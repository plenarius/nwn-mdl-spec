#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""nwn-mdl-spec conformance runner (standard library only).

  mdlconf.py run --impl NAME --cmd 'COMMAND' [--only PROBE ...] [--json OUT]
      Run an implementation through the suite. COMMAND is called as
          COMMAND compile   <in.mdl> <out.mdl>
          COMMAND decompile <in.mdl> <out.mdl>
      (see runner/README.md for the contract). Each probe with a golden is
      compiled (the output decoded and compared with expected/<probe>.json)
      and its golden decompiled (the ASCII read and compared likewise).

  mdlconf.py expect [--second DIR]
      Regenerate conformance/expected/*.json from conformance/goldens/. With
      --second, a second engine compile of the same probes: any field that
      differs between the two compiles is listed as volatile (uninitialised
      memory in the engine's output) and never compared.

  mdlconf.py check-goldens DIR
      Compare freshly made goldens (e.g. after a game patch) with the
      expected files and report what changed.

  mdlconf.py roundtrip --impl NAME --cmd 'COMMAND' [--resource-dir DIR ...] PATH ...
      Decompile every binary model under PATH (files or folders, searched
      recursively), compile the ASCII back, and compare both with the
      original under the same rules as the suite, the original standing in
      for the golden. Then decompile and compile the result once more: the
      second binary must be byte-identical to the first. The implementation
      finds supermodels, skeletons and materials in the original's folder and
      the --resource-dir folders, which it is given in MDLCONF_RESOURCE_DIRS.
      Failures are grouped by cause. Exits 1 unless every model passes.

  mdlconf.py view FILE
      Print the JSON view of a binary or ASCII model.
"""
import argparse
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import approvals  # noqa: E402
import mdlview  # noqa: E402
import nodefacts  # noqa: E402

ROOT = os.path.dirname(HERE)
CONF = os.path.join(ROOT, 'conformance')
BUILD = '89.8193.37-17'

# Fields never compared: uninitialised or runtime values in the engine's
# output (spec/binary.md, MDL-BIN-050/051; engine/behaviour.md E55).
ALWAYS_VOLATILE = {'lightmapped'}


# ------------------------------------------------------------ helpers

def load_manifest():
    with open(os.path.join(CONF, 'manifest.json')) as f:
        return json.load(f)['probes']


def flat(o, p=''):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, '%s.%s' % (p, k) if p else k)
    elif isinstance(o, list):
        if not o:
            yield p, []
        for i, v in enumerate(o):
            yield from flat(v, '%s[%d]' % (p, i))
    else:
        yield p, o


def normalise(view):
    """The expected-file form of a decoded golden."""
    m = view['model']
    out = {'model': {k: m[k] for k in ('name', 'classification', 'fog', 'animationscale', 'supermodel',
                                       'node_count', 'bmin', 'bmax', 'radius')},
           'nodes': [], 'animations': []}
    for n in view['nodes']:
        nn = {k: v for k, v in n.items()}
        if 'mesh' in nn:
            nn['mesh'] = {k: v for k, v in nn['mesh'].items() if k not in ALWAYS_VOLATILE}
        out['nodes'].append(nn)
    for a in view['animations']:
        aa = {k: a[k] for k in ('name', 'length', 'transtime', 'animroot', 'events', 'node_count')}
        aa['nodes'] = []
        for n in a['nodes']:
            # In an animation only these mean anything: the type-specific
            # headers hold uninitialised memory (E55).
            nn = {k: n[k] for k in ('name', 'parent', 'type', 'flags', 'number', 'controllers')}
            if 'animmesh' in n:
                nn['animmesh'] = n['animmesh']
            aa['nodes'].append(nn)
        out['animations'].append(aa)
    return out


# ------------------------------------------------------------ comparison

class Report:
    def __init__(self, facts=False):
        self.items = []  # (level, path, message)
        # With facts=True (roundtrip), what the approvals (runner/approvals.py)
        # need to know about a failing mesh or a renamed node, by path.
        self.facts = {} if facts else None

    def add(self, level, path, msg):
        self.items.append((level, path, msg))

    def must(self, path, msg):
        self.add('must', path, msg)

    def should(self, path, msg):
        self.add('should', path, msg)

    @property
    def failed(self):
        return any(l == 'must' for l, _, _ in self.items)


def fval(x):
    if isinstance(x, str):
        return {'nan': math.nan, 'inf': math.inf, '-inf': -math.inf}.get(x, x)
    return x


def close(a, b, tol):
    a, b = fval(a), fval(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        if math.isinf(a) or math.isinf(b):
            return a == b
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def vclose(a, b, tol):
    if not isinstance(a, list) or not isinstance(b, list):
        return close(a, b, tol)
    return len(a) == len(b) and all(vclose(x, y, tol) for x, y in zip(a, b))


def qclose(a, b, tol):
    """Quaternions: q and -q are the same rotation."""
    return vclose(a, b, tol) or vclose(a, [-fval(x) for x in b], tol)


def node_key(n):
    return n['name'].lower()


def drawn(mesh):
    """Triangles as drawn: the index list when there is one (it is what the
    game draws, E31), else the face list."""
    il = mesh.get('index_lists') or []
    if il and il[0]:
        idx = il[0]
        return [idx[i:i + 3] for i in range(0, len(idx) - len(idx) % 3, 3)]
    return [f['v'] for f in mesh.get('faces', [])]


def corner_attrs(mesh, vi):
    v = mesh.get('vertices', {})
    out = {}
    for k, vals in v.items():
        if isinstance(vals, list) and 0 <= vi < len(vals):
            out[k] = vals[vi]
    return out


TOL = {'position': 1e-5, 'uv0': 1e-5, 'uv1': 1e-5, 'uv2': 1e-5, 'uv3': 1e-5,
       'normal': 1e-4, 'tangent': 1e-3, 'handedness': 0.5, 'color': 0}


def compare_mesh(r, path, exp, act, profile, volatile, aabb=False, face_indices=True):
    vol = lambda k: ('%s.%s' % (path, k)) in volatile  # noqa: E731
    fields = ['diffuse', 'ambient', 'specular', 'shininess', 'shadow', 'beaming', 'render',
              'transparencyhint', 'renderhint', 'tilefade', 'rotatetexture', 'textures']
    for k in fields:
        if vol(k) or k not in exp:
            continue
        a = act.get(k)
        if a is None and profile == 'decompile':
            a = (AABB_DEFAULTS if aabb else MESH_DEFAULTS).get(k)
        if k == 'textures' and isinstance(a, list):
            # NULL is the ASCII word for none; the engine stores it as text.
            nul = lambda t: '' if t.upper() == 'NULL' else t.lower()  # noqa: E731
            e = [nul(t) for t in exp[k]]
            a = [nul(t) for t in a] + [''] * (4 - len(a))
            if e != a[:4]:
                r.must('%s.%s' % (path, k), 'expected %s, got %s' % (exp[k], act.get(k)))
            continue
        if not vclose(exp[k], a, 1e-5):
            r.must('%s.%s' % (path, k), 'expected %s, got %s' % (exp[k], a))
    et, at = drawn(exp), drawn(act)
    if len(et) != len(at):
        r.must(path + '.triangles', 'expected %d drawn triangles, got %d' % (len(et), len(at)))
    if profile == 'compile':
        if exp.get('vertex_count') != act.get('vertex_count'):
            r.must(path + '.vertex_count', 'expected %s, got %s' % (exp.get('vertex_count'), act.get('vertex_count')))
        if exp.get('face_count') != act.get('face_count'):
            r.must(path + '.face_count', 'expected %s, got %s' % (exp.get('face_count'), act.get('face_count')))
    bad = {}
    for ti, (ef, af) in enumerate(zip(et, at)):
        for k in range(3):
            ea, aa = corner_attrs(exp, ef[k]), corner_attrs(act, af[k])
            for attr, ev in ea.items():
                if attr not in TOL:
                    continue
                av = aa.get(attr)
                level = 'must'
                if attr in ('tangent', 'handedness') and profile == 'decompile':
                    level = 'should'
                if av is None:
                    if attr == 'color' and all(c == [255, 255, 255, 255] for c in exp['vertices']['color']):
                        level = 'should'  # all white: the same as no colour stream
                    bad.setdefault((attr, level), []).append('triangle %d corner %d: missing' % (ti, k))
                    continue
                if attr == 'handedness':
                    ok = (fval(ev) < 0) == (fval(av) < 0)
                else:
                    ok = vclose(ev, av, TOL[attr])
                if not ok:
                    bad.setdefault((attr, level), []).append('triangle %d corner %d: expected %s, got %s' % (ti, k, ev, av))
            for attr in aa:
                if attr in TOL and attr not in ea and attr not in ('handedness',):
                    if not (attr == 'color' and aa[attr] == [255, 255, 255, 255]):
                        bad.setdefault((attr, 'should'), []).append('present but the golden has none')
                        break
    for (attr, level), msgs in bad.items():
        r.add(level, '%s.%s' % (path, attr), '%d corner(s) differ; first: %s' % (len(msgs), msgs[0]))
    # face materials
    ef, af = exp.get('faces', []), act.get('faces', [])
    if len(ef) == len(af):
        diff = [i for i, (x, y) in enumerate(zip(ef, af)) if x.get('material') != y.get('material')]
        if diff:
            r.must(path + '.faces.material', 'face %d: expected %s, got %s' % (diff[0], ef[diff[0]]['material'], af[diff[0]]['material']))
    if profile == 'compile':
        if face_indices and len(ef) == len(af):
            # The face records keep the original vertex where tangent
            # generation cloned it; only the index list names the clone
            # (MDL-MESH-043, MDL-BIN-049). Against a golden, the records'
            # vertex indices must be the engine's. Not in a round trip, where
            # the original's compiler numbered the vertices its own way.
            diff = [i for i, (x, y) in enumerate(zip(ef, af)) if x.get('v') != y.get('v')]
            if diff:
                r.must(path + '.faces.v', '%d face(s) differ; first face %d: expected %s, got %s'
                       % (len(diff), diff[0], ef[diff[0]].get('v'), af[diff[0]].get('v')))
        if exp.get('index_lists') and act.get('index_lists') and drawn(exp) != drawn(act):
            r.should(path + '.vertex_order', 'same triangles, different vertex numbering or order')
        for k in ('bmin', 'bmax', 'radius', 'average'):
            if k in exp and not vol(k) and not vclose(exp[k], act.get(k), 1e-4):
                r.should('%s.%s' % (path, k), 'expected %s, got %s' % (exp[k], act.get(k)))
        if len(ef) == len(af):
            for k, tol in (('normal', 1e-4), ('distance', 1e-4), ('adjacent', 0)):
                diff = [i for i, (x, y) in enumerate(zip(ef, af)) if not vclose(x.get(k), y.get(k), tol)]
                if diff:
                    r.should('%s.faces.%s' % (path, k), '%d face(s) differ; first face %d: expected %s, got %s'
                             % (len(diff), diff[0], ef[diff[0]].get(k), af[diff[0]].get(k)))


CORNER_ATTRS = ('position', 'uv0', 'uv1', 'uv2', 'uv3', 'normal', 'tangent', 'handedness', 'color')


def _has_nan(x):
    if isinstance(x, list):
        return any(_has_nan(y) for y in x)
    x = fval(x)
    return isinstance(x, float) and math.isnan(x)


def _freeze(x):
    if isinstance(x, list):
        return tuple(_freeze(y) for y in x)
    return fval(x)


def bad_tangent(t):
    """A NaN, infinite or zero tangent (MDL-BIN-048)."""
    if not isinstance(t, list) or len(t) < 3:
        return True
    x, y, z = (fval(c) for c in t[:3])
    try:
        q = x * x + y * y + z * z
    except TypeError:
        return True
    return not math.isfinite(q) or q == 0


def tri_area2(pos, tri):
    """Twice the area of a triangle (exactly 0 when two corners share a
    position), None when a corner is out of range or not finite."""
    try:
        p = [[float(fval(c)) for c in pos[i]] for i in tri]
    except (IndexError, TypeError):
        return None
    u = [p[1][k] - p[0][k] for k in range(3)]
    w = [p[2][k] - p[0][k] for k in range(3)]
    c = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    q = c[0] * c[0] + c[1] * c[1] + c[2] * c[2]
    return math.sqrt(q) if math.isfinite(q) else None


def mesh_streams(mesh):
    """The vertex streams a mesh holds; an all-white colour stream counts as
    none (MDL-MESH-061)."""
    v = mesh.get('vertices', {})
    s = {k for k, vals in v.items() if isinstance(vals, list) and vals}
    if 'color' in s and all(c == [255, 255, 255, 255] for c in v['color']):
        s.discard('color')
    return s


def left_out_tangents(rep):
    """The mesh paths whose decompile findings say only that the ASCII has
    no tangents (and so no handedness): every corner 'missing'."""
    out = {}
    for lvl, pth, msg in rep.items:
        for attr in ('tangent', 'handedness'):
            if pth.endswith('.mesh.' + attr) and lvl == 'should' and msg.endswith(': missing') \
                    and re.match(r'(\d+) corner\(s\) differ; first: triangle \d+ corner \d+: missing$', msg):
                out.setdefault(pth[:-len(attr) - 1], []).append((lvl, pth, msg))
    return out


def tangents_regenerated(exp_mesh, comp_mesh):
    """Whether a compile of the ASCII gives exactly the original's tangents
    and handedness: the same drawn triangles, and at each corner, in order,
    the same tangent and handedness floats (MDL-MESH-043)."""
    et, ct = drawn(exp_mesh), drawn(comp_mesh)
    ev, cv = exp_mesh.get('vertices', {}), comp_mesh.get('vertices', {})
    if len(et) != len(ct) or not et:
        return False
    for attr in ('tangent', 'handedness'):
        if attr not in ev:
            continue
        if attr not in cv:
            return False
        for x, y in zip(et, ct):
            for k in range(3):
                if not (x[k] < len(ev[attr]) and y[k] < len(cv[attr])):
                    return False
                if _freeze(ev[attr][x[k]]) != _freeze(cv[attr][y[k]]):
                    return False
    return 'tangent' in ev


def accept_left_out_tangents(rep, exp, compiled):
    """Move the decompile findings of meshes whose ASCII left the tangents
    out to a list of accepted ones, when compiling that ASCII (`compiled`, a
    binary view) gives exactly the original's tangents: cleanmodels leaves
    out tangents a compile makes again, so that the vertex order survives
    (cleanmodels PR #137). Returns the accepted findings."""
    meshes = left_out_tangents(rep)
    if not meshes or compiled is None:
        return []
    exp_nodes = {n['name'].lower(): n for n in exp['nodes']}
    cmp_nodes = {n['name'].lower(): n for n in compiled['nodes']}
    ok = set()
    for mp in meshes:
        m = re.match(r'^nodes\[([^\]#]*)\]\.mesh$', mp)
        if not m:
            continue
        e, c = exp_nodes.get(m.group(1).lower()), cmp_nodes.get(m.group(1).lower())
        if e and c and 'mesh' in e and 'mesh' in c and tangents_regenerated(e['mesh'], c['mesh']):
            ok.add(mp)
    accepted = [x for mp in ok for x in meshes[mp]]
    rep.items = [x for x in rep.items if x not in accepted]
    return [[pth, msg + ' [accepted: compiling the ASCII gives exactly these tangents]']
            for _, pth, msg in accepted]


def mesh_facts(e, a, own_nodes):
    """What a compiled mesh keeps of the original's, for the approvals: the
    drawn triangles paired in order, an original triangle the compile did not
    draw counted as dropped (with whether it has zero area), and per paired
    corner which attributes differ (with the tolerances of compare_mesh),
    including skin weights, dangly constraints and face materials. Also the
    number of distinct vertices the original draws by the game's merge key
    (MDL-MESH-010, floats compared exactly)."""
    em, am = e['mesh'], a['mesh']
    et, at = drawn(em), drawn(am)
    ml = merged_list(em)
    if ml:
        # A receiver of a merged render list: its own faces' triangles come
        # first in its index list, in face order, then the copies of other
        # meshes' (MDL-BIN-049). The compile is paired with that beginning:
        # where the copies are drawn is for merged-render-lists to judge.
        et = et[:max(ml[0], len(at))]
    ev, av = em.get('vertices', {}), am.get('vertices', {})
    es, as_ = mesh_streams(em), mesh_streams(am)
    both = [k for k in CORNER_ATTRS if k in es and k in as_]
    epos = ev.get('position', [])
    # skin weights by bone name, unless bound to a skeleton (compare_skin)
    skin = None
    ew = aw = None
    if 'skin' in e or 'skin' in a:
        sk = e.get('skin') or {}
        if 'skin' not in e or 'skin' not in a:
            skin = 'one side'
        elif sk.get('bone_map_count', 0) > own_nodes:
            skin = 'unresolved'
        else:
            ew, aw = sk.get('weights', []), a['skin'].get('weights', [])
            skin = 'same'
    ec = (e.get('dangly') or {}).get('constraints')
    ac = (a.get('dangly') or {}).get('constraints')
    constraints = None
    if ec is not None or ac is not None:
        constraints = 'same' if ec is not None and ac is not None else 'one side'

    def weights(w, i):
        return sorted((n.lower(), x) for n, x in (w[i] if i < len(w) else []))

    def corner_diff(ei, ai):
        out = []
        for k in both:
            ex, ax = ev[k], av[k]
            if not (0 <= ei < len(ex)) or not (0 <= ai < len(ax)):
                out.append(k)
                continue
            if k == 'handedness':
                if (fval(ex[ei]) < 0) != (fval(ax[ai]) < 0):
                    out.append(k)
            elif not vclose(ex[ei], ax[ai], TOL[k]):
                out.append(k)
        if skin == 'same':
            we, wa = weights(ew, ei), weights(aw, ai)
            if [n for n, _ in we] != [n for n, _ in wa] or not vclose([x for _, x in we], [x for _, x in wa], 1e-4):
                out.append('skin')
        if constraints == 'same':
            ce = ec[ei] if 0 <= ei < len(ec) else None
            ca = ac[ai] if 0 <= ai < len(ac) else None
            if not close(ce, ca, 1e-4):
                out.append('constraint')
        return out

    def same_place(ti, tj):
        for k in range(3):
            for attr in ('position', 'uv0'):
                if attr in both:
                    x, y = ev[attr], av[attr]
                    i, j = et[ti][k], at[tj][k]
                    if not (0 <= i < len(x) and 0 <= j < len(y)) or not vclose(x[i], y[j], TOL[attr]):
                        return False
        return True

    # Pair the drawn triangles in order. With fewer compiled triangles, an
    # original one that is not where the next compiled one is was dropped.
    pairs, dropped = [], []
    if len(et) == len(at):
        pairs = list(zip(range(len(et)), range(len(at))))
        extra = 0
    else:
        i = j = 0
        while i < len(et):
            if j < len(at) and (len(et) - i <= len(at) - j or same_place(i, j)):
                pairs.append((i, j))
                j += 1
            else:
                dropped.append(i)
            i += 1
        extra = len(at) - j
    differ, at_bad = {}, {}
    etan = ev.get('tangent') if 'tangent' in both else None
    for ti, tj in pairs:
        for k in range(3):
            ei, ai = et[ti][k], at[tj][k]
            for attr in corner_diff(ei, ai):
                differ[attr] = differ.get(attr, 0) + 1
                if attr in ('tangent', 'handedness') and etan is not None and \
                        (not (0 <= ei < len(etan)) or bad_tangent(etan[ei])):
                    at_bad[attr] = at_bad.get(attr, 0) + 1
    areas = [tri_area2(epos, et[ti]) for ti in dropped]
    ef, af = em.get('faces', []), am.get('faces', [])
    material = None
    if len(ef) == len(et) and len(af) == len(at):
        material = sum(1 for ti, tj in pairs if ef[ti].get('material') != af[tj].get('material'))
    # distinct original vertices by the merge key (NaN never equals itself)
    used = sorted({i for t in et for i in t})
    keys = set()
    streams = sorted(k for k in ev if isinstance(ev[k], list))
    for i in used:
        key = [ev[k][i] if i < len(ev[k]) else None for k in streams]
        if ew is not None:
            key.append(weights(ew, i))
        if ec is not None:
            key.append(ec[i] if i < len(ec) else None)
        keys.add(('nan', i) if _has_nan(key) else _freeze(key))
    f = {'vertices': [em.get('vertex_count'), am.get('vertex_count')],
         'distinct': len(keys),
         'triangles': [len(et), len(at)],
         'faces': [len(ef), len(af)],
         'paired': len(pairs),
         'dropped': len(dropped),
         'dropped_nonzero': sum(1 for x in areas if x != 0),
         'extra': extra,
         'differ': differ,
         'differ_bad_tangent': at_bad,
         'material_differ': material,
         'streams_only_original': sorted(es - as_),
         'streams_only_compiled': sorted(as_ - es),
         'aabb': bool(e['flags'] & 0x200)}
    if ml:
        f['merged_list'] = list(ml)
    if dropped:
        f['dropped_max_area'] = max((x for x in areas if x is not None), default=None)
    if em.get('texanim_slots_used'):
        f['texanim_slots'] = em['texanim_slots_used']
    if am.get('texanim_slots_used'):
        f['texanim_slots_compiled'] = am['texanim_slots_used']
    if skin is not None:
        f['skin'] = skin if skin != 'same' or 'skin' not in differ else 'differ'
    if constraints is not None:
        f['constraints'] = constraints if constraints != 'same' or 'constraint' not in differ else 'differ'
    return f


# ------------------------------------------------------------ merged render lists

# What decides how a triangle is drawn besides its corners: the drawing
# mesh's state, its node type, and the first key of its alpha and
# selfillumcolor controllers (defaults 1 and 0 0 0).
RL_STATE = ('textures', 'diffuse', 'ambient', 'specular', 'shininess', 'transparencyhint', 'renderhint',
            'tilefade', 'beaming', 'rotatetexture', 'triangle_mode')
RL_MOVING = ('position', 'orientation', 'scale', 'alpha', 'selfillumcolor')
RL_PAIR = {'position': 1e-3, 'uv0': 1e-4}  # metres in world space; UV units
RL_TOL = {'uv1': 1e-4, 'uv2': 1e-4, 'uv3': 1e-4, 'normal': 1e-3, 'tangent': 1e-2}
RL_GRID = 0.01


def merged_list(mesh):
    """(own triangles, index-list triangles) of a receiver: a mesh whose first
    index list holds more triangles than its face list (MDL-BIN-049: its own
    faces' triangles in face order, then copies of other meshes'), else
    None."""
    il = mesh.get('index_lists') or []
    n = len(il[0]) // 3 if il and il[0] else 0
    nf = len(mesh.get('faces', []))
    return (nf, n) if n > nf else None


def _ff(x):
    try:
        return float(fval(x))
    except (TypeError, ValueError):
        return math.nan


def _first_key(node, name):
    for c in node.get('controllers', []):
        if c.get('name') == name and c.get('keys'):
            return c['keys'][0].get('v')
    return None


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def _qrot(q, v):
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


def _world(view):
    """Per node: (rotation, scale, translation, chain of node indices), from
    the first key of each node's position, orientation and scale up the
    parent chain; p_world = q * (s * p) + t."""
    out, byname = [], {}
    for i, nd in enumerate(view['nodes']):
        pos, ori, sc = (_first_key(nd, k) for k in ('position', 'orientation', 'scale'))
        t = tuple(_ff(c) for c in pos[:3]) if pos and len(pos) >= 3 else (0.0, 0.0, 0.0)
        q = tuple(_ff(c) for c in ori[:4]) if ori and len(ori) >= 4 else (0.0, 0.0, 0.0, 1.0)
        n = math.sqrt(sum(c * c for c in q)) if all(math.isfinite(c) for c in q) else 0
        q = tuple(c / n for c in q) if n else (0.0, 0.0, 0.0, 1.0)
        s = _ff(sc[0]) if sc else 1.0
        pi = byname.get((nd.get('parent') or '').lower())
        if pi is None:
            out.append((q, s, t, (i,)))
        else:
            pq, ps, pt, chain = out[pi]
            st = _qrot(pq, tuple(ps * c for c in t))
            out.append((_qmul(pq, q), ps * s, tuple(st[k] + pt[k] for k in range(3)), chain + (i,)))
        byname.setdefault(nd['name'].lower(), i)
    return out


def animated_names(view):
    """The names of the nodes an animation moves or fades: a position,
    orientation, scale, alpha or selfillumcolor controller with keys of more
    than one value."""
    out = set()
    for an in view.get('animations', []):
        for nd in an.get('nodes', []):
            for c in nd.get('controllers', []):
                if c.get('name') in RL_MOVING and len({_freeze(k.get('v')) for k in c.get('keys', [])}) > 1:
                    out.add(nd['name'].lower())
    return out


def supermodel_animated(name, dirs, depth=0):
    """animated_names of a supermodel and its own supermodels (their
    animations play on this model's nodes of the same name), found as
    find_supermodel finds them; None when one is named but not found."""
    name = (name or '').strip().lower()
    if not name or name == 'null':
        return set()
    if depth > 8:
        return None
    data = _supermodel_data(name, dirs)
    if data is None:
        return None
    view = mdlview.read_binary(data) if data[:4] == b'\0\0\0\0' else mdlview.read_ascii(data.decode('latin-1'))
    up = supermodel_animated(view['model'].get('supermodel'), dirs, depth + 1)
    return None if up is None else up | animated_names(view)


def _draw_state(nd):
    m = nd['mesh']
    st = {'type': nd['flags']}
    for k in RL_STATE:
        v = m.get(k)
        if k == 'textures':
            v = [('' if (t or '').upper() == 'NULL' else (t or '').lower()) for t in (v or [])]
            v = v + [''] * (4 - len(v))
        st[k] = _freeze(v)
    a, s = _first_key(nd, 'alpha'), _first_key(nd, 'selfillumcolor')
    st['alpha'] = _freeze(a[:1]) if a else (1,)
    st['selfillumcolor'] = _freeze(s[:3]) if s else (0, 0, 0)
    return st


def _rl_tris(view, mode, moving):
    """The triangles a model draws ('draw': each mesh with render != 0, from
    its first index list, MDL-BIN-049) or projects as shadow volumes
    ('shadow': each mesh with shadow or beaming != 0, from its face list), in
    world space. Skins, animmeshes and AABB walkmeshes are left out (deformed,
    or never drawn). An entry is None when a corner is out of range or not
    finite."""
    xf = _world(view)
    out = []
    for i, nd in enumerate(view['nodes']):
        m = nd.get('mesh')
        if not m or nd['flags'] & (mdlview.F_SKIN | mdlview.F_ANIM | mdlview.F_AABB):
            continue
        if mode == 'draw':
            if not m.get('render'):
                continue
            il = m.get('index_lists') or []
            idx = il[0] if il else []
            tl = [idx[k:k + 3] for k in range(0, len(idx) - 2, 3)]
            st = _draw_state(nd)
        else:
            if not (m.get('shadow') or m.get('beaming')):
                continue
            tl = [f['v'] for f in m.get('faces', [])]
            a = _first_key(nd, 'alpha')
            st = {'shadow': m.get('shadow'), 'beaming': m.get('beaming'), 'alpha': _freeze(a[:1]) if a else (1,)}
        q, s, t, chain = xf[i]
        mv = any(view['nodes'][j]['name'].lower() in moving for j in chain)
        v = m.get('vertices', {})
        pos = v.get('position', [])
        for tri in tl:
            if len(tri) != 3 or any(not (0 <= c < len(pos)) for c in tri):
                out.append(None)
                continue
            corners = []
            for c in tri:
                lp = [_ff(x) for x in pos[c]]
                p = _qrot(q, tuple(s * x for x in lp))
                cn = {'p': tuple(p[k] + t[k] for k in range(3))}
                corners.append(cn)
                if mode == 'shadow':
                    continue  # a shadow volume is built from positions alone
                for k in ('uv0', 'uv1', 'uv2', 'uv3'):
                    if k in v and c < len(v[k]):
                        cn[k] = tuple(_ff(x) for x in v[k][c])
                if 'normal' in v and c < len(v['normal']):
                    cn['n'] = _qrot(q, tuple(_ff(x) for x in v['normal'][c]))
                if 'tangent' in v and c < len(v['tangent']):
                    cn['bad_t'] = bad_tangent(v['tangent'][c])
                    cn['t'] = _qrot(q, tuple(_ff(x) for x in v['tangent'][c]))
                    if 'handedness' in v and c < len(v['handedness']):
                        cn['h'] = _ff(v['handedness'][c]) < 0
                if 'color' in v and c < len(v['color']):
                    cn['c'] = tuple(v['color'][c])
            if not all(math.isfinite(x) for cn in corners for x in cn['p'] + cn.get('uv0', ())):
                out.append(None)
                continue
            out.append({'node': nd['name'].lower(), 'state': st, 'moving': mv, 'corners': corners,
                        'zero': tri_area2(pos, tri) == 0})
    return out


def _rl_cell(tr):
    return tuple(int(math.floor(sum(cn['p'][k] for cn in tr['corners']) / 3 / RL_GRID)) for k in range(3))


def _rl_rotation(a, b):
    """r with a's corner j where b's corner (j + r) % 3 is (the winding kept),
    within RL_PAIR, or None."""
    for r in range(3):
        if all(max(abs(x['p'][k] - y['p'][k]) for k in range(3)) <= RL_PAIR['position'] and
               (('uv0' in x) == ('uv0' in y)) and
               ('uv0' not in x or max(abs(x['uv0'][k] - y['uv0'][k]) for k in range(2)) <= RL_PAIR['uv0'])
               for x, y in ((a['corners'][j], b['corners'][(j + r) % 3]) for j in range(3))):
            return r
    return None


def _rl_pair(orig, comp):
    """Pair each original triangle with one compiled triangle at the same
    place (corners within RL_PAIR, in the same winding), the same node first
    and then any node. Returns (pairs [(i, j, r)], lost [i], extra [j])."""
    grid = {}
    for j, tr in enumerate(comp):
        if tr is not None:
            grid.setdefault(_rl_cell(tr), []).append(j)
    used, pairs, done = set(), [], set()
    for same_node in (True, False):
        for i, tr in enumerate(orig):
            if tr is None or i in done:
                continue
            c = _rl_cell(tr)
            found = None
            for d in ((x, y, z) for x in (0, -1, 1) for y in (0, -1, 1) for z in (0, -1, 1)):
                for j in grid.get((c[0] + d[0], c[1] + d[1], c[2] + d[2]), ()):
                    if j in used or (same_node and comp[j]['node'] != tr['node']):
                        continue
                    r = _rl_rotation(tr, comp[j])
                    if r is not None:
                        found = (j, r)
                        break
                if found:
                    break
            if found:
                used.add(found[0])
                done.add(i)
                pairs.append((i, found[0], found[1]))
    lost = [i for i, tr in enumerate(orig) if tr is not None and i not in done]
    extra = [j for j, tr in enumerate(comp) if tr is not None and j not in used]
    return pairs, lost, extra


def _rl_compare(orig, comp):
    pairs, lost, extra = _rl_pair(orig, comp)
    f = {'original': len(orig), 'compiled': len(comp), 'paired': len(pairs),
         'unreadable': [sum(1 for t in orig if t is None), sum(1 for t in comp if t is None)],
         'lost': len(lost), 'lost_nonzero': sum(1 for i in lost if not orig[i]['zero']),
         'extra': len(extra), 'extra_nonzero': sum(1 for j in extra if not comp[j]['zero']),
         'state_differ': {}, 'moving_differ': 0, 'corner_differ': {}, 'bad_tangent': 0, 'tangent_baked': 0,
         'max_delta': {'position': 0.0, 'uv0': 0.0}, 'moved': {}}

    def bump(d, k):
        d[k] = d.get(k, 0) + 1

    white = (255, 255, 255, 255)
    for i, j, r in pairs:
        a, b = orig[i], comp[j]
        if a['node'] != b['node']:
            f['moved'].setdefault(b['node'], set()).add(a['node'])
        for k, v in a['state'].items():
            if b['state'].get(k) != v:
                bump(f['state_differ'], k)
        if a['moving'] != b['moving']:
            f['moving_differ'] += 1
        for jj in range(3):
            x, y = a['corners'][jj], b['corners'][(jj + r) % 3]
            f['max_delta']['position'] = max(f['max_delta']['position'],
                                             max(abs(x['p'][k] - y['p'][k]) for k in range(3)))
            if 'uv0' in x:
                f['max_delta']['uv0'] = max(f['max_delta']['uv0'], max(abs(x['uv0'][k] - y['uv0'][k]) for k in range(2)))
            for k in ('uv1', 'uv2', 'uv3'):
                if (k in x) != (k in y) or (k in x and not vclose(list(x[k]), list(y[k]), RL_TOL[k])):
                    bump(f['corner_differ'], k)
            if ('n' in x) != ('n' in y) or ('n' in x and not vclose(list(x['n']), list(y['n']), RL_TOL['normal'])):
                bump(f['corner_differ'], 'normal')
            if 't' in x and x['bad_t']:
                f['bad_tangent'] += 1  # what the original drew here is undefined (MDL-BIN-048)
            elif 't' in x and 't' in y:
                if not vclose(list(x['t']), list(y['t']), RL_TOL['tangent']):
                    bump(f['corner_differ'], 'tangent')
                if x.get('h') != y.get('h'):
                    bump(f['corner_differ'], 'handedness')
            elif 't' in y:
                f['tangent_baked'] += 1  # the compile baked tangents the original had none of
            elif 't' in x:
                bump(f['corner_differ'], 'tangent')
            if x.get('c', white) != y.get('c', white):
                bump(f['corner_differ'], 'color')
    f['moved'] = {k: sorted(v) for k, v in sorted(f['moved'].items())}
    return f


def render_list_facts(exp, comp, super_moving=frozenset()):
    """What a model with merged render lists draws and projects as shadows in
    its compile against the original, compared across the whole model in
    world space (for the approval merged-render-lists, runner/approvals.py).

    Every drawn triangle (meshes with render != 0, from the index list) and
    every shadow face (meshes with shadow or beaming != 0, from the face list,
    whatever render says: MDL-MESH-063) of each model is placed in world space
    (first keys of position, orientation and scale up the parent chain) and
    paired one to one with a triangle of the other model at the same place
    (corners within RL_PAIR, winding kept), the same node first. Per pair the
    drawing state (RL_STATE, node type, alpha, selfillumcolor), whether an
    animation (the model's own or its supermodel's, `super_moving`) moves or
    fades the drawing node or an ancestor, and the corners' UV1-3, normal,
    tangent, handedness and colour are compared. Tangents the original holds
    as NaN, infinite or zero are counted apart (`bad_tangent`), as are
    tangents only the compile has (`tangent_baked`). A triangle left without
    a pair is counted, and whether it has area.

    `receivers` are the original's meshes whose index list holds more
    triangles than their faces (merged_list); `donor_candidates` the
    original's meshes with render 0, no index list and faces; `moved` the
    compiled nodes that draw triangles another node drew in the original,
    with those nodes."""
    rec, cand, names, deformed = [], [], [], 0
    for nd in exp['nodes']:
        names.append(nd['name'].lower())
        m = nd.get('mesh')
        if not m or nd['flags'] & mdlview.F_AABB:
            continue
        if merged_list(m):
            rec.append(nd['name'].lower())
            if nd['flags'] & (mdlview.F_SKIN | mdlview.F_ANIM):
                deformed += 1
        il = m.get('index_lists') or []
        if not m.get('render') and not (il and il[0]) and m.get('faces'):
            cand.append(nd['name'].lower())
    f = {'receivers': rec, 'donor_candidates': cand, 'receivers_deformed': deformed,
         'unique': len(set(names)) == len(names)}
    for mode in ('draw', 'shadow'):
        ot = _rl_tris(exp, mode, animated_names(exp) | super_moving)
        ct = _rl_tris(comp, mode, animated_names(comp) | super_moving)
        f[mode] = _rl_compare(ot, ct)
    return f


MESH_DEFAULTS = {'diffuse': [1, 1, 1], 'ambient': [1, 1, 1], 'specular': [0, 0, 0], 'shininess': 1,
                 'shadow': 1, 'beaming': 0, 'render': 1, 'transparencyhint': 0, 'renderhint': 0,
                 'tilefade': 0, 'rotatetexture': 0, 'textures': ['', '', '', '']}
# The engine's values for an aabb node with no render/shadow line (zspec_aabbdef).
AABB_DEFAULTS = dict(MESH_DEFAULTS, render=0, shadow=0)
LIGHT_DEFAULTS = {'flareradius': 0, 'flaresizes': [], 'flarepositions': [], 'flarecolorshifts': [],
                  'texturenames': [], 'lightpriority': 5, 'ambientonly': 0, 'ndynamictype': 1,
                  'affectdynamic': 1, 'shadow': 1, 'generateflare': 0, 'fadinglight': 1}
EMITTER_DEFAULTS = {'deadspace': 0, 'blastradius': 0, 'blastlength': 0, 'spawntype': 0, 'chunkname': '',
                    'twosidedtex': 0, 'loop': 0, 'renderorder': 0, 'flags': 0}


def compare_section(r, path, exp, act, defaults, profile, volatile, tol=1e-5):
    for k, ev in exp.items():
        p = '%s.%s' % (path, k)
        if p in volatile or any(v.startswith(p + '[') for v in volatile):
            continue
        av = act.get(k) if act else None
        if av is None and profile == 'decompile':
            av = defaults.get(k)
        if isinstance(ev, str) and isinstance(av, str):
            # NULL is the ASCII word for none (refModel NULL, chunkName NULL)
            nul = lambda t: '' if t.upper() == 'NULL' else t.lower()  # noqa: E731
            if nul(ev) != nul(av):
                r.must(p, 'expected %r, got %r' % (ev, av))
        elif not vclose(ev, av, tol):
            r.must(p, 'expected %s, got %s' % (ev, av))


def runtime_padded(flags, c, keys):
    """Each key's value padded to the controller's width with the values the
    engine's runtime field starts with (MDL-CTRL-014): a controller with fewer
    columns writes only its first floats. None for orientation, whose runtime
    quaternion is held w first, or when the width is unknown."""
    cdef = mdlview.controller_def(flags, c['id'])
    width = cdef.get('columns') if cdef else None
    if not width or c['name'] == 'orientation':
        return None
    init = cdef.get('default')
    init = init if isinstance(init, list) else [init if init is not None else 0] * width
    out = []
    for k in keys:
        v = list(k.get('v') or [])
        out.append((k['t'], v + init[len(v):width] if len(v) < width else v[:width]))
    return out


def skipped_count(c):
    """A column count the engine skips (MDL-CTRL-014), detonate aside."""
    return c['name'] != 'detonate' and c['columns'] not in (1, 3, 4)


def compare_controllers(r, path, exp, act, profile, flags):
    tol = 1e-5 if profile == 'compile' else 1e-4
    # A node may hold several controllers of one id (a keyword given twice,
    # MDL-CTRL-036). The engine applies them in order, so the last one's
    # value is what the node keeps: the last of each side is compared in
    # full, the earlier ones only as SHOULD.
    amap, emap = {}, {}
    for c in act:
        amap.setdefault(c['id'], []).append(c)
    for c in exp:
        emap.setdefault(c['id'], []).append(c)
    pairs = []
    for cid, es in emap.items():
        as_ = amap.pop(cid, [])
        p = '%s.controllers[%s]' % (path, es[0]['name'])
        if len(es) > 1 or len(as_) > 1:
            if len(es) != len(as_):
                r.should(p, 'the golden has %d controllers of id %d, got %d; the last one is compared, '
                            'which is the value the engine applies (MDL-CTRL-036)' % (len(es), cid, len(as_)))
            else:
                for i, (c, a) in enumerate(zip(es[:-1], as_[:-1])):
                    ks = [(ek.get('v'), ak.get('v')) for ek, ak in zip(c['keys'], a['keys'])]
                    if len(c['keys']) != len(a['keys']) or not all(vclose(x, y, tol) for x, y in ks):
                        r.should('%s#%d' % (p, i), 'expected %s, got %s; only the last of them is applied '
                                 '(MDL-CTRL-036)' % ([k.get('v') for k in c['keys']],
                                                     [k.get('v') for k in a['keys']]))
        pairs.append((es[-1], as_[-1] if as_ else None, p))
    for c, a, p in pairs:
        if a is None:
            if skipped_count(c) and not c['bezier']:
                r.should(p, 'dropped; its column count (%d) is one the engine skips (MDL-CTRL-014)' % c['columns'])
            elif is_default(flags, c['id'], c['keys'], tol):
                r.should(p, 'omitted; the golden has it with the default value')
            elif mdlview.controller_def(flags, c['id']) is None:
                r.should(p, 'missing; id %d has no ASCII keyword' % c['id'])
            else:
                r.must(p, 'missing (id %d, %d key(s))' % (c['id'], len(c['keys'])))
            continue
        if c['bezier'] != a.get('bezier'):
            r.must(p, 'expected %s keys, got %s' % ('bezier' if c['bezier'] else 'linear',
                                                     'bezier' if a.get('bezier') else 'linear'))
            # The first key's value is still compared: it is all a geometry
            # node shows (MDL-CTRL-023), and an allowance for the key kind
            # alone ("match") must not hide a wrong value.
            if c['keys'] and a['keys'] and 'v' in c['keys'][0]:
                ev, av = c['keys'][0]['v'], a['keys'][0].get('v')
                if not vclose(ev, av, tol):
                    r.must('%s.keys[0].v' % p, 'expected %s, got %s' % (ev, av))
            continue
        if c['columns'] != a.get('columns') and not c['bezier'] and len(c['keys']) == len(a['keys']):
            # The same runtime result once both are padded with the runtime
            # field's initial values (MDL-CTRL-014): a SHOULD, not a failure.
            # The components only one side holds must equal the initial value
            # exactly: anything else is a value the engine never reads.
            pe, pa = runtime_padded(flags, c, c['keys']), runtime_padded(flags, a, a['keys'])
            n = min(c['columns'], a.get('columns') or 0)
            if pe is not None and pa is not None and all(
                    close(te, ta, tol) and vclose(ve[:n], va[:n], tol) and ve[n:] == va[n:]
                    for (te, ve), (ta, va) in zip(pe, pa)):
                r.should(p, 'expected %d columns, got %s; the same values at runtime (MDL-CTRL-014)'
                         % (c['columns'], a.get('columns')))
                continue
        if profile == 'compile':
            if c['columns'] != a.get('columns'):
                r.must(p, 'expected %d columns, got %s' % (c['columns'], a.get('columns')))
            if 'colbyte' in c and c.get('colbyte') != a.get('colbyte'):
                r.should(p + '.colbyte', 'expected %#x, got %#x' % (c['colbyte'], a.get('colbyte', 0)))
        if len(c['keys']) != len(a['keys']):
            r.must(p, 'expected %d key(s), got %d' % (len(c['keys']), len(a['keys'])))
            continue
        quat = c['name'] == 'orientation' and not c['bezier'] and c['columns'] == 4
        for i, (ek, ak) in enumerate(zip(c['keys'], a['keys'])):
            if not close(ek['t'], ak['t'], tol):
                r.must('%s.keys[%d].t' % (p, i), 'expected %s, got %s' % (ek['t'], ak['t']))
            for part in ('v', 'in', 'out'):
                if part not in ek:
                    continue
                ok = (qclose if quat and part == 'v' else vclose)(ek[part], ak.get(part), tol)
                if not ok:
                    r.must('%s.keys[%d].%s' % (p, i, part), 'expected %s, got %s' % (ek[part], ak.get(part)))
    for cid, as_ in amap.items():
        a = as_[-1]
        pth = '%s.controllers[%s]' % (path, a['name'])
        if is_default(flags, cid, a['keys'], tol):
            r.should(pth, 'not in the golden (id %d), with the default value' % cid)
            continue
        level = 'must' if profile == 'compile' else 'should'
        first = a['keys'][0].get('v') if a['keys'] else None
        r.add(level, pth, 'not in the golden (id %d, %d key(s), first %s)' % (cid, len(a['keys']), first))


def is_default(flags, cid, keys, tol):
    """One key at t = 0 holding the controller's default (tables/controllers.yaml)."""
    cdef = mdlview.controller_def(flags, cid)
    dflt = cdef.get('default') if cdef else None
    if dflt is None or len(keys) != 1 or 'in' in keys[0] or not close(keys[0].get('t', 0), 0, tol):
        return False
    want = dflt if isinstance(dflt, list) else [dflt]
    got = list(keys[0].get('v') or [])
    if cdef['name'] != 'orientation' and len(got) < len(want):
        got += want[len(got):]  # the rest of the runtime field keeps its initial value (MDL-CTRL-014)
    return (qclose if cdef['name'] == 'orientation' else vclose)(want, got, tol)


def compare_skin(r, path, e, a, own_nodes):
    """Bone weights per drawn corner, by bone name (MDL-SKIN-010)."""
    es, as_ = e['skin'], a.get('skin') or {}
    if es.get('bone_map_count', 0) > own_nodes:
        r.should(path, 'bound to a skeleton (%d tree positions, %d own nodes): weights not compared'
                 % (es['bone_map_count'], own_nodes))
        return
    ew, aw = es.get('weights', []), as_.get('weights')
    if aw is None:
        r.must(path + '.weights', 'missing')
        return
    et, corners = drawn(e['mesh']), drawn(a['mesh'])
    out_of_tree = set(es.get('out_of_tree', []))
    bad, soft = [], []
    for ti, (ef, af) in enumerate(zip(et, corners)):
        for k in range(3):
            want = sorted((n.lower(), w) for n, w in (ew[ef[k]] if ef[k] < len(ew) else []))
            got = sorted((n.lower(), w) for n, w in (aw[af[k]] if af[k] < len(aw) else []))
            if [n for n, _ in want] != [n for n, _ in got] or \
                    not vclose([w for _, w in want], [w for _, w in got], 1e-4):
                msg = 'triangle %d corner %d: expected %s, got %s' % (ti, k, want, got)
                # A bone list entry past the tree: by the code the engine
                # skips that influence; not observed in game (spec/unknown.md).
                (soft if ef[k] in out_of_tree else bad).append(msg)
    if bad:
        r.must(path + '.weights', '%d corner(s) differ; first: %s' % (len(bad), bad[0]))
    if soft:
        r.should(path + '.weights', '%d corner(s) differ on a bone list entry past the tree; first: %s'
                 % (len(soft), soft[0]))


def dfs_order(nodes):
    return [(n['name'], n['parent']) for n in nodes]


def cut_names(names):
    """Each name as the game's compiler stores it (MDL-BIN-007: at most 31
    characters), lower-case; with the set of those that two names share."""
    cut = [n[:31].lower() for n in names]
    seen, shared = set(), set()
    for c in cut:
        (shared if c in seen else seen).add(c)
    return cut, shared


def compare_nodes(r, base, exp_nodes, act_nodes, profile, volatile, anim):
    ecut, eshared = cut_names([n['name'] for n in exp_nodes])
    long_names = {n['name'].lower() for n in exp_nodes if len(n['name']) == 32}

    def name_cut(en, an):
        """an is en cut to 31 characters, and no other node of the original
        has that name once cut (MDL-BIN-007)."""
        en, an = (en or '').lower(), (an or '').lower()
        return len(en) == 32 and an == en[:31] and an not in eshared

    if [node_key(n) for n in exp_nodes] != [node_key(n) for n in act_nodes]:
        en = [n['name'] for n in exp_nodes]
        an = [n['name'] for n in act_nodes]
        level = 'must' if profile == 'compile' or set(map(str.lower, en)) != set(map(str.lower, an)) else 'should'
        r.add(level, base + '.tree', 'node order differs: expected %s, got %s' % (en, an))
        if r.facts is not None and long_names and ecut == [node_key(n) for n in act_nodes]:
            # the same tree once the 32-character names are cut to 31
            r.facts[profile + ' ' + base + '.tree'] = {
                'names_cut_only': True, 'cut': sorted(long_names),
                'unique': not any(c[:31] in eshared for c in long_names)}
    # Match by name and occurrence: a name used twice (zspec_super) pairs
    # the first with the first and so on.
    def keyed(nodes):
        seen, out = {}, []
        for n in nodes:
            k = node_key(n)
            seen[k] = seen.get(k, 0) + 1
            out.append(((k, seen[k]), n))
        return out
    amap = dict(keyed(act_nodes))
    exp_keys = {node_key(n) for n in exp_nodes}
    for i, (ek, e) in enumerate(keyed(exp_nodes)):
        p = '%s[%s]' % (base, e['name']) if ek[1] == 1 else '%s[%s#%d]' % (base, e['name'], ek[1])
        a = amap.get(ek)
        cut = (ek[0][:31], ek[1])
        if a is None and len(ek[0]) == 32 and cut in amap and cut[0] not in exp_keys and cut[0] not in eshared:
            # A 32-character name the compile cut to 31 (MDL-BIN-007), paired
            # with that node when no other node of the original has the name.
            a = amap[cut]
            r.must(p + '.name', 'expected %r, got %r: cut to 31 characters' % (e['name'], a['name']))
            if r.facts is not None:
                r.facts[profile + ' ' + p + '.name'] = {'name_cut': [e['name'], a['name']], 'unique': True}
        if a is None:
            r.must(p, 'missing')
            continue
        ep, ap = (e.get('parent') or '').lower(), (a.get('parent') or '').lower()
        if ep != ap:
            r.must(p + '.parent', 'expected %s, got %s' % (e.get('parent'), a.get('parent')))
            if r.facts is not None and name_cut(ep, ap):
                r.facts[profile + ' ' + p + '.parent'] = {'name_cut': [e.get('parent'), a.get('parent')],
                                                          'unique': True}
        if e['flags'] != a['flags']:
            level = 'should' if anim else 'must'
            r.add(level, p + '.type', 'expected %s (%#x), got %s (%#x)' % (e['type'], e['flags'], a['type'], a['flags']))
        if profile == 'compile':
            if e['number'] != a.get('number'):
                r.must(p + '.number', 'expected %s, got %s' % (e['number'], a.get('number')))
            if not anim and e.get('inheritcolor') != a.get('inheritcolor'):
                r.must(p + '.inheritcolor', 'expected %s, got %s' % (e.get('inheritcolor'), a.get('inheritcolor')))
        compare_controllers(r, p, e['controllers'], a.get('controllers', []), profile, e['flags'])
        pre = '%s[%d].' % (base, i)
        vol = {p + '.' + v[len(pre):] for v in volatile if v.startswith(pre)}
        if 'light' in e and not anim:
            compare_section(r, p + '.light', e['light'], a.get('light'), LIGHT_DEFAULTS, profile, vol)
        if 'emitter' in e and not anim:
            compare_section(r, p + '.emitter', e['emitter'], a.get('emitter'), EMITTER_DEFAULTS, profile, vol)
        if 'reference' in e and not anim:
            compare_section(r, p + '.reference', e['reference'], a.get('reference'),
                            {'refmodel': '', 'reattachable': 0}, profile, vol)
        if 'dangly' in e:
            ed = dict(e['dangly'])
            ad = dict(a.get('dangly') or {})
            if profile == 'decompile' and 'mesh' in e and 'mesh' in a:
                # constraints are per vertex; an ASCII may number vertices
                # its own way, so compare them per drawn corner
                ec, ac = ed.pop('constraints', []), ad.pop('constraints', [])
                bad = []
                for ti, (x, y) in enumerate(zip(drawn(e['mesh']), drawn(a['mesh']))):
                    for k in range(3):
                        cx = ec[x[k]] if x[k] < len(ec) else None
                        cy = ac[y[k]] if y[k] < len(ac) else None
                        if not close(cx, cy, 1e-4):
                            bad.append('triangle %d corner %d: expected %s, got %s' % (ti, k, cx, cy))
                if bad:
                    r.must(p + '.dangly.constraints', '%d corner(s) differ; first: %s' % (len(bad), bad[0]))
            compare_section(r, p + '.dangly', ed, ad, {}, profile, vol, 1e-4)
        if 'animmesh' in e:
            ea = dict(e['animmesh'])
            aa = a.get('animmesh') or {}
            if profile == 'decompile':
                ea.pop('vertex_sets', None)
                ea.pop('texture_sets', None)
                if not anim:
                    ea = {k: v for k, v in ea.items() if v not in (0, [])}
            compare_section(r, p + '.animmesh', ea, aa, {}, profile, vol, 1e-4)
        if 'aabb' in e:
            ee = e['aabb']
            ae = a.get('aabb') or []
            if len(ee) != len(ae):
                r.must(p + '.aabb', 'expected %d tree entries, got %d' % (len(ee), len(ae)))
            else:
                for j, (x, y) in enumerate(zip(ee, ae)):
                    if not (vclose(x['min'], y['min'], 1e-4) and vclose(x['max'], y['max'], 1e-4) and x['face'] == y['face']):
                        r.must('%s.aabb[%d]' % (p, j), 'expected %s, got %s' % (x, y))
                        break
                    if profile == 'compile' and x.get('plane') != y.get('plane'):
                        r.must('%s.aabb[%d].plane' % (p, j), 'expected %s, got %s' % (x.get('plane'), y.get('plane')))
                        if r.facts is not None:
                            r.facts['compile ' + p + '.aabb'] = nodefacts.aabb_facts(ee, ae)
                        break
        if 'mesh' in e and not anim:
            if 'mesh' not in a:
                r.must(p + '.mesh', 'missing')
            else:
                before = len(r.items)
                compare_mesh(r, p + '.mesh', e['mesh'], a['mesh'], profile, vol, bool(e['flags'] & 0x200),
                             face_indices=r.facts is None)
                if r.facts is not None and profile == 'compile' and any(
                        lvl == 'must' for lvl, _, _ in r.items[before:]):
                    r.facts['compile ' + p + '.mesh'] = mesh_facts(e, a, len(exp_nodes))
                if 'skin' in e and profile == 'decompile':
                    compare_skin(r, p + '.skin', e, a, len(exp_nodes))


def compare(exp, act, profile, facts=False):
    r = Report(facts)
    volatile = set(exp.get('volatile', []))
    em, am = exp['model'], act['model']
    for k in ('name', 'classification', 'fog', 'animationscale', 'supermodel'):
        ev, av = em.get(k), am.get(k)
        if k == 'supermodel':
            ev = '' if (ev or '').upper() == 'NULL' else (ev or '').lower()
            av = '' if (av or '').upper() == 'NULL' else (av or '').lower()
        if k == 'name':
            ev, av = (ev or '').lower(), (av or '').lower()
        if not vclose(ev, av, 1e-5):
            r.must('model.' + k, 'expected %r, got %r' % (em.get(k), am.get(k)))
    if profile == 'compile':
        if em.get('node_count') != am.get('node_count'):
            r.must('model.node_count', 'expected %s, got %s' % (em.get('node_count'), am.get('node_count')))
        for k in ('bmin', 'bmax', 'radius'):
            if not vclose(em.get(k), am.get(k), 1e-4):
                r.should('model.' + k, 'expected %s, got %s' % (em.get(k), am.get(k)))
    compare_nodes(r, 'nodes', exp['nodes'], act['nodes'], profile, volatile, False)
    amap = {a['name'].lower(): a for a in act.get('animations', [])}
    if [a['name'].lower() for a in exp['animations']] != [a['name'].lower() for a in act.get('animations', [])]:
        r.should('animations', 'order or set differs: expected %s, got %s'
                 % ([a['name'] for a in exp['animations']], [a['name'] for a in act.get('animations', [])]))
    for ea in exp['animations']:
        p = 'animations[%s]' % ea['name']
        aa = amap.get(ea['name'].lower())
        if aa is None:
            r.must(p, 'missing')
            continue
        for k in ('length', 'transtime'):
            if not close(ea[k], aa.get(k), 1e-5):
                r.must('%s.%s' % (p, k), 'expected %s, got %s' % (ea[k], aa.get(k)))
        if (ea['animroot'] or '').lower() != (aa.get('animroot') or '').lower():
            r.must(p + '.animroot', 'expected %r, got %r' % (ea['animroot'], aa.get('animroot')))
        ev = [[e[0], e[1].lower()] for e in ea['events']]
        av = [[e[0], e[1].lower()] for e in aa.get('events', [])]
        if not vclose([x[0] for x in ev], [x[0] for x in av], 1e-5) or [x[1] for x in ev] != [x[1] for x in av]:
            r.must(p + '.events', 'expected %s, got %s' % (ea['events'], aa.get('events')))
        if profile == 'compile' and ea.get('node_count') != aa.get('node_count'):
            r.must(p + '.node_count', 'expected %s, got %s' % (ea.get('node_count'), aa.get('node_count')))
        compare_nodes(r, p + '.nodes', ea['nodes'], aa.get('nodes', []), profile, set(), True)
    return r


# ------------------------------------------------------------ commands

def cmd_expect(a):
    goldens = os.path.join(CONF, 'goldens')
    outdir = os.path.join(CONF, 'expected')
    os.makedirs(outdir, exist_ok=True)
    for p in load_manifest():
        g = os.path.join(goldens, p['name'] + '.mdl')
        if not os.path.exists(g):
            continue
        data = open(g, 'rb').read()
        exp = normalise(mdlview.read_binary(data))
        volatile = set()
        if a.second:
            g2 = os.path.join(a.second, p['name'] + '.mdl')
            if os.path.exists(g2):
                exp2 = normalise(mdlview.read_binary(open(g2, 'rb').read()))
                f1, f2 = dict(flat(exp)), dict(flat(exp2))
                volatile = {k for k in f1 if f1[k] != f2.get(k)}
        doc = {'format': 'mdl-expected/1', 'probe': p['name'], 'build': BUILD,
               'golden_sha256': hashlib.sha256(data).hexdigest(),
               'volatile': sorted(volatile)}
        doc.update(exp)
        with open(os.path.join(outdir, p['name'] + '.json'), 'w') as f:
            json.dump(doc, f, indent=1, sort_keys=False)
            f.write('\n')
        print('%-18s %d volatile field(s)' % (p['name'], len(volatile)))


# roundtrip caps the memory of its own worker processes (--max-memory) so one
# model the reader cannot cope with fails alone instead of exhausting the
# machine. The cap is the soft address-space limit, which a child can raise
# again: the implementation under test runs without it.
_MEMORY_CAPPED = False


def _uncap_memory():
    import resource
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (hard, hard))


def _cap_memory(gb):
    global _MEMORY_CAPPED
    try:
        import resource
    except ImportError:  # not POSIX: no cap
        return
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    limit = int(gb * (1 << 30))
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    _MEMORY_CAPPED = True


def run_impl(cmd, verb, src, dst, cwd, env=None):
    argv = shlex.split(cmd) + [verb, src, dst]
    if os.path.exists(argv[0]):  # a relative path: the command runs elsewhere
        argv[0] = os.path.abspath(argv[0])
    try:
        r = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, env=env,
                           preexec_fn=_uncap_memory if _MEMORY_CAPPED else None)
        return r.returncode, r.stdout.decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        return -1, 'timeout'
    except OSError as e:
        return -1, str(e)


def compile_check(cmd, probe, ascii_data, tmp):
    """The implementation's compile of a decompile's ASCII, as a view (None
    when it fails), with the probe's companion files beside it."""
    d = os.path.join(tmp, 'check')
    os.makedirs(d, exist_ok=True)
    name = probe['name'] + '.mdl'
    with open(os.path.join(d, name), 'wb') as f:
        f.write(ascii_data)
    for fn in probe.get('with', []):
        if not fn.endswith('.mdl'):
            shutil.copyfile(os.path.join(CONF, 'probes', fn), os.path.join(d, fn))
        elif os.path.exists(os.path.join(CONF, 'goldens', fn)):
            shutil.copyfile(os.path.join(CONF, 'goldens', fn), os.path.join(d, fn))
    out = os.path.join(tmp, 'check-out', name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rc, _ = run_impl(cmd, 'compile', os.path.join(d, name), out, tmp)
    try:
        return mdlview.read_binary(open(out, 'rb').read()) if rc == 0 else None
    except Exception:  # noqa: BLE001 - no compile, nothing accepted
        return None


def cmd_run(a):
    results = []
    probes = [p for p in load_manifest() if not a.only or p['name'] in a.only]
    for p in probes:
        name = p['name']
        expf = os.path.join(CONF, 'expected', name + '.json')
        if not os.path.exists(expf):
            results.append({'probe': name, 'test': 'all', 'status': 'pending', 'reason': p.get('pending', 'no golden')})
            continue
        exp = json.load(open(expf))
        for test in ('compile', 'decompile'):
            if a.test and test not in a.test:
                continue
            tmp = tempfile.mkdtemp(prefix='mdlconf-')
            try:
                if test == 'compile':
                    for fn in [name + '.mdl'] + p.get('with', []):
                        shutil.copyfile(os.path.join(CONF, 'probes', fn), os.path.join(tmp, fn))
                    src = os.path.join(tmp, name + '.mdl')
                else:
                    os.makedirs(os.path.join(tmp, 'in'))
                    src = os.path.join(tmp, 'in', name + '.mdl')
                    shutil.copyfile(os.path.join(CONF, 'goldens', name + '.mdl'), src)
                    for fn in p.get('with', []):
                        if fn.endswith('.mdl') and os.path.exists(os.path.join(CONF, 'goldens', fn)):
                            shutil.copyfile(os.path.join(CONF, 'goldens', fn), os.path.join(tmp, 'in', fn))
                os.makedirs(os.path.join(tmp, 'out'))
                dst = os.path.join(tmp, 'out', name + '.mdl')
                rc, log = run_impl(a.cmd, test, src, dst, tmp)
                res = {'probe': name, 'test': test}
                if rc != 0 or not os.path.exists(dst):
                    res.update(status='error', reason='exit %s: %s' % (rc, log.strip()[-600:]))
                    results.append(res)
                    continue
                data = open(dst, 'rb').read()
                try:
                    if test == 'compile':
                        if data[:4] != b'\0\0\0\0':
                            raise ValueError('output is not a binary model')
                        act = mdlview.read_binary(data)
                    else:
                        if data[:4] == b'\0\0\0\0':
                            raise ValueError('output is not an ASCII model')
                        act = mdlview.read_ascii(data.decode('latin-1'))
                except Exception as e:  # noqa: BLE001 - report any decoding failure
                    res.update(status='error', reason='cannot read the output: %s' % e)
                    results.append(res)
                    continue
                rep = compare(exp, act, test)
                accepted = []
                if test == 'decompile' and left_out_tangents(rep):
                    accepted = accept_left_out_tangents(rep, exp, compile_check(a.cmd, p, data, tmp))
                # The manifest may relax checks: "lenient" (a list of tests)
                # makes every check of that test a SHOULD (malformed input);
                # "allow" entries make the checks under a path a SHOULD where
                # the spec lets an implementation differ from the engine; with
                # "match", only the checks whose message contains it.
                items = []
                for lvl, pth, msg in rep.items:
                    if lvl == 'must' and test in p.get('lenient', []):
                        lvl, msg = 'should', msg + ' [lenient: malformed input]'
                    for al in p.get('allow', []):
                        if (lvl == 'must' and pth.startswith(al['path']) and test in al.get('tests', ['compile', 'decompile'])
                                and al.get('match', '') in msg):
                            lvl, msg = 'should', '%s [allowed: %s]' % (msg, al['rule'])
                    items.append((lvl, pth, msg))
                rep.items = items
                res['status'] = 'fail' if rep.failed else 'pass'
                res['must'] = [[pth, msg] for l, pth, msg in rep.items if l == 'must']
                res['should'] = [[pth, msg] for l, pth, msg in rep.items if l == 'should']
                if accepted:
                    res['accepted'] = accepted
                if log.strip():
                    res['log'] = log.strip()[-2000:]
                results.append(res)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return report(a, results)


def report(a, results):
    counts = {}
    for r in results:
        counts[(r['test'], r['status'])] = counts.get((r['test'], r['status']), 0) + 1
    print('# %s' % a.impl)
    for r in results:
        line = '%-18s %-9s %s' % (r['probe'], r['test'], r['status'].upper())
        if r['status'] == 'pass' and r.get('should'):
            line += ' (%d should)' % len(r['should'])
        if r.get('accepted'):
            line += ' (%d accepted)' % len(r['accepted'])
        print(line)
        if r['status'] in ('error', 'pending'):
            print('    ' + r['reason'].replace('\n', '\n    '))
        for pth, msg in r.get('must', [])[:a.max]:
            print('    MUST   %s: %s' % (pth, msg))
        if a.verbose:
            for pth, msg in r.get('should', [])[:a.max]:
                print('    SHOULD %s: %s' % (pth, msg))
            for pth, msg in r.get('accepted', [])[:a.max]:
                print('    OK     %s: %s' % (pth, msg))
    print('# totals: ' + ', '.join('%s %s %d' % (t, s, n) for (t, s), n in sorted(counts.items())))
    if a.json:
        with open(a.json, 'w') as f:
            json.dump({'impl': a.impl, 'build': BUILD, 'results': results}, f, indent=1)
    return 0


def cmd_stock(a):
    import miniyaml
    import resfiles
    root = a.root or resfiles.default_root()
    if not root:
        sys.exit('NWN install not found: give --root or set NWN_ROOT')
    key = resfiles.KeyArchive(root)
    models = miniyaml.load(os.path.join(CONF, 'stock.yaml'))['models']
    results = []
    for m in models:
        name = m['resref']
        if a.only and name not in a.only:
            continue
        data = key.get(name)
        res = {'probe': name, 'test': 'decompile'}
        if data is None:
            res.update(status='pending', reason='not in this install')
            results.append(res)
            continue
        exp = normalise(mdlview.read_binary(data))
        tmp = tempfile.mkdtemp(prefix='mdlconf-')
        try:
            os.makedirs(os.path.join(tmp, 'in'))
            os.makedirs(os.path.join(tmp, 'out'))
            src = os.path.join(tmp, 'in', name + '.mdl')
            dst = os.path.join(tmp, 'out', name + '.mdl')
            with open(src, 'wb') as f:
                f.write(data)
            rc, log = run_impl(a.cmd, 'decompile', src, dst, tmp)
            if rc != 0 or not os.path.exists(dst):
                res.update(status='error', reason='exit %s: %s' % (rc, log.strip()[-600:]))
            else:
                out = open(dst, 'rb').read()
                if out[:4] == b'\0\0\0\0':
                    res.update(status='error', reason='output is not an ASCII model')
                else:
                    rep = compare(exp, mdlview.read_ascii(out.decode('latin-1')), 'decompile')
                    res['status'] = 'fail' if rep.failed else 'pass'
                    res['must'] = [[pth, msg] for l, pth, msg in rep.items if l == 'must']
                    res['should'] = [[pth, msg] for l, pth, msg in rep.items if l == 'should']
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        results.append(res)
    return report(a, results)


def find_binaries(paths):
    """The binary models under paths (files or folders, recursively), sorted,
    and how many ASCII models were passed over."""
    out, ascii_count = [], 0
    for p in paths:
        files = [p]
        if os.path.isdir(p):
            files = sorted(os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs if f.lower().endswith('.mdl'))
        for f in files:
            with open(f, 'rb') as fh:
                if fh.read(4) == b'\0\0\0\0':
                    out.append(f)
                else:
                    ascii_count += 1
    return sorted(set(out)), ascii_count


class ModelTimeout(BaseException):
    """Not an Exception, so that no handler for a bad file catches it."""


def _on_alarm(signum, frame):
    raise ModelTimeout()


def roundtrip_one(job):
    """Round-trip one binary model: decompile, compile, and once more. With a
    time limit (job[3], seconds), a model that takes longer is an error."""
    limit = job[3] if len(job) > 3 else 0
    alarm = limit and hasattr(signal, 'SIGALRM')
    if alarm:
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(int(limit))
    try:
        return _roundtrip_one(job)
    except MemoryError:
        return {'file': job[1], 'must': [], 'should': [], 'status': 'error',
                'reason': 'the runner ran out of memory reading or comparing this model (--max-memory)'}
    except ModelTimeout:
        return {'file': job[1], 'must': [], 'should': [], 'status': 'error',
                'reason': 'timeout: the model took longer than %d s (--model-timeout)' % limit}
    finally:
        if alarm:
            signal.alarm(0)


def _roundtrip_one(job):
    cmd, path, resource_dirs = job[:3]
    res = {'file': path, 'must': [], 'should': []}
    name = os.path.basename(path)
    env = dict(os.environ)
    env['MDLCONF_RESOURCE_DIRS'] = os.pathsep.join([os.path.dirname(os.path.abspath(path))] + resource_dirs)
    tmp = tempfile.mkdtemp(prefix='mdlconf-rt-')
    try:
        orig = open(path, 'rb').read()
        try:
            exp = normalise(mdlview.read_binary(orig))
        except Exception as e:  # noqa: BLE001 - an unreadable original is reported, not fatal
            res.update(status='error', reason='cannot read the original: %s' % e)
            return res
        steps = {}
        for step, verb, src in (('ascii', 'decompile', path), ('binary', 'compile', 'ascii'),
                                ('ascii2', 'decompile', 'binary'), ('binary2', 'compile', 'ascii2')):
            os.makedirs(os.path.join(tmp, step))
            dst = os.path.join(tmp, step, name)
            rc, log = run_impl(cmd, verb, steps.get(src, src), dst, tmp, env)
            if rc != 0 or not os.path.exists(dst):
                res.update(status='error', reason='%s (%s step): exit %s: %s' % (verb, step, rc, log.strip()[-600:]))
                return res
            steps[step] = dst
        data = {k: open(v, 'rb').read() for k, v in steps.items()}
        try:
            first = mdlview.BinaryParts(data['binary'])
            acts = [('decompile', mdlview.read_ascii(data['ascii'].decode('latin-1'))),
                    ('compile', first.view)]
        except Exception as e:  # noqa: BLE001
            res.update(status='error', reason='cannot read the output: %s' % e)
            return res
        facts = {}
        for test, act in acts:
            rep = compare(exp, act, test, facts=True)
            if test == 'decompile' and left_out_tangents(rep):
                # tangents the ASCII leaves out, which its compile makes again
                for pth, msg in accept_left_out_tangents(rep, exp, acts[1][1]):
                    res.setdefault('accepted', []).append([test, pth, msg])
            for lvl, pth, msg in rep.items:
                res[lvl].append([test, pth, msg])
            facts.update(rep.facts)
        if any(MERGE_FINDING.search(p) for _, p, _ in res['must']) and any(
                'mesh' in n and merged_list(n['mesh']) for n in exp['nodes']):
            try:
                moving = supermodel_animated(exp['model'].get('supermodel'),
                                             env['MDLCONF_RESOURCE_DIRS'].split(os.pathsep))
                rf = render_list_facts(exp, acts[1][1], moving or frozenset())
                if moving is None:
                    rf['supermodel_missing'] = True
                facts['compile model.render_lists'] = rf
            except Exception as e:  # noqa: BLE001 - no facts, nothing approved
                facts['compile model.render_lists'] = {'error': repr(e)}
        if any(t == 'compile' and NODE_FINDING.search(p) for t, p, _ in res['must']):
            try:
                sup = find_supermodel(exp['model'].get('supermodel'), env['MDLCONF_RESOURCE_DIRS'].split(os.pathsep))
                facts['compile model.nodes'] = nodefacts.model_facts(exp, acts[1][1], data['ascii'].decode('latin-1'), sup)
            except Exception as e:  # noqa: BLE001 - no facts, nothing approved
                facts['compile model.nodes'] = {'error': repr(e)}
        if facts:
            res['facts'] = facts
        # Checked whatever the findings, so that approvals (approvals.py) can
        # tell a model whose findings are all approved from an unstable one.
        res['stable'] = data['binary2'] == data['binary']
        if not res['stable']:
            # one read of the second compile for all three (the views are
            # changed by explain_unstable, so it comes last)
            try:
                second = mdlview.BinaryParts(data['binary2'])
            except Exception:  # noqa: BLE001 - unreadable: unexplained
                second = None
            res['unstable_fields'] = unstable_fields(acts[1][1], data['binary2'], second)
            res['unstable_adjacency_only'] = adjacency_only(data['binary'], data['binary2'], first, second)
            try:
                why = explain_unstable(data['binary'], data['binary2'], exp, first, second) if second else None
            except Exception:  # noqa: BLE001 - unexplained
                why = None
            if why:
                res['unstable_explained'] = why
        if res['must']:
            res['status'] = 'fail'
        elif not res['stable']:
            res['status'] = 'unstable'
            res['reason'] = 'decompiling and compiling the compiled model again gives different bytes'
        else:
            res['status'] = 'pass'
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def adjacency_only(first, second, p1=None, p2=None):
    """How many face records differ between two compiles that are byte
    for byte the same apart from the faces' adjacency fields (MDL-BIN-044,
    MDL-MESH-022), in face records found at the same offsets in both; 0 when
    anything else differs (or the files are the same, or cannot be read).
    p1, p2: the files' mdlview.BinaryParts, when already read."""
    if first == second or len(first) != len(second):
        return 0
    try:
        p1 = p1 or mdlview.BinaryParts(first)
        p2 = p2 or mdlview.BinaryParts(second)
        x, xo = p1.adjacency_masked(), p1.face_records
        y, yo = p2.adjacency_masked(), p2.face_records
    except Exception:  # noqa: BLE001 - unreadable: not shown to differ only there
        return 0
    if xo != yo or x != y:
        return 0
    return sum(1 for o in xo if first[o + 20:o + 26] != second[o + 20:o + 26])


NODE_FINDING = re.compile(r'(\.number|\.tree|node_count)$')
MERGE_FINDING = re.compile(r'\.mesh\.(render|triangles|vertex_count)$')
_SUPERS = {}


def find_supermodel(name, dirs, depth=0):
    """The supermodel an implementation compiles against, as a
    nodefacts.Super: the first <name>.mdl in the folders (the original's own
    first), else the base game's (NWN_ROOT); an ASCII one numbered by the
    rules against its own supermodel. None when there is none or it (or a
    supermodel it names) is not found."""
    name = (name or '').strip().lower()
    if not name or name == 'null' or depth > 8:
        return None
    key = (name, tuple(dirs))
    if key in _SUPERS:
        return _SUPERS[key]
    data = _supermodel_data(name, dirs)
    sup = None
    if data and data[:4] == b'\0\0\0\0':
        sup = nodefacts.Super.from_binary(mdlview.read_binary(data))
    elif data:
        text = data.decode('latin-1')
        parent = nodefacts.ascii_supermodel(text)
        psup = find_supermodel(parent, dirs, depth + 1) if parent else None
        if not parent or psup is not None:
            sup = nodefacts.Super.from_ascii(text, psup)
    _SUPERS[key] = sup
    return sup


def _supermodel_data(name, dirs):
    """The bytes of the first <name>.mdl in the folders, else the base
    game's (NWN_ROOT); None when not found."""
    data = None
    for d in dirs:
        for fn in (name + '.mdl', name.upper() + '.mdl'):
            p = os.path.join(d, fn)
            if data is None and os.path.isfile(p):
                data = open(p, 'rb').read()
    if data is None:
        try:
            import resfiles
            root = resfiles.default_root()
            if root:
                if 'archive' not in _SUPERS:
                    _SUPERS['archive'] = resfiles.KeyArchive(root)
                data = _SUPERS['archive'].get(name)
        except Exception:  # noqa: BLE001 - not found
            data = None
    return data


M_BOUNDS = range(12 + 136, 12 + 160, 4)  # the model's bounding box (bmin, bmax), file offsets


def _ulps(a, b):
    """The distance in units in the last place between two float32 (bytes)."""
    def ordered(x):
        u = struct.unpack('<I', x)[0]
        return -(u & 0x7fffffff) if u & 0x80000000 else u
    fa, fb = struct.unpack('<f', a)[0], struct.unpack('<f', b)[0]
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return None
    return abs(ordered(a) - ordered(b))


def explain_bytes(first, second, p1=None, p2=None):
    """{kind: count} when two compiles of the same length differ only in
    (a) the adjacency fields of face records at the same offsets in both
    (MDL-BIN-044), (b) float fields (as the reader reads them) that are 0.0
    in one and -0.0 in the other, and (c) the model bounding box's floats by
    at most 1 ulp each; None when anything else differs."""
    if first == second or len(first) != len(second):
        return None
    p1 = p1 or mdlview.BinaryParts(first)
    p2 = p2 or mdlview.BinaryParts(second)
    x, xo = p1.adjacency_masked(), p1.face_records
    y, yo = p2.adjacency_masked(), p2.face_records
    if xo != yo:
        return None
    diff = [i for i, (u, v) in enumerate(zip(x, y)) if u != v]
    floats = p1.floats & p2.floats if diff else set()
    words = set()
    for i in diff:
        w = next((i - k for k in range(4) if i - k in floats), None)
        if w is None:
            return None
        words.add(w)
    out = {}
    adj = sum(1 for o in xo if first[o + 20:o + 26] != second[o + 20:o + 26])
    if adj:
        out['adjacency'] = adj
    zero = {bytes(4), b'\0\0\0\x80'}
    for w in words:
        a, b = first[w:w + 4], second[w:w + 4]
        if a in zero and b in zero:
            out['signed_zero'] = out.get('signed_zero', 0) + 1
        elif w in M_BOUNDS and _ulps(a, b) is not None and _ulps(a, b) <= 1:
            out['bounds_ulp'] = out.get('bounds_ulp', 0) + 1
        else:
            return None
    return out


def _dead_vertices(mesh):
    """The vertices no face record and no index list uses."""
    used = set()
    for f in mesh.get('faces', []):
        used.update(f['v'])
    for il in mesh.get('index_lists') or []:
        used.update(il)
    return [i for i in range(mesh.get('vertex_count', 0)) if i not in used]


def _without_vertices(node, dead):
    """A copy of a mesh node without the vertices `dead`, the others
    renumbered in order: streams, face records, index lists, skin weights,
    dangly constraints and animmesh sets."""
    import copy
    node = copy.deepcopy(node)
    m = node['mesh']
    nv = m.get('vertex_count', 0)
    gone = set(dead)
    keep = [i for i in range(nv) if i not in gone]
    remap = {o: n for n, o in enumerate(keep)}
    m['vertices'] = {k: ([vals[i] for i in keep] if isinstance(vals, list) and len(vals) == nv else vals)
                     for k, vals in m.get('vertices', {}).items()}
    m['vertex_count'] = len(keep)
    for f in m.get('faces', []):
        f['v'] = [remap.get(i, -1) for i in f['v']]
    m['index_lists'] = [[remap.get(i, -1) for i in il] for il in m.get('index_lists') or []]
    sk = node.get('skin')
    if sk and len(sk.get('weights', [])) == nv:
        sk['weights'] = [sk['weights'][i] for i in keep]
        if 'out_of_tree' in sk:
            sk['out_of_tree'] = [remap[i] for i in sk['out_of_tree'] if i in remap]
    dg = node.get('dangly')
    if dg and len(dg.get('constraints', [])) == nv:
        dg['constraints'] = [dg['constraints'][i] for i in keep]
    am = node.get('animmesh')
    if am:
        for k, sets in (('animverts', am.get('vertex_sets', 0)), ('animtverts', am.get('texture_sets', 0))):
            if k in am and nv and len(am[k]) == sets * nv:
                am[k] = [am[k][s * nv + i] for s in range(sets) for i in keep]
    return node


def _exact(view):
    """A view flattened, floats by their exact text (so -0.0 is not 0.0)."""
    return {k: (repr(v) if isinstance(v, float) else v) for k, v in flat(view)}


def explain_dead_vertices(first, second, exp, v1=None, v2=None):
    """{'dead_vertices': n[, 'adjacency': faces]} when the second compile is
    the first without the vertices no face of the first uses, each of them at
    the position of a corner of a zero-area triangle the original draws (the
    compile dropped that face, MDL-MESH-020, and kept its vertices), with the
    other vertices renumbered in order; the meshes' bounding box, average and
    radius may differ there (computed from the vertices, MDL-MESH-050), and
    their box must be that of their own vertices; face adjacency may differ
    (counted). None when anything else differs."""
    return dead_vertices_explained(v1 or mdlview.read_binary(first), v2 or mdlview.read_binary(second), exp)


def dead_vertices_explained(v1, v2, exp):
    """explain_dead_vertices on the two compiles' views (changed in place)."""
    n1, n2 = v1['nodes'], v2['nodes']
    if [n['name'] for n in n1] != [n['name'] for n in n2]:
        return None
    orig = {n['name'].lower(): n for n in exp['nodes']}
    dead_total = adj = 0
    for i, (a, b) in enumerate(zip(n1, n2)):
        if 'mesh' not in a or 'mesh' not in b:
            continue
        dead = _dead_vertices(a['mesh'])
        if _dead_vertices(b['mesh']):
            return None
        if not dead:
            continue
        o = orig.get(a['name'].lower())
        if o is None or 'mesh' not in o:
            return None
        opos = o['mesh'].get('vertices', {}).get('position', [])
        corners = set()
        for tri in drawn(o['mesh']):
            if tri_area2(opos, tri) == 0:
                corners.update(_freeze(opos[k]) for k in tri)
        pos1 = a['mesh']['vertices'].get('position', [])
        if not all(_freeze(pos1[k]) in corners for k in dead):
            return None
        a = _without_vertices(a, dead)
        for m, src in ((a['mesh'], pos1), (b['mesh'], b['mesh']['vertices'].get('position', []))):
            if not src or [min(fval(p[k]) for p in src) for k in range(3)] != [fval(x) for x in m.get('bmin') or []] or \
                    [max(fval(p[k]) for p in src) for k in range(3)] != [fval(x) for x in m.get('bmax') or []]:
                return None
            for k in ('bmin', 'bmax', 'average', 'radius'):
                m.pop(k, None)
        dead_total += len(dead)
        n1[i], n2[i] = a, b
    if not dead_total:
        return None
    for a, b in zip(n1, n2):
        for x, y in zip(a.get('mesh', {}).get('faces', []), b.get('mesh', {}).get('faces', [])):
            if x['adjacent'] != y['adjacent']:
                adj += 1
                x['adjacent'] = y['adjacent']
    if _exact(v1) != _exact(v2):
        return None
    out = {'dead_vertices': dead_total}
    if adj:
        out['adjacency'] = adj
    return out


def explain_unstable(first, second, exp, p1=None, p2=None):
    """Why the second compile differs from the first, as {kind: count}, when
    every difference is of a known kind (explain_bytes, or
    explain_dead_vertices); None otherwise. p1, p2: the files'
    mdlview.BinaryParts, when already read (their views are changed)."""
    p1 = p1 or mdlview.BinaryParts(first)
    p2 = p2 or mdlview.BinaryParts(second)
    return explain_bytes(first, second, p1, p2) or explain_dead_vertices(first, second, exp, p1.view, p2.view)


def unstable_fields(first, second_data, second=None):
    """What differs between the first compile (its view) and the second
    (bytes, or its mdlview.BinaryParts): {path with indices taken out:
    count}, the ten most common."""
    try:
        x = dict(flat(first))
        y = dict(flat(second.view if second is not None else mdlview.read_binary(second_data)))
    except Exception as e:  # noqa: BLE001
        return {'cannot read the second compile: %s' % e: 1}
    counts = {}
    for k in set(x) | set(y):
        if x.get(k) != y.get(k):
            k = re.sub(r'\[\d+\]', '[]', k)
            counts[k] = counts.get(k, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10])


def cause_of(test, pth, msg):
    """A failure's cause, for grouping: the path with node names and indices
    taken out, the message with its numbers and lists taken out."""
    pth = re.sub(r'\[[^\]]*\]', '[*]', pth)
    msg = re.sub(r'\[.*\]', '[...]', msg)
    msg = re.sub(r'-?\d+(\.\d+)?(e-?\d+)?', 'N', msg)
    msg = re.sub(r"'[^']*'", "'...'", msg)
    return '%s %s: %s' % (test, pth, msg[:120])


ROUNDTRIP_BATCH = 256


def cmd_roundtrip(a):
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
    from concurrent.futures.process import BrokenProcessPool
    approved = approvals.load(a.approved) if a.approved else None  # a bad file fails before the run
    files, ascii_count = find_binaries(a.paths)
    if not files:
        print('no binary models under %s (%d ASCII passed over)' % (', '.join(a.paths), ascii_count))
        return 1
    rdirs = [os.path.abspath(d) for d in (a.resource_dir or [])]
    # --partial: each result is appended as a JSON line as it finishes, and
    # models already there are not run again, so a stopped run resumes.
    done = {}
    if a.partial and os.path.exists(a.partial):
        with open(a.partial) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue  # a line cut short when the run was stopped
                done[r['file']] = r
    partial = open(a.partial, 'a') if a.partial else None
    jobs = [(a.cmd, f, rdirs, a.model_timeout) for f in files if f not in done]
    if done:
        print('roundtrip: %d of %d models already in %s' % (len(files) - len(jobs), len(files), a.partial),
              file=sys.stderr, flush=True)
    stall = (a.model_timeout or 4 * 120) + 300

    def keep(r):
        done[r['file']] = r
        if partial:
            partial.write(json.dumps(r) + '\n')
            partial.flush()

    # In batches, each with its own pool: a worker that dies (killed from
    # outside, or crashing) costs its batch, reported as errors, not the run.
    # A pool where no model finishes for longer than a model may take (each
    # call of the implementation is limited to 120 s) is stopped the same way.
    for i in range(0, len(jobs), ROUNDTRIP_BATCH):
        batch = jobs[i:i + ROUNDTRIP_BATCH]
        ex = ProcessPoolExecutor(max_workers=a.workers or None, initializer=_cap_memory, initargs=(a.max_memory,))
        futs = {ex.submit(roundtrip_one, j): j for j in batch}
        why = None
        pending = set(futs)
        while pending:
            finished, pending = wait(pending, timeout=stall, return_when=FIRST_COMPLETED)
            if not finished:
                why = 'no model finished for %d s in this batch of %d models (stalled worker)' % (stall, len(batch))
                break
            for fut in finished:
                try:
                    keep(fut.result())
                except BrokenProcessPool:
                    why = 'a worker process died in this batch of %d models' % len(batch)
                except Exception as e:  # noqa: BLE001
                    keep({'file': futs[fut][1], 'must': [], 'should': [], 'status': 'error',
                          'reason': 'the runner failed on this model: %r' % e})
            if why:
                break
        if why:
            for p in list(getattr(ex, '_processes', {}).values()):
                p.kill()
            for fut in pending:
                fut.cancel()
            for fut in futs:
                if futs[fut][1] not in done:
                    keep({'file': futs[fut][1], 'must': [], 'should': [], 'status': 'error', 'reason': why})
        ex.shutdown(wait=not why)
        print('roundtrip: %d of %d models done' % (len(done), len(files)), file=sys.stderr, flush=True)
    if partial:
        partial.close()
    results = [done[f] for f in files]

    if approved is not None:
        for r in results:
            approvals.apply(r, approved)
    return roundtrip_report(a, a.impl, results, len(files), ascii_count, approved)


def group_causes(results, statuses, key):
    causes = {}
    for r in results:
        keys = {cause_of(*m[:3]) for m in r.get(key, [])} if r['status'] in statuses else set()
        if key == 'must' and r['status'] in ('error', 'unstable'):
            keys = {'%s: %s' % (r['status'], re.sub(r'\d+', 'N', r['reason'].split(':')[0]))}
        for k in keys:
            c = causes.setdefault(k, {'cause': k, 'count': 0, 'example': r['file']})
            c['count'] += 1
    return sorted(causes.values(), key=lambda c: (-c['count'], c['cause']))


def roundtrip_report(a, impl, results, nfiles, ascii_count, approved=None):
    """Print the round trip's summary (and write --json); the exit status."""
    counts = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    ordered = group_causes(results, ('fail', 'error', 'unstable'), 'must')

    print('# %s: round trip of %d binary models (%d ASCII passed over)' % (impl, nfiles, ascii_count))
    for r in results:
        if r['status'] in ('pass', 'pass-approved') and not (a.verbose and (r['should'] or r.get('approved'))):
            continue
        print('%s %s' % (r['status'].upper(), r['file']))
        if r.get('reason'):
            print('    ' + r['reason'].replace('\n', '\n    '))
        for test, pth, msg in r['must'][:a.max]:
            print('    MUST   %s %s: %s' % (test, pth, msg))
        if a.verbose:
            for test, pth, msg, aid in r.get('approved', [])[:a.max]:
                print('    APPROVED (%s) %s %s: %s' % (aid, test, pth, msg))
            for test, pth, msg in r['should'][:a.max]:
                print('    SHOULD %s %s: %s' % (test, pth, msg))
    if ordered:
        print('# causes (models affected, example):')
        for c in ordered:
            print('%6d  %s\n        e.g. %s' % (c['count'], c['cause'], c['example']))
    doc_approvals = None
    if approved is not None:
        per = approvals.summary(results, approved)
        acauses = {}
        for aid in per:
            acauses[aid] = group_causes([dict(r, approved=[x for x in r.get('approved', []) if x[3] == aid])
                                         for r in results], ('pass-approved', 'fail', 'unstable'), 'approved')
        print('# approved differences (%s): models, findings, causes' % approved['file'])
        for e in approved['entries'].values():
            c = per[e['id']]
            print('%6d %7d  %s (%s)' % (c['models'], c['findings'], e['id'], ', '.join(e['rules'])))
            for x in acauses[e['id']][:a.max]:
                print('        %6d  %s' % (x['count'], x['cause']))
        doc_approvals = {'file': approved['file'], 'name': approved['name'], 'sha256': approved['sha256'],
                         'counts': per, 'causes': acauses}
        doc_approvals['stability_approved'] = sum(1 for r in results if approvals.stability_approved(r))
    print('# totals: ' + ', '.join('%s %d' % (s, n) for s, n in sorted(counts.items())))
    if doc_approvals is not None:
        print('# stability-approved %d (of the pass-approved: the second compile differs from the first only '
              'in ways an entry approves; per entry above, under "stability binary2")'
              % doc_approvals['stability_approved'])
    if a.json:
        doc = {'impl': impl, 'build': BUILD, 'ascii_passed_over': ascii_count,
               'totals': counts, 'causes': ordered, 'results': results}
        if doc_approvals is not None:
            doc['approvals'] = doc_approvals
        with open(a.json, 'w') as f:
            json.dump(doc, f, indent=1)
    passed = counts.get('pass', 0) + counts.get('pass-approved', 0)
    return 0 if passed == len(results) else 1


def cmd_approve(a):
    """Re-score a roundtrip --json result under an approvals file, without
    running anything."""
    doc = json.load(open(a.results))
    approved = approvals.load(a.approved)
    results = doc['results']
    nofacts = sum(1 for r in results if r['status'] != 'error' and r.get('must') and 'stable' not in r)
    for r in results:
        approvals.apply(r, approved)
    if nofacts:
        print('# note: %d results with findings have no facts (made before the runner recorded them): '
              'nothing in them can be approved' % nofacts, file=sys.stderr)
    return roundtrip_report(a, doc.get('impl', '?'), results, len(results), doc.get('ascii_passed_over', 0), approved)


def cmd_check_goldens(a):
    changed = 0
    for p in load_manifest():
        g = os.path.join(a.dir, p['name'] + '.mdl')
        expf = os.path.join(CONF, 'expected', p['name'] + '.json')
        if not os.path.exists(g) or not os.path.exists(expf):
            continue
        exp = json.load(open(expf))
        act = mdlview.read_binary(open(g, 'rb').read())
        rep = compare(exp, act, 'compile')
        items = [(l, pth, m) for l, pth, m in rep.items]
        if items:
            changed += 1
            print(p['name'])
            for l, pth, m in items:
                print('   %s %s: %s' % (l.upper(), pth, m))
    print('%d probe(s) changed' % changed)
    return 1 if changed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd_name', required=True)
    r = sub.add_parser('run')
    r.add_argument('--impl', required=True)
    r.add_argument('--cmd', required=True)
    r.add_argument('--only', nargs='*')
    r.add_argument('--test', nargs='*', choices=['compile', 'decompile'])
    r.add_argument('--json')
    r.add_argument('--max', type=int, default=6)
    r.add_argument('-v', '--verbose', action='store_true')
    e = sub.add_parser('expect')
    e.add_argument('--second')
    c = sub.add_parser('check-goldens')
    c.add_argument('dir')
    st = sub.add_parser('stock')
    st.add_argument('--impl', required=True)
    st.add_argument('--cmd', required=True)
    st.add_argument('--root')
    st.add_argument('--only', nargs='*')
    st.add_argument('--json')
    st.add_argument('--max', type=int, default=6)
    st.add_argument('-v', '--verbose', action='store_true')
    rt = sub.add_parser('roundtrip')
    rt.add_argument('--impl', required=True)
    rt.add_argument('--cmd', required=True)
    rt.add_argument('--resource-dir', action='append', help='more folders with supermodels, skeletons and materials (repeatable)')
    rt.add_argument('--workers', type=int, default=0, help='parallel models (default: one per CPU)')
    rt.add_argument('--max-memory', type=float, default=4, help='memory each worker may use, in GB (default 4; the implementation run is not limited)')
    rt.add_argument('--json')
    rt.add_argument('--partial', help='append each result here as a JSON line as it finishes; models already in it '
                                      'are not run again (resume a stopped run)')
    rt.add_argument('--model-timeout', type=int, default=0,
                    help='seconds one model may take, all four calls and the comparison; past it the model is an '
                         'error (default: no limit beyond 120 s per call)')
    rt.add_argument('--max', type=int, default=6)
    rt.add_argument('-v', '--verbose', action='store_true')
    rt.add_argument('--approved', help='an approvals file (runner/approvals/): findings it covers are reported apart, '
                                       'and a model with only those passes as pass-approved')
    rt.add_argument('paths', nargs='+')
    ap_ = sub.add_parser('approve')
    ap_.add_argument('--results', required=True, help='a roundtrip --json file')
    ap_.add_argument('--approved', required=True, help='an approvals file (runner/approvals/)')
    ap_.add_argument('--json', help='write the re-scored results here')
    ap_.add_argument('--max', type=int, default=6)
    ap_.add_argument('-v', '--verbose', action='store_true')
    v = sub.add_parser('view')
    v.add_argument('file')
    a = ap.parse_args()
    if a.cmd_name == 'run':
        sys.exit(cmd_run(a))
    if a.cmd_name == 'stock':
        sys.exit(cmd_stock(a))
    if a.cmd_name == 'roundtrip':
        sys.exit(cmd_roundtrip(a))
    if a.cmd_name == 'approve':
        sys.exit(cmd_approve(a))
    if a.cmd_name == 'expect':
        cmd_expect(a)
    elif a.cmd_name == 'check-goldens':
        sys.exit(cmd_check_goldens(a))
    elif a.cmd_name == 'view':
        print(json.dumps(mdlview.read_file(a.file), indent=1))


if __name__ == '__main__':
    main()
