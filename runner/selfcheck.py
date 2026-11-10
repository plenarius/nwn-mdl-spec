#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""The repository's own checks (standard library only; run by CI).

1. Every table loads with runner/miniyaml.py (and, when PyYAML is installed,
   gives the same data as a full YAML reader).
2. Every rule ID mentioned anywhere is defined exactly once in spec/.
3. The expected files are what `mdlconf.py expect --second
   conformance/goldens/run2` makes from the goldens.
4. Every golden compiled against itself passes (the comparison is sound).
5. Every golden decodes identically with ksy/nwn_mdl.ksy.
"""
import collections
import glob
import json
import os
import re
import subprocess
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import miniyaml  # noqa: E402
import mdlconf  # noqa: E402
import mdlview  # noqa: E402


def check_tables():
    bad = []
    try:
        import yaml  # optional
    except ImportError:
        yaml = None
    for f in sorted(glob.glob(os.path.join(ROOT, 'tables', '*.yaml')) + [os.path.join(ROOT, 'conformance', 'stock.yaml'),
                                                                          os.path.join(ROOT, 'ksy', 'nwn_mdl.ksy')]):
        try:
            a = miniyaml.load(f)
        except Exception as e:  # noqa: BLE001
            bad.append('%s: %s' % (f, e))
            continue
        if yaml is not None and yaml.safe_load(open(f)) != a:
            bad.append('%s: miniyaml and PyYAML disagree' % f)
    return bad


def check_rules():
    defined = collections.Counter()
    for f in glob.glob(os.path.join(ROOT, 'spec', '*.md')):
        for r in re.findall(r'\*\*(MDL-[A-Z]+-\d{3})\*\*', open(f).read()):
            defined[r] += 1
    bad = ['%s defined %d times' % (r, n) for r, n in defined.items() if n > 1]
    for f in glob.glob(os.path.join(ROOT, '**', '*'), recursive=True):
        if os.path.isdir(f) or '/goldens/' in f or '/.git/' in f or not f.endswith(('.md', '.yaml', '.json', '.py', '.ksy')):
            continue
        for r in set(re.findall(r'MDL-[A-Z]+-\d{3}', open(f, errors='replace').read())):
            if r not in defined:
                bad.append('%s: %s is not defined' % (os.path.relpath(f, ROOT), r))
    return bad


def check_expected():
    bad = []
    tmp = tempfile.mkdtemp(prefix='mdlspec-self-')
    orig = os.path.join(ROOT, 'conformance', 'expected')
    for p in mdlconf.load_manifest():
        g = os.path.join(ROOT, 'conformance', 'goldens', p['name'] + '.mdl')
        if not os.path.exists(g):
            continue
        exp = json.load(open(os.path.join(orig, p['name'] + '.json')))
        data = open(g, 'rb').read()
        fresh = mdlconf.normalise(mdlview.read_binary(data))
        g2 = os.path.join(ROOT, 'conformance', 'goldens', 'run2', p['name'] + '.mdl')
        vol = set()
        if os.path.exists(g2):
            f1 = dict(mdlconf.flat(fresh))
            f2 = dict(mdlconf.flat(mdlconf.normalise(mdlview.read_binary(open(g2, 'rb').read()))))
            vol = {k for k in f1 if f1[k] != f2.get(k)}
        if sorted(vol) != exp['volatile']:
            bad.append('%s: volatile fields differ' % p['name'])
        for k in ('model', 'nodes', 'animations'):
            if json.loads(json.dumps(fresh[k])) != exp[k]:
                bad.append('%s: %s differs from the golden' % (p['name'], k))
        rep = mdlconf.compare(exp, mdlview.read_binary(data), 'compile')
        if rep.items:
            bad.append('%s: the golden does not pass against itself: %s' % (p['name'], rep.items[:2]))
    os.rmdir(tmp)
    return bad


def check_ksy():
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'ksy', 'check_ksy.py')], capture_output=True, text=True)
    return [] if r.returncode == 0 else [r.stdout.strip().splitlines()[-1]]


def _view(meshes, names=None):
    """A minimal decoded model: a root and one trimesh node per mesh, each
    mesh {'pos': [...], 'tris': [...], and optional streams}."""
    names = names or ['m%d' % i for i in range(len(meshes))]
    nodes = [{'name': 'root', 'parent': None, 'type': 'dummy', 'flags': 1, 'number': 0,
              'inheritcolor': 0, 'controllers': []}]
    for i, (name, m) in enumerate(zip(names, meshes)):
        v = {'position': m['pos'], 'uv0': m.get('uv', [[0, 0]] * len(m['pos']))}
        for k in ('tangent', 'handedness', 'normal', 'bumpmap_slot3'):
            if k in m:
                v[k] = m[k]
        faces = [{'v': t, 'material': 0, 'normal': [0, 0, 1], 'distance': 0, 'adjacent': [-1, -1, -1]}
                 for t in m['tris']]
        nodes.append({'name': name, 'parent': 'root', 'type': 'trimesh', 'flags': 0x21, 'number': i + 1,
                      'inheritcolor': 0, 'controllers': [],
                      'mesh': {'render': 1, 'vertex_count': len(m['pos']), 'face_count': len(faces),
                               'faces': faces, 'index_lists': [[c for t in m['tris'] for c in t]],
                               'vertices': v}})
        if 'slots' in m:
            nodes[-1]['mesh']['texanim_slots_used'] = m['slots']
    return {'model': {'name': 'x', 'classification': 'character', 'fog': 1, 'animationscale': 1,
                      'supermodel': 'NULL', 'node_count': len(nodes), 'bmin': [0, 0, 0], 'bmax': [0, 0, 0],
                      'radius': 0},
            'nodes': nodes, 'animations': [], 'volatile': []}


def check_approvals():
    """The approvals (runner/approvals.py) on small made-up models: each
    category is approved where its condition holds and nowhere else."""
    import approvals
    bad = []
    files = sorted(glob.glob(os.path.join(HERE, 'approvals', '*.json')))
    for f in files:
        try:
            approvals.load(f)
        except approvals.ApprovalsError as e:
            bad.append(str(e))
    full = approvals.load(os.path.join(HERE, 'approvals', 'layonara.json'))
    nan = 'nan'
    P = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
    T = [[1, 0, 0]] * 4
    # the original: two triangles that share an edge, written with six vertices
    dup = {'pos': [P[0], P[1], P[2], P[0], P[2], P[3]], 'tris': [[0, 1, 2], [3, 4, 5]]}
    merged = {'pos': P, 'tris': [[0, 1, 2], [0, 2, 3]]}
    degen = {'pos': dup['pos'] + [P[1], P[1], P[3]], 'tris': [[0, 1, 2], [6, 7, 8], [3, 4, 5]]}
    flat = {'pos': dup['pos'] + [P[0], P[1], P[3]], 'tris': [[0, 1, 2], [6, 7, 8], [3, 4, 5]]}
    cases = [
        # (what, original meshes, compiled meshes, expected status, expected approval ids, names)
        ('duplicate vertices merged', [dup], [merged], 'pass-approved', {'vertex-layout'}, None),
        ('a corner moved', [dup], [dict(merged, pos=[P[0], P[1], [1, 1, 0.5], P[3]])], 'fail', set(), None),
        ('a zero-area face dropped', [degen], [merged], 'pass-approved',
         {'vertex-layout', 'dropped-zero-area-faces'}, None),
        ('a face with area dropped', [flat], [merged], 'fail', set(), None),
        ('NaN tangents filled', [dict(dup, tangent=[T[0], [nan] * 3, T[0], T[0], T[0], [0, 0, 0]],
                                      handedness=[1] * 6)],
         [dict(merged, tangent=[T[0], [0, 1, 0], T[0], [0, 1, 0]], handedness=[1] * 4)],
         'pass-approved', {'nan-tangent-fill'}, None),
        ('a good tangent changed', [dict(dup, tangent=[[0, 1, 0]] + [T[0]] * 4 + [[nan] * 3], handedness=[1] * 6)],
         [dict(merged, tangent=[T[0], T[0], T[0], [0, 1, 0]], handedness=[1] * 4)], 'fail', set(), None),
        ('tangents baked', [dup], [dict(merged, tangent=T + [T[0]], handedness=[1] * 5,
                                        pos=P + [P[0]], tris=[[0, 1, 2], [4, 2, 3]])],
         'pass-approved', {'tangents-baked'}, None),
        ('1.69 water slots', [dict(dup, bumpmap_slot3=[[0, 0, 0]] * 6, slots=[0, 1, 2, 4])], [merged],
         'pass-approved', {'water-texanim-169'}, None),
        ('slot 3 dropped without the water slots', [dict(dup, bumpmap_slot3=[[0, 0, 0]] * 6)], [merged],
         'fail', set(), None),
        ('a 32-character name cut', [merged], [merged], 'pass-approved', {'name-cut-31'},
         (['n' * 32], ['n' * 31])),
        ('a cut name that another node has', [merged, merged], [merged, merged], 'fail', set(),
         (['n' * 32, 'n' * 31], ['n' * 31, 'n' * 31])),
    ]
    for what, em, am, status, ids, names in cases:
        exp = mdlconf.normalise(_view(em, names and names[0]))
        exp['volatile'] = []
        act = _view(am, names and names[1])
        res = {'file': what, 'must': [], 'should': [], 'facts': {}, 'stable': True}
        for test in ('compile',):
            rep = mdlconf.compare(exp, act, test, facts=True)
            res['must'] += [[test, p, m] for lvl, p, m in rep.items if lvl == 'must']
            res['facts'].update(rep.facts)
        plain = 'fail' if res['must'] else 'pass'
        approvals.apply(res, full)
        got = {x[3] for x in res.get('approved', [])}
        if res['status'] != status or got != ids:
            bad.append('%s: %s %s, expected %s %s; left %s' % (what, res['status'], sorted(got), status,
                                                               sorted(ids), res['must'][:3]))
        again = json.loads(json.dumps(res))
        if approvals.apply(again, full) != res:
            bad.append('%s: scoring the result again changes it' % what)
        # without approvals, the plain status
        if approvals.apply(json.loads(json.dumps(res)), None)['status'] != plain:
            bad.append('%s: without approvals the status is not %s' % (what, plain))
        # an approvals file without one of the categories approves no mesh that needs it
        for drop in ids:
            part = dict(full, entries={k: v for k, v in full['entries'].items() if k != drop})
            r2 = approvals.apply(json.loads(json.dumps(res)), part)
            if r2['status'] != 'fail' or any(x[3] == drop for x in r2.get('approved', [])):
                bad.append('%s: still %s without %s' % (what, r2['status'], drop))
    # an unstable compile is never pass-approved
    res = {'file': 'u', 'status': 'fail', 'must': [], 'should': [], 'stable': False}
    exp = mdlconf.normalise(_view([dup]))
    exp['volatile'] = []
    rep = mdlconf.compare(exp, _view([merged]), 'compile', facts=True)
    res['must'] = [['compile', p, m] for lvl, p, m in rep.items if lvl == 'must']
    res['facts'] = rep.facts
    if approvals.apply(res, full)['status'] != 'unstable':
        bad.append('an unstable model with approved findings is %s' % res['status'])
    # an unstable compile whose second compile differs in face adjacency alone
    for what, adj, entries, must, status in (
            ('adjacency only', 3, full, False, 'pass-approved'),
            ('adjacency only, no entry', 3, dict(full, entries={k: v for k, v in full['entries'].items()
                                                              if k != 'unstable-adjacency-only'}),
             False, 'unstable'),
            ('more than adjacency', 0, full, False, 'unstable'),
            ('adjacency only, a finding left', 3, full, True, 'fail')):
        res = {'file': what, 'status': 'unstable', 'must': [], 'should': [], 'stable': False,
               'unstable_adjacency_only': adj}
        rep = mdlconf.compare(exp, _view([merged]), 'compile', facts=True)
        res['must'] = [['compile', p, m] for lvl, p, m in rep.items if lvl == 'must']
        res['facts'] = rep.facts
        if must:
            res['must'].append(['compile', 'nodes[m0].mesh.render', 'expected 1, got 0'])
        approvals.apply(res, entries)
        ids = {x[3] for x in res.get('approved', [])}
        if res['status'] != status or approvals.stable_except_adjacency(res) != (status == 'pass-approved'):
            bad.append('%s: %s %s, expected %s' % (what, res['status'], sorted(ids), status))
        if status == 'pass-approved' and ids != {'vertex-layout', 'unstable-adjacency-only'}:
            bad.append('%s: approved %s' % (what, sorted(ids)))
        if approvals.apply(json.loads(json.dumps(res)), entries) != res:
            bad.append('%s: scoring the result again changes it' % what)
        if approvals.apply(json.loads(json.dumps(res)), None)['status'] != 'fail':  # vertex_count is left
            bad.append('%s: without approvals the status is not fail' % what)
    # mdlconf.adjacency_only on a compiled golden: adjacency bytes alone, or more
    g = open(os.path.join(ROOT, 'conformance', 'goldens', 'run2', 'zspec_merge.mdl'), 'rb').read()
    _, recs = mdlview.face_adjacency_masked(g)

    def patched(*edits):
        d = bytearray(g)
        for off, val in edits:
            d[off:off + 2] = struct.pack('<h', val)
        return bytes(d)

    adj0 = struct.unpack_from('<h', g, recs[0] + 20)[0]
    adj1 = struct.unpack_from('<h', g, recs[1] + 22)[0]
    vtx = struct.unpack_from('<h', g, recs[0] + 26)[0]
    for what, other, want in (
            ('the same file', g, 0),
            ('one face adjacency', patched((recs[0] + 20, adj0 + 1)), 1),
            ('two faces adjacency', patched((recs[0] + 20, adj0 + 1), (recs[1] + 22, adj1 - 1)), 2),
            ('a vertex index', patched((recs[0] + 26, vtx + 1)), 0),
            ('adjacency and a vertex index', patched((recs[0] + 20, adj0 + 1), (recs[0] + 26, vtx + 1)), 0),
            ('the face normal', patched((recs[0] + 0, 1)), 0),
            ('a longer file', g + b'\0' * 4, 0)):
        got = mdlconf.adjacency_only(g, other)
        if got != want:
            bad.append('adjacency_only, %s: %s, expected %s' % (what, got, want))
    if len(recs) != 10:
        bad.append('zspec_merge: %d face records found, expected 10' % len(recs))
    # results without facts (made before they were recorded) approve nothing
    res = {'file': 'old', 'status': 'fail', 'must': [['compile', 'nodes[m0].mesh.vertex_count', 'expected 6, got 4']],
           'should': []}
    if approvals.apply(res, full)['status'] != 'fail':
        bad.append('a result without facts was approved')
    return bad


def main():
    failed = False
    for name, fn in (('tables', check_tables), ('rule references', check_rules),
                     ('expected files', check_expected), ('approvals', check_approvals), ('ksy', check_ksy)):
        bad = fn()
        print('%-16s %s' % (name, 'ok' if not bad else 'FAIL'))
        for b in bad[:20]:
            print('    ' + b)
        failed |= bool(bad)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
