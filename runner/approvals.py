# SPDX-License-Identifier: CC0-1.0
"""Approved differences for `mdlconf.py roundtrip --approved FILE` and
`mdlconf.py approve` (standard library only).

An approvals file (runner/approvals/*.json) lists differences a project has
agreed to live with. Each entry names one of the checks below; a MUST
finding is approved only when that check's condition holds on the mesh or
node the finding is about, from the facts the round trip records
(mdlconf.mesh_facts and the name facts of compare_nodes). Approved findings
are moved from `must` to `approved` with the entry's id, never dropped. A
model whose MUST findings are all approved and whose compile is stable has
the status `pass-approved`.

The checks, per mesh (all of a mesh's MUST findings are approved, or none):

- every compiled triangle is paired, in order, with one of the original's,
  and every original triangle the compile does not draw has zero area;
- face materials, skin weights and dangly constraints match per paired
  corner, and every corner attribute does (position, UV0-3, normal,
  tangent, handedness, colour), except a tangent or handedness at a corner
  whose original tangent is NaN, infinite or zero;
- the streams are the same, or the compile added tangents (and
  handedness) where the original had none, or the original's slot-3 stream
  was a 1.69 bump-map stream (texture animation slots set) and the compile
  has none.

Then each finding gets the check that explains it:

- `vertex-layout`: vertex_count, when the compiled count is the number of
  distinct vertices the original draws by the game's merge key
  (MDL-MESH-010/011; for an AABB walkmesh, MDL-MESH-012, the corner match
  alone);
- `dropped-zero-area-faces`: triangles and face_count when the difference is
  exactly the dropped zero-area triangles (MDL-MESH-020), and a per-corner
  finding that the paired comparison does not show (the runner compares
  corners in order, so a dropped face shifts the rest);
- `nan-tangent-fill`: tangent and handedness when every paired corner that
  differs had a NaN, infinite or zero tangent (MDL-BIN-048); and the
  vertex_count of such a mesh;
- `tangents-baked`: the vertex_count of a mesh whose compile added tangents
  the original did not have (MDL-MESH-041/042/043, tangent clones);
- `water-texanim-169`: the vertex_count of a mesh whose original holds a
  1.69 water bump-map stream in the texture animation slots (MDL-BIN-048);
- `name-cut-31`: a node's name or parent cut from 32 to 31 characters
  (MDL-BIN-007) when no other node of the original has the cut name, and a
  tree finding whose only difference is such names.
"""
import hashlib
import json
import re

FORMAT = 'mdlconf-approvals/1'

CHECKS = ('vertex-layout', 'dropped-zero-area-faces', 'nan-tangent-fill', 'tangents-baked',
          'water-texanim-169', 'name-cut-31')
CORNER = ('position', 'uv0', 'uv1', 'uv2', 'uv3', 'normal', 'tangent', 'handedness', 'color')
MESH_PATH = re.compile(r'^(.*\.mesh)\.([A-Za-z0-9_.]+)$')


class ApprovalsError(ValueError):
    pass


def load(path):
    """The approvals file: {check: entry}, with the file's name and digest."""
    raw = open(path, 'rb').read()
    try:
        doc = json.loads(raw.decode('utf-8'))
    except ValueError as e:
        raise ApprovalsError('%s: not JSON: %s' % (path, e))
    if doc.get('format') != FORMAT:
        raise ApprovalsError('%s: format is %r, expected %r' % (path, doc.get('format'), FORMAT))
    entries, ids = {}, set()
    for i, e in enumerate(doc.get('approvals', [])):
        for k in ('id', 'check', 'description', 'rules', 'condition'):
            if not e.get(k):
                raise ApprovalsError('%s: approval %d has no %r' % (path, i, k))
        if e['check'] not in CHECKS:
            raise ApprovalsError('%s: approval %r: unknown check %r (known: %s)'
                                 % (path, e['id'], e['check'], ', '.join(CHECKS)))
        if e['id'] in ids or e['check'] in entries:
            raise ApprovalsError('%s: approval %r: id or check used twice' % (path, e['id']))
        ids.add(e['id'])
        entries[e['check']] = e
    return {'file': path, 'name': doc.get('name', ''), 'sha256': hashlib.sha256(raw).hexdigest(),
            'entries': entries}


