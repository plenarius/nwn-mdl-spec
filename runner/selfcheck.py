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
6. The approvals (runner/approvals.py) and the facts behind them
   (runner/nodefacts.py, the round trip's stability explanations, accepted
   left-out tangents, face-record indices) on goldens and made-up models.
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
        if res['status'] != status or bool(approvals.stability_approved(res)) != (status == 'pass-approved'):
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


def _tree(spec, supermodel='NULL', node_count=None, anims=()):
    """A made-up decoded model from [(name, parent, number, mesh hint or
    None for a dummy)], stored in this order (depth-first)."""
    nodes = []
    for name, parent, number, hint in spec:
        n = {'name': name, 'parent': parent, 'type': 'dummy' if hint is None else 'trimesh',
             'flags': 1 if hint is None else 0x21, 'number': number, 'inheritcolor': 0, 'controllers': []}
        if hint is not None:
            n['mesh'] = {'transparencyhint': hint}
        nodes.append(n)
    out = []
    for name, nn, hdr in anims:
        out.append({'name': name, 'length': 1, 'transtime': 0, 'animroot': '', 'events': [], 'node_count': hdr,
                    'nodes': [{'name': a, 'parent': p, 'type': 'dummy', 'flags': 1, 'number': num, 'controllers': []}
                              for a, p, num in nn]})
    return {'model': {'name': 'x', 'classification': 0, 'fog': 1, 'animationscale': 1, 'supermodel': supermodel,
                      'node_count': len(nodes) if node_count is None else node_count,
                      'bmin': [0, 0, 0], 'bmax': [0, 0, 0], 'radius': 0},
            'nodes': nodes, 'animations': out, 'volatile': []}


def _ascii(spec, supermodel='NULL'):
    """ASCII declaring [(name, parent, mesh hint or None)] in this order."""
    lines = ['newmodel x', 'setsupermodel x %s' % supermodel, 'beginmodelgeom x']
    for name, parent, hint in spec:
        lines += ['node %s %s' % ('dummy' if hint is None else 'trimesh', name), '  parent %s' % (parent or 'NULL')]
        if hint is not None:
            lines.append('  transparencyhint %d' % hint)
        lines.append('endnode')
    return '\n'.join(lines + ['endmodelgeom x', 'donemodel x', ''])


def _node_result(exp, act, text, sup=None, entries=None):
    """Score a made-up compile as the round trip does (findings, facts
    including `compile model.nodes`), under `entries`."""
    import approvals
    import nodefacts
    rep = mdlconf.compare(exp, act, 'compile', facts=True)
    res = {'file': 'x', 'must': [['compile', p, m] for lvl, p, m in rep.items if lvl == 'must'],
           'should': [], 'facts': dict(rep.facts), 'stable': True}
    if any(mdlconf.NODE_FINDING.search(p) for _, p, _ in res['must']):
        res['facts']['compile model.nodes'] = nodefacts.model_facts(exp, act, text, sup)
    return approvals.apply(res, entries)


