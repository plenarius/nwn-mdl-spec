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
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import approvals  # noqa: E402
import mdlview  # noqa: E402

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


def compare_mesh(r, path, exp, act, profile, volatile, aabb=False):
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
    amap = {}
    for c in act:
        amap.setdefault(c['id'], c)
    for c in exp:
        p = '%s.controllers[%s]' % (path, c['name'])
        a = amap.pop(c['id'], None)
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
    for cid, a in amap.items():
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
                        break
        if 'mesh' in e and not anim:
            if 'mesh' not in a:
                r.must(p + '.mesh', 'missing')
            else:
                before = len(r.items)
                compare_mesh(r, p + '.mesh', e['mesh'], a['mesh'], profile, vol, bool(e['flags'] & 0x200))
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
        print(line)
        if r['status'] in ('error', 'pending'):
            print('    ' + r['reason'].replace('\n', '\n    '))
        for pth, msg in r.get('must', [])[:a.max]:
            print('    MUST   %s: %s' % (pth, msg))
        if a.verbose:
            for pth, msg in r.get('should', [])[:a.max]:
                print('    SHOULD %s: %s' % (pth, msg))
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
            acts = [('decompile', mdlview.read_ascii(data['ascii'].decode('latin-1'))),
                    ('compile', mdlview.read_binary(data['binary']))]
        except Exception as e:  # noqa: BLE001
            res.update(status='error', reason='cannot read the output: %s' % e)
            return res
        facts = {}
        for test, act in acts:
            rep = compare(exp, act, test, facts=True)
            for lvl, pth, msg in rep.items:
                res[lvl].append([test, pth, msg])
            facts.update(rep.facts)
        if facts:
            res['facts'] = facts
        # Checked whatever the findings, so that approvals (approvals.py) can
        # tell a model whose findings are all approved from an unstable one.
        res['stable'] = data['binary2'] == data['binary']
        if not res['stable']:
            res['unstable_fields'] = unstable_fields(acts[1][1], data['binary2'])
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


def unstable_fields(first, second_data):
    """What differs between the first compile (its view) and the second
    (bytes): {path with indices taken out: count}, the ten most common."""
    try:
        x = dict(flat(first))
        y = dict(flat(mdlview.read_binary(second_data)))
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
    print('# totals: ' + ', '.join('%s %d' % (s, n) for s, n in sorted(counts.items())))
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