def mesh_checks(leaves, f):
    """{leaf: check or None} for one mesh's compile findings, and the checks
    the mesh relies on."""
    none = ({leaf: None for leaf in leaves}, set())
    if not f:
        return none
    n_orig, n_comp = f['triangles']
    if f['extra'] or f['dropped_nonzero'] or f['paired'] != n_comp or f['paired'] + f['dropped'] != n_orig:
        return none
    if f.get('material_differ') != 0:  # differs, or could not be compared
        return none
    if f.get('skin', 'same') != 'same' or f.get('constraints', 'same') != 'same':
        return none
    differ, bad = f['differ'], f['differ_bad_tangent']
    if any(n - (bad.get(k, 0) if k in ('tangent', 'handedness') else 0) for k, n in differ.items()):
        return none
    so, sc = set(f['streams_only_original']), set(f['streams_only_compiled'])
    baked = water = False
    if so or sc:
        if not so and 'tangent' in sc and sc <= {'tangent', 'handedness'}:
            baked = True
        elif (not sc and 'bumpmap_slot3' in so and so <= {'bumpmap_slot3', 'bumpmap_slot5'}
              and f.get('texanim_slots') and not f.get('texanim_slots_compiled')):
            water = True
        else:
            return none
    nanfill = any(bad.values())
    faces = f.get('faces')
    out, needs = {}, set()
    for leaf in leaves:
        c = None
        if leaf in CORNER:
            if differ.get(leaf):
                c = 'nan-tangent-fill'  # only bad-tangent corners differ (checked above)
            elif f['dropped']:
                c = 'dropped-zero-area-faces'  # the in-order comparison shifted by a dropped face
        elif leaf == 'triangles':
            c = 'dropped-zero-area-faces' if f['dropped'] and f['dropped'] == n_orig - n_comp else None
        elif leaf == 'face_count':
            if f['dropped'] and faces and faces[0] - faces[1] == f['dropped']:
                c = 'dropped-zero-area-faces'
        elif leaf == 'vertex_count':
            if baked:
                c = 'tangents-baked'
            elif water:
                c = 'water-texanim-169'
            elif nanfill:
                c = 'nan-tangent-fill'
            elif f.get('aabb') or f['vertices'][1] == f['distinct']:
                c = 'vertex-layout'
        out[leaf] = c
    if f['dropped']:
        needs.add('dropped-zero-area-faces')
    if nanfill:
        needs.add('nan-tangent-fill')
    if baked:
        needs.add('tangents-baked')
    if water:
        needs.add('water-texanim-169')
    return out, needs


def node_check(test, path, facts):
    f = facts.get('%s %s' % (test, path))
    if not f or not f.get('unique'):
        return None
    if path.endswith('.tree') and f.get('names_cut_only'):
        return 'name-cut-31'
    if (path.endswith('.name') or path.endswith('.parent')) and f.get('name_cut'):
        return 'name-cut-31'
    return None


def apply(res, approvals):
    """Re-score one roundtrip result in place under the approvals (None: no
    approvals, the plain status). Findings approved earlier are scored again."""
    if res.get('status') == 'error':
        return res
    findings = list(res.get('must', [])) + [x[:3] for x in res.get('approved', [])]
    stable = res.get('stable')
    if stable is None and res.get('status') in ('pass', 'unstable'):
        stable = res['status'] == 'pass'  # made before 'stable' was recorded
    facts = res.get('facts', {})
    entries = approvals['entries'] if approvals else {}
    meshes = {}
    for i, (test, path, msg) in enumerate(findings):
        m = MESH_PATH.match(path)
        if test == 'compile' and m:
            meshes.setdefault(m.group(1), []).append((i, m.group(2)))
    verdict = [None] * len(findings)
    if entries:
        for mesh, items in meshes.items():
            leaves, needs = mesh_checks([leaf for _, leaf in items], facts.get('compile ' + mesh))
            if any(c is None or c not in entries for c in leaves.values()) or not needs <= set(entries):
                continue  # the whole mesh stays failed
            for i, leaf in items:
                verdict[i] = leaves[leaf]
        for i, (test, path, msg) in enumerate(findings):
            if verdict[i] is None and not MESH_PATH.match(path):
                c = node_check(test, path, facts)
                verdict[i] = c if c in entries else None
    res['must'] = [x for x, c in zip(findings, verdict) if c is None]
    approved = [list(x) + [entries[c]['id']] for x, c in zip(findings, verdict) if c is not None]
    if approved:
        res['approved'] = approved
    else:
        res.pop('approved', None)
    if res['must']:
        res['status'] = 'fail'
    elif stable is None:
        res['status'] = 'fail'
        res['reason'] = 'every MUST finding is approved, but the result does not say whether the compile is stable'
    elif not stable:
        res['status'] = 'unstable'
        res['reason'] = 'decompiling and compiling the compiled model again gives different bytes'
    else:
        res['status'] = 'pass-approved' if approved else 'pass'
    return res


def summary(results, approvals):
    """{id: {'models': n, 'findings': n}} over the results, in file order."""
    out = {e['id']: {'models': 0, 'findings': 0} for e in approvals['entries'].values()}
    for r in results:
        seen = set()
        for x in r.get('approved', []):
            c = out.setdefault(x[3], {'models': 0, 'findings': 0})
            c['findings'] += 1
            if x[3] not in seen:
                seen.add(x[3])
                c['models'] += 1
    return out