def check_node_facts():
    """runner/nodefacts.py on the goldens: the sort and the numbering rules
    reproduce every probe the engine compiled, and every golden is
    reachable; then the node approvals on made-up models."""
    import approvals
    import nodefacts as N
    bad = []
    conf = os.path.join(ROOT, 'conformance')
    for p in mdlconf.load_manifest():
        g = os.path.join(conf, 'goldens', p['name'] + '.mdl')
        src = os.path.join(conf, 'probes', p['name'] + '.mdl')
        if not (os.path.exists(g) and os.path.exists(src)):
            continue
        view = mdlview.read_binary(open(g, 'rb').read())
        text = open(src, encoding='latin-1').read()
        decl = N.ascii_declarations(text)
        names = [n['name'].lower() for n in view['nodes']]
        if len({d[0] for d in decl}) != len(decl) or len(set(names)) != len(names) or \
                not set(names) <= {d[0] for d in decl}:
            continue  # duplicate or cut names (zspec_super, zspec_kid4, zspec_name32/40)
        sname = N.ascii_supermodel(text)
        sup = None
        if sname:
            sp = os.path.join(conf, 'goldens', sname + '.mdl')
            if not os.path.exists(sp):
                continue
            sup = N.Super.from_binary(mdlview.read_binary(open(sp, 'rb').read()))
        kids, key, root = {}, {}, None
        for n, par, k in decl:
            key[n] = k
            if par is None:
                root = n
            elif par is not False:
                kids.setdefault(par, []).append(n)
        if root is None or N.stored_order(root, kids, key) != names:
            if p['name'] != 'zspec_numbers':  # a node left out of the tree on purpose
                bad.append('%s: the sort does not give the stored order' % p['name'])
        ref = N.ref_numbers([(n, par) for n, par, _ in decl], sup)
        if any(n['number'] != ref.get(n['name'].lower()) for n in view['nodes']):
            bad.append('%s: the numbering rule does not give the golden numbers' % p['name'])
        if not N.reachable(N.Geo(view['nodes']), sup):
            bad.append('%s: a golden the engine compiled is called unreachable' % p['name'])
    full = approvals.load(os.path.join(HERE, 'approvals', 'layonara.json'))
    # (what, original tree, compiled tree, ASCII declarations, expected status, approved ids)
    d = None
    cases = [
        ('N2: numbers no declaration order gives', [('r', None, 0, d), ('x', 'r', 2, d), ('y', 'r', 1, d)],
         [('r', None, 0, d), ('x', 'r', 1, d), ('y', 'r', 2, d)], [('r', None, d), ('x', 'r', d), ('y', 'r', d)],
         'pass-approved', {'renumbered'}),
        ('N1: declared out of tree order (reachable)',
         [('r', None, 0, d), ('x', 'r', 1, d), ('x1', 'x', 3, d), ('y', 'r', 2, d)],
         [('r', None, 0, d), ('x', 'r', 1, d), ('x1', 'x', 2, d), ('y', 'r', 3, d)],
         [('r', None, d), ('x', 'r', d), ('x1', 'x', d), ('y', 'r', d)], 'fail', set()),
        ('numbers not as the rule gives the ASCII', [('r', None, 0, d), ('x', 'r', 2, d), ('y', 'r', 1, d)],
         [('r', None, 0, d), ('x', 'r', 1, d), ('y', 'r', 3, d)], [('r', None, d), ('x', 'r', d), ('y', 'r', d)],
         'fail', set()),
        ('T2: children out of sort order, sorted by the compile',
         [('r', None, 0, d), ('m1', 'r', 1, 1), ('m0', 'r', 2, 0)],
         [('r', None, 0, d), ('m0', 'r', 2, 0), ('m1', 'r', 1, 1)], [('r', None, d), ('m1', 'r', 1), ('m0', 'r', 0)],
         'pass-approved', {'tree-sorted'}),
        ('T2 with numbers', [('r', None, 0, d), ('m1', 'r', 2, 1), ('m0', 'r', 1, 0)],
         [('r', None, 0, d), ('m0', 'r', 2, 0), ('m1', 'r', 1, 1)], [('r', None, d), ('m1', 'r', 1), ('m0', 'r', 0)],
         'pass-approved', {'tree-sorted', 'renumbered'}),
        ('a tree the sort does not give', [('r', None, 0, d), ('m1', 'r', 1, 1), ('m0', 'r', 2, 0)],
         [('r', None, 0, d), ('m0', 'r', 2, 0), ('m1', 'r', 1, 1), ('z', 'r', 3, d)],
         [('r', None, d), ('m1', 'r', 1), ('m0', 'r', 0), ('z', 'r', d)], 'fail', set()),
    ]
    # T1: 24 children already in sort order that std::sort shuffles (zspec_tsort24's kind)
    kids = [('d%d' % i, 'r', i + 1, d) for i in range(20)] + [('m%d' % i, 'r', 21 + i, 1) for i in range(4)]
    key = {k[0]: (k[3] is not None, k[3] or 0) for k in kids}
    shuffled = N.sort_children([k[0] for k in kids], key)
    if shuffled == [k[0] for k in kids]:
        bad.append('engine_sort: 24 sorted children with ties come back unchanged; the T1 case tests nothing')
    byname = {k[0]: k for k in kids}
    cases.append(('T1: >16 sorted children shuffled', [('r', None, 0, d)] + kids,
                  [('r', None, 0, d)] + [(n, 'r', byname[n][2], byname[n][3]) for n in shuffled],
                  [('r', None, d)] + [(k[0], 'r', k[3]) for k in kids], 'fail', set()))
    # T1 after the decompiler fix (cleanmodels PR #140): the children declared
    # in the order std::sort maps onto the stored one, so the tree comes back;
    # the original numbered them in stored order, which no declaration gives
    stored = [k[0] for k in kids]
    idx = list(range(len(stored)))
    N.engine_sort(idx, lambda x, y: N.key_less(key[stored[x]], key[stored[y]]))
    D = [None] * len(stored)
    for j, i in enumerate(idx):
        D[i] = stored[j]
    if N.sort_children(D, key) != stored:
        bad.append('engine_sort: the inverse declaration order does not rebuild the stored order')
    cases.append(('T1 after the decompiler fix: tree back, numbers differ', [('r', None, 0, d)] + kids,
                  [('r', None, 0, d)] + [(n, 'r', D.index(n) + 1, byname[n][3]) for n in stored],
                  [('r', None, d)] + [(n, 'r', byname[n][3]) for n in D], 'pass-approved', {'renumbered'}))
    for what, orig, comp, decl, status, ids in cases:
        exp = mdlconf.normalise(_tree(orig))
        exp['volatile'] = []
        res = _node_result(exp, _tree(comp), _ascii(decl), None, full)
        got = {x[3] for x in res.get('approved', [])}
        if res['status'] != status or got != ids:
            bad.append('%s: %s %s, expected %s %s; left %s' % (what, res['status'], sorted(got), status,
                                                               sorted(ids), res['must'][:3]))
        for drop in ids:
            part = dict(full, entries={k: v for k, v in full['entries'].items() if full['entries'][k]['id'] != drop})
            r2 = approvals.apply(json.loads(json.dumps(res)), part)
            if r2['status'] != 'fail' or any(x[3] == drop for x in r2.get('approved', [])):
                bad.append('%s: still %s without %s' % (what, r2['status'], drop))
        if approvals.apply(json.loads(json.dumps(res)), full) != res:
            bad.append('%s: scoring the result again changes it' % what)
    # supermodels: S4 (numbered as if there were none) and the count
    sv = _tree([('sr', None, 0, d), ('arm', 'sr', 1, d), ('hand', 'arm', 2, d)])
    sup = N.Super.from_binary(sv)
    orig = [('r', None, 0, d), ('arm', 'r', 1, d), ('extra', 'r', 2, d)]
    comp = [('r', None, 0, d), ('arm', 'r', 1, d), ('extra', 'r', -1, d)]
    decl = [('r', None, d), ('arm', 'r', d), ('extra', 'r', d)]
    for what, ocount, ccount, status, ids in (
            ('S4: compiled without its supermodel', 3, 3 + 3 + 1, 'pass-approved', {'renumbered', 'supermodel-count'}),
            ('S1: a count against another supermodel', 9, 3 + 3 + 1, 'pass-approved',
             {'renumbered', 'supermodel-count'}),
            ('a count not by MDL-NODE-030', 3, 8, 'fail', {'renumbered'})):
        exp = mdlconf.normalise(_tree(orig, 'sup', ocount))
        exp['volatile'] = []
        res = _node_result(exp, _tree(comp, 'sup', ccount), _ascii(decl, 'sup'), sup, full)
        got = {x[3] for x in res.get('approved', [])}
        if res['status'] != status or got != ids:
            bad.append('%s: %s %s, expected %s %s' % (what, res['status'], sorted(got), status, sorted(ids)))
    dup = [('r', None, 0, d), ('arm', 'r', 1, d), ('arm', 'r', 2, d)]
    exp_dup = mdlconf.normalise(_tree(dup, 'sup', 3))
    exp_dup['volatile'] = []
    res = _node_result(exp_dup, _tree([('r', None, 0, d), ('arm', 'r', 1, d), ('arm', 'r', -1, d)], 'sup', 7),
                       _ascii([('r', None, d), ('arm', 'r', d), ('arm', 'r', d)], 'sup'), sup, full)
    if {x[3] for x in res.get('approved', [])} != {'supermodel-count'} or res['status'] != 'fail':
        bad.append('a count with duplicate names: %s %s' % (res['status'], res.get('approved')))
    res = _node_result(exp, _tree(comp, 'sup', 7), _ascii(decl, 'sup'), None, full)
    if res['status'] != 'fail' or res.get('approved'):
        bad.append('a supermodel not found: %s %s' % (res['status'], res.get('approved')))
    # an ASCII supermodel numbered by the rules (MDL-NODE-010)
    asup = N.Super.from_ascii(_ascii([('sr', None, d), ('hand', 'arm', d), ('arm', 'sr', d)]), None)
    if asup.count != 3 or asup.bypath != {N.ROOT: 0, N.ROOT + ('arm',): 2, N.ROOT + ('arm', 'hand'): 1}:
        bad.append('Super.from_ascii: %s %s' % (asup.count, asup.bypath))
    # A2: the animation header's count
    tree = [('r', None, 0, d), ('x', 'r', 1, d)]
    for what, ohdr, chdr, cnodes, status in (
            ('A2: header count not the tree size', 5, 2, [('r', None, 0), ('x', 'r', 1)], 'pass-approved'),
            ('the compile not the tree size either', 5, 3, [('r', None, 0), ('x', 'r', 1)], 'fail'),
            ('other nodes in the compile', 5, 2, [('r', None, 0), ('y', 'r', -1)], 'fail')):
        exp = mdlconf.normalise(_tree(tree, anims=[('a', [('r', None, 0), ('x', 'r', 1)], ohdr)]))
        exp['volatile'] = []
        res = _node_result(exp, _tree(tree, anims=[('a', cnodes, chdr)]), _ascii([('r', None, d), ('x', 'r', d)]),
                           None, full)
        got = {x[3] for x in res.get('approved', [])}
        if res['status'] != status or (status == 'pass-approved') != (got == {'anim-header-count'}):
            bad.append('%s: %s %s, expected %s' % (what, res['status'], sorted(got), status))
    # aabb planes at a tie (MDL-MESH-052)
    def aabb(plane, right_centre):
        c = right_centre
        return [{'min': [-1, -1, 0], 'max': [1, 1, 0], 'face': -1, 'plane': plane},
                {'min': [-0.5, -0.5, 0], 'max': [-0.5, -0.5, 0], 'face': 0, 'plane': 0},
                {'min': c, 'max': c, 'face': 1, 'plane': 0}]
    for what, op, cp, rc, status in (
            ('a tie of +X and -Y', 1, 16, [0.5, -1.5, 0], 'pass-approved'),
            ('no tie', 1, 16, [0.5, -1, 0], 'fail'),
            ('a tie, the sign against the delta', 1, 2, [0.5, -1.5, 0], 'fail'),
            ('zero delta: -Z', 32, 1, [-0.5, -0.5, 0], 'fail')):
        e = _tree([('r', None, 0, d), ('w', 'r', 1, d)])
        a = _tree([('r', None, 0, d), ('w', 'r', 1, d)])
        e['nodes'][1].update(flags=0x221, type='aabb', aabb=aabb(op, rc))
        a['nodes'][1].update(flags=0x221, type='aabb', aabb=aabb(cp, rc))
        exp = mdlconf.normalise(e)
        exp['volatile'] = []
        res = _node_result(exp, a, _ascii([('r', None, d), ('w', 'r', d)]), None, full)
        got = {x[3] for x in res.get('approved', [])}
        if res['status'] != status or (status == 'pass-approved') != (got == {'aabb-plane-tie'}):
            bad.append('aabb %s: %s %s, expected %s' % (what, res['status'], sorted(got), status))
    return bad


def check_stability():
    """The round trip's explanations of an unstable second compile, and
    their approvals."""
    import approvals
    bad = []
    full = approvals.load(os.path.join(HERE, 'approvals', 'layonara.json'))
    g = open(os.path.join(ROOT, 'conformance', 'goldens', 'run2', 'zspec_merge.mdl'), 'rb').read()
    _, recs = mdlview.face_adjacency_masked(g)
    floats = mdlview.float_fields(g)
    zero = next(o for o in sorted(floats) if g[o:o + 4] == bytes(4) and o > 12 + 200)
    one = next(o for o in sorted(floats) if g[o:o + 4] not in (bytes(4), b'\0\0\0\x80') and o > 12 + 200)
    adjf = {o + k for o in recs for k in range(20, 26)}
    mat = next(o for o in range(12 + 200, len(g) - 4, 4)  # a zero word not read as a float
               if g[o:o + 4] == bytes(4) and o not in floats and not adjf & set(range(o, o + 4)))
    bmin = 12 + 136

    def patched(*edits):
        b = bytearray(g)
        for off, val in edits:
            b[off:off + len(val)] = val
        return bytes(b)

    def ulp(off, n):
        return struct.pack('<I', struct.unpack_from('<I', g, off)[0] + n)
    adj = struct.pack('<h', struct.unpack_from('<h', g, recs[0] + 20)[0] + 1)
    for what, other, want in (
            ('a float 0.0 made -0.0', patched((zero, b'\0\0\0\x80')), {'signed_zero': 1}),
            ('-0.0 and adjacency', patched((zero, b'\0\0\0\x80'), (recs[0] + 20, adj)),
             {'signed_zero': 1, 'adjacency': 1}),
            ('a zero word that is no float given the sign bit', patched((mat, b'\0\0\0\x80')), None),
            ('another float changed', patched((one, ulp(one, 1))), None),
            ('the model box by 1 ulp', patched((bmin + 4, ulp(bmin + 4, 1))), {'bounds_ulp': 1}),
            ('the model box by 2 ulp', patched((bmin + 4, ulp(bmin + 4, 2))), None),
            ('the radius by 1 ulp', patched((12 + 160, ulp(12 + 160, 1))), None),
            ('a longer file', g + bytes(4), None)):
        if other is None:
            continue
        got = mdlconf.explain_bytes(g, other)
        if got != want:
            bad.append('explain_bytes, %s: %s, expected %s' % (what, got, want))
    # dead vertices (made-up views)
    P = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]

    def mesh_view(pos, tris):
        v = _view([{'pos': pos, 'tris': tris}])
        m = v['nodes'][1]['mesh']
        m['bmin'] = [min(p[k] for p in pos) for k in range(3)]
        m['bmax'] = [max(p[k] for p in pos) for k in range(3)]
        m['average'] = [sum(p[k] for p in pos) / len(pos) for k in range(3)]
        m['radius'] = 1.0
        return v
    degen = mdlconf.normalise(_view([{'pos': P + [[2, 2, 0], [2, 2, 0], [3, 3, 0]],
                                      'tris': [[0, 1, 2], [4, 5, 6], [0, 2, 3]]}]))
    first = P[:2] + [[3, 3, 0]] + P[2:]
    for what, v1, v2, want in (
            ('a vertex only a zero-area face used', mesh_view(first, [[0, 1, 3], [0, 3, 4]]),
             mesh_view(P, [[0, 1, 2], [0, 2, 3]]), {'dead_vertices': 1}),
            ('a vertex no zero-area face had', mesh_view(P[:2] + [[5, 5, 0]] + P[2:], [[0, 1, 3], [0, 3, 4]]),
             mesh_view(P, [[0, 1, 2], [0, 2, 3]]), None),
            ('and another vertex moved', mesh_view(first, [[0, 1, 3], [0, 3, 4]]),
             mesh_view(P[:3] + [[0, 1, 1]], [[0, 1, 2], [0, 2, 3]]), None),
            ('and the order changed', mesh_view(first, [[0, 1, 3], [0, 3, 4]]),
             mesh_view(P, [[0, 2, 3], [0, 1, 2]]), None),
            ('no vertex dropped', mesh_view(P, [[0, 1, 2], [0, 2, 3]]), mesh_view(P, [[0, 2, 3], [0, 1, 2]]), None)):
        got = mdlconf.dead_vertices_explained(v1, v2, degen)
        if got != want:
            bad.append('dead vertices, %s: %s, expected %s' % (what, got, want))
    # approving them
    for what, why, entries, must, status, ids in (
            ('dead vertices and adjacency', {'dead_vertices': 2, 'adjacency': 3}, full, False, 'pass-approved',
             {'dead-face-vertices', 'unstable-adjacency-only'}),
            ('dead vertices, adjacency not approved', {'dead_vertices': 2, 'adjacency': 3},
             dict(full, entries={k: v for k, v in full['entries'].items() if k != 'unstable-adjacency-only'}),
             False, 'unstable', set()),
            ('1 ulp', {'bounds_ulp': 1}, full, False, 'pass-approved', {'bounds-ulp'}),
            ('-0.0 and adjacency', {'signed_zero': 1, 'adjacency': 2}, full, False, 'pass-approved',
             {'signed-zero', 'unstable-adjacency-only'}),
            ('-0.0 not approved', {'signed_zero': 1},
             dict(full, entries={k: v for k, v in full['entries'].items() if k != 'signed-zero'}),
             False, 'unstable', set()),
            ('an unknown kind', {'vertex_order': 1}, full, False, 'unstable', set()),
            ('1 ulp, a finding left', {'bounds_ulp': 1}, full, True, 'fail', set())):
        res = {'file': what, 'status': 'unstable', 'must': [], 'should': [], 'stable': False,
               'unstable_adjacency_only': 0, 'unstable_explained': why}
        if must:
            res['must'].append(['compile', 'nodes[m0].mesh.render', 'expected 1, got 0'])
        approvals.apply(res, entries)
        got = approvals.stability_approved(res)
        if res['status'] != status or got != ids:
            bad.append('stability %s: %s %s, expected %s %s' % (what, res['status'], sorted(got), status,
                                                                sorted(ids)))
        if approvals.apply(json.loads(json.dumps(res)), entries) != res:
            bad.append('stability %s: scoring the result again changes it' % what)
    return bad


def check_tangents_and_faces():
    """Left-out tangents are accepted only when the compile gives them back
    exactly; a conformance compile's face records must hold the golden's
    vertex indices (MDL-MESH-043, MDL-BIN-049), a round trip's need not."""
    bad = []
    T = [[1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 0, 1]]
    P = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
    m = {'pos': P, 'tris': [[0, 1, 2], [0, 2, 3]], 'tangent': T, 'handedness': [1, 1, -1, 1]}
    exp = mdlconf.normalise(_view([m]))
    exp['volatile'] = []
    asc = _view([{'pos': P, 'tris': m['tris']}])
    for what, comp, want in (('given back exactly', _view([m]), 2),
                             ('one tangent off', _view([dict(m, tangent=[[1, 0, 0.001]] + T[1:])]), 0),
                             ('no compile', None, 0)):
        rep = mdlconf.compare(exp, asc, 'decompile')
        got = mdlconf.accept_left_out_tangents(rep, exp, comp)
        left = [p for lvl, p, _ in rep.items if p.endswith(('.tangent', '.handedness'))]
        if len(got) != want or len(left) != 2 - want:
            bad.append('left-out tangents, %s: %d accepted, %d left' % (what, len(got), len(left)))
    g = json.load(open(os.path.join(ROOT, 'conformance', 'expected', 'zspec_tanmirror.json')))
    act = mdlview.read_binary(open(os.path.join(ROOT, 'conformance', 'goldens', 'zspec_tanmirror.mdl'), 'rb').read())
    mesh = next(n['mesh'] for n in act['nodes'] if 'mesh' in n)
    idx = mesh['index_lists'][0]
    if [f['v'] for f in mesh['faces']] == [idx[i:i + 3] for i in range(0, len(idx), 3)]:
        bad.append('zspec_tanmirror: the face records name the clones; the case tests nothing')
    for f, i in zip(mesh['faces'], range(0, len(idx), 3)):
        f['v'] = idx[i:i + 3]  # the clones written into the face records
    for facts, want in ((False, True), (True, False)):
        rep = mdlconf.compare(g, act, 'compile', facts=facts)
        if any(p.endswith('.faces.v') for lvl, p, _ in rep.items if lvl == 'must') != want:
            bad.append('faces.v %s in a %s' % ('not found' if want else 'found', 'round trip' if facts else 'run'))
    return bad


def main():
    failed = False
    for name, fn in (('tables', check_tables), ('rule references', check_rules),
                     ('expected files', check_expected), ('approvals', check_approvals),
                     ('node facts', check_node_facts), ('stability', check_stability),
                     ('tangents, faces', check_tangents_and_faces), ('ksy', check_ksy)):
        bad = fn()
        print('%-16s %s' % (name, 'ok' if not bad else 'FAIL'))
        for b in bad[:20]:
            print('    ' + b)
        failed |= bool(bad)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
