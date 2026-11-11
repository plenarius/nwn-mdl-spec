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
  (MDL-BIN-007) when no node of the original with another name has the cut
  name (a name it already used twice is no new collision, cut_names), and
  a tree finding whose only difference is such names.

Per node, from the facts the comparison records:

- `emitter-texture-junk`: an emitter's texture (decompile and compile) when
  its chunk name is not empty and the original's texture field holds a byte
  outside 0x20-0x7e before its first NUL (mdlconf.emitter_facts);
- `aabb-stale-tree`: an aabb node's entry count, in the compile, when the
  original's tree has more leaves than its mesh has faces (MDL-MESH-024),
  and the compile's tree names each of its faces once, with each leaf's box
  its face's and each inner box its children's union, and the face count is
  the same (nodefacts.aabb_stale_facts).

Per model, from the facts of runner/nodefacts.py (recorded as `compile
model.nodes` when the compile has a node number, tree or count finding).
Names are cut to 31 characters (MDL-BIN-007), and nodes that share a name
are told apart by their parent and their order among its children of that
name (nodefacts.unique_labels; with a supermodel, its paths are walked by
name). A shared name that is a parent is told apart only in a model with no
supermodel and no animations, where a part number binds nothing: a child's
parent is the latest node of that name before it (fact
`duplicate_parents`); elsewhere such a model has no "unique names", which
below means names told apart this way:

- `renumbered`: node and animation node numbers (`nodes[X].number`,
  `animations[A].nodes[X].number`) when, with unique node names, the same
  nodes and parents and a supermodel found where the model names one: the
  compile's numbers are what MDL-NODE-010/020 give the ASCII's declaration
  order; no declaration order gives the original's numbers and stored tree
  together (nodefacts.reachable); every animation node is numbered by
  MDL-NODE-040 against its own model's geometry in both (by name: of
  geometry siblings sharing a name, the first stored one's number); and no
  tree, name, parent or missing-node finding is left unapproved;
- `supermodel-count`: model.node_count when the compile's count is the
  supermodel's header count + the model's nodes + 1 (MDL-NODE-030) with the
  supermodel found, the node count is the same in both, and the original's
  count is its node count (compiled without the supermodel) or more than it;
- `anim-header-count`: animations[A].node_count when the original's header
  count is not the size of its animation tree, the compile's is (MDL-NODE-042),
  and both trees have the same nodes;
- `tree-sorted`: nodes.tree when, with unique names and the same nodes and
  parents, every node whose children differ has as compiled children its
  original children with the transparency sort applied (MDL-NODE-012,
  nodefacts.engine_sort; parent by parent, so that a parent left as stored
  is not re-sorted), and held them out of sort order in the original
  (no ASCII gives them; the fact `ties_moved` counts those where std::sort
  also moves equal children, past 16, and is reported, not a condition);
- `aabb-plane-tie`: aabb[j].plane when the aabb trees have the same boxes and
  faces and every differing plane, in the original and in the compile, is at
  a tie of MDL-MESH-052's axis rule (nodefacts.aabb_facts).

Per model, from the facts of mdlconf.render_list_facts (recorded as
`compile model.render_lists` when the original has merged render lists,
MDL-BIN-053, and the round trip has a render, triangles, vertex_count,
face_count or shadow finding):

- `merged-render-lists` (merged_render_lists, merged_node_check): when the
  whole model draws as the original does, compared in world space (every
  drawn triangle paired one to one, apart from original triangles of zero
  area, with the same drawing state, animation and corner attributes; bad
  original tangents and baked ones needing nan-tangent-fill and
  tangents-baked), and casts its shadows as before or from what it now
  draws (a restored donor's shadow may follow the alpha it took; a folded
  donor's faces may cast no shadow, or cast it from a receiver where the
  receiver draws them, as many as lost); no node name used twice that is a
  parent or animated; every supermodel found, no skin or animmesh receiver;
  every node that now draws another's triangles a render-0 mesh without an
  index list in the original, drawing a receiver's. Then, in the decompile
  and the compile: a restored donor's render, triangles, vertex_count,
  normal, tangent, handedness and drawing settings (DONOR_SETTINGS) and its
  alpha and selfillumcolor controllers (its own values were never drawn;
  the copies' are what the condition compares); a folded donor's render,
  shadow and beaming; a receiver's triangles and vertex_count, and, when it
  draws folded copies as faces, its face_count and per-corner findings; and
  nodes.tree when restored donors re-sorted by the transparencyhint they
  took are the only difference. A restored donor's other findings are
  checked with its normal, tangent and handedness left out of its facts; a
  receiver's mesh facts pair the compile with its own faces only (the start
  of its index list). A decompile finding of these meshes that is not one
  of those leaves the mesh failed.

And one per model, about the second compile rather than a finding: a model
whose MUST findings are all approved and whose second compile differs from
the first, where every difference is of a kind an entry approves
(mdlconf.explain_unstable, recorded as `unstable_explained`, {kind: count};
results made before it have only `unstable_adjacency_only`):

- `unstable-adjacency-only` (adjacency): face records' adjacency fields
  (MDL-BIN-044, MDL-MESH-022), the face records at the same offsets;
- `signed-zero` (signed_zero): a float field 0.0 in one and -0.0 in the other;
- `bounds-ulp` (bounds_ulp): the model's bounding box, by at most 1 ulp per
  component;
- `dead-face-vertices` (dead_vertices): vertices no face of the first compile
  uses, each at a corner of a zero-area triangle of the original, which the
  second compile does not have, and vertices at such corners that the second
  compile puts where the kept faces first use them (the first compile kept
  them where the dropped face used them first); every other vertex keeps its
  order, the meshes' box, average and radius following from their vertices
  (a mesh whose every face had zero area has no vertices in the second
  compile and the compiler's empty box; the model's box stays exact).
  Meshes are found in the original by their names cut to 31 characters.

Byte-level kinds (the first three) need the two files to be the same length
and byte for byte the same apart from them. The model passes as
`pass-approved`, with an approved finding `stability binary2` per kind naming
its entry; any other difference leaves it `unstable`.
"""
import hashlib
import json
import re

FORMAT = 'mdlconf-approvals/1'

CHECKS = ('vertex-layout', 'dropped-zero-area-faces', 'nan-tangent-fill', 'tangents-baked',
          'water-texanim-169', 'name-cut-31', 'renumbered', 'supermodel-count', 'anim-header-count',
          'tree-sorted', 'aabb-plane-tie', 'unstable-adjacency-only', 'signed-zero', 'bounds-ulp',
          'dead-face-vertices', 'merged-render-lists', 'emitter-texture-junk', 'aabb-stale-tree')
STABILITY = ('stability', 'binary2')  # the approved finding of an approved instability
UNSTABLE = {  # kind in unstable_explained: (check, message)
    'adjacency': ('unstable-adjacency-only', 'the adjacency of %d faces'),
    'signed_zero': ('signed-zero', '%d float(s) 0.0 in one compile and -0.0 in the other'),
    'bounds_ulp': ('bounds-ulp', '%d model bounding box float(s), by 1 ulp'),
    'dead_vertices': ('dead-face-vertices', '%d vertices zero-area faces of the original used, left unused '
                                            'or first used by them'),
}
NUMBER = re.compile(r'^(nodes|animations\[[^\]]*\]\.nodes)\[[^\]]*\]\.number$')
ANIM_COUNT = re.compile(r'^animations\[(.*)\]\.node_count$')
PLANE = re.compile(r'^(nodes\[[^\]]*\])\.aabb\[\d+\]\.plane$')
EMITTER_TEXTURE = re.compile(r'^(nodes\[[^\]]*\]\.emitter)\.texture$')
AABB_COUNT = re.compile(r'^(nodes\[[^\]]*\])\.aabb$')
TREE_BLOCKERS = ('.tree', '.parent', '.name')
CORNER = ('position', 'uv0', 'uv1', 'uv2', 'uv3', 'normal', 'tangent', 'handedness', 'color')
MESH_PATH = re.compile(r'^(.*\.mesh)\.([A-Za-z0-9_.]+)$')
MESH_NODE = re.compile(r'^nodes\[([^\]]*)\]\.mesh$')
MERGE_LEAVES = ('render', 'triangles', 'vertex_count')
# A donor's own normals and tangents were never drawn (render 0); what the
# game drew is the receiver's copy, which the world-space facts compare.
DONOR_CORNERS = ('normal', 'tangent', 'handedness')
# The drawing settings a restored donor takes from its receiver (cleanmodels
# #141): never drawn with its own; compared in world space as drawn.
DONOR_SETTINGS = ('diffuse', 'ambient', 'specular', 'shininess', 'transparencyhint', 'renderhint', 'tilefade',
                  'rotatetexture', 'textures', 'beaming')
# A folded donor: render 0 kept, its shadow cast from the receiver's copies
FOLDED_LEAVES = ('render', 'shadow', 'beaming')
DONOR_CONTROLLER = re.compile(r'^nodes\[([^\]]*)\]\.controllers\[(alpha|selfillumcolor)\](\.keys\[\d+\]\.\w+)?$')


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
            # a receiver's count includes the copies: merged-render-lists
            c = ('dropped-zero-area-faces' if f['dropped'] and f['dropped'] == n_orig - n_comp
                 and not f.get('merged_list') else None)
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


def merged_render_lists(rf):
    """The meshes merged-render-lists covers when a model's merged render
    lists draw as in the original and cast shadows as in the original or
    from what is drawn (`compile model.render_lists`,
    mdlconf.render_list_facts), else None: {'receivers', 'donors' (restored:
    they now draw triangles a receiver drew), 'folded' (donor candidates
    still at render 0 in the compile, their copies drawn by a receiver),
    'folding' (receivers that draw more triangles than their own faces in
    the compile), 'needs'}, as node labels (mdlconf.node_labels: lower-case
    names, #k for a name's k-th node).

    Drawn triangles must pair one to one with nothing else different. Shadow
    faces must pair the same, with one exception: a folded donor's faces may
    cast no shadow any more, or cast it from the receiver, with the
    receiver's state, where the receiver now draws them (extra shadow faces
    of receivers, every one on a triangle the original draws)."""
    if not rf or rf.get('error') or not rf.get('receivers') or rf.get('ambiguous', True):
        return None
    if rf.get('supermodel_missing') or rf.get('receivers_deformed'):
        return None
    d, s = rf['draw'], rf['shadow']
    if any(d['unreadable']) or d['lost_nonzero'] or d['extra'] or d['state_differ'] or d['moving_differ']:
        return None
    if d['corner_differ']:
        return None
    rec, cand = set(rf['receivers']), set(rf['donor_candidates'])
    moved = d['moved']
    if any(n not in cand or not set(src) <= rec for n, src in moved.items()):
        return None
    comp = rf.get('donors_compiled')
    folded = {k for k, v in (comp or {}).items() if not v[0]} if comp is not None else set()
    if any(s['unreadable']):
        return None
    # A restored donor's shadow follows the alpha it took from its receiver
    # (GetProjectsShadows compares the part's alpha with the cut-off,
    # MDL-MESH-067); nothing else of a shadow may change on the same node.
    if 'same_node_differ_by' in s:
        if any(n not in moved or set(by) - {'alpha'} for n, by in s['same_node_differ_by'].items()):
            return None
    elif s.get('same_node_differ', s['state_differ'] or s['moving_differ']):
        return None
    if comp is None:  # facts made before folding was known: no shadow may change
        if s['lost_nonzero'] or s['extra'] or s['state_differ'] or s['moving_differ']:
            return None
    else:
        if any(n not in rec or not set(src) <= folded for n, src in s['moved'].items()):
            return None
        if not set(s.get('lost_nodes', {})) <= folded:
            return None
        # replaced, not added: as many new faces as the folded donors lost
        if s['extra'] and (not set(s.get('extra_nodes', {})) <= rec or s.get('extra_on_drawn') != s['extra']
                           or s['extra'] != s['extra_nonzero']
                           or s['extra'] != sum(s.get('lost_nodes', {}).values())):
            return None
    tri = rf.get('receiver_triangles') or {}
    folding = {k for k, (own, _, got) in tri.items() if got > own}
    needs = {'merged-render-lists'}
    if d['bad_tangent']:
        needs.add('nan-tangent-fill')
    if d['tangent_baked']:
        needs.add('tangents-baked')
    if d['lost'] or s['lost'] > s.get('lost_nonzero', 0):
        needs.add('dropped-zero-area-faces')
    return {'receivers': rec, 'donors': set(moved), 'folded': folded & cand, 'folding': folding & rec,
            'needs': needs}


def merged_node_check(path, mr, mf):
    """merged-render-lists on a node finding: a restored donor's alpha or
    selfillumcolor controller (it takes the receiver's, which drew its
    copies), and a tree whose only difference is restored donors re-sorted
    by the transparencyhint they took (nodefacts.model_facts:
    `hint_changed`, `declared_resorted`)."""
    m = DONOR_CONTROLLER.match(path)
    if m and m.group(1).lower() in mr['donors']:
        return 'merged-render-lists'
    if path == 'nodes.tree':
        t = mf.get('tree') or {}
        if mf.get('unique') and mf.get('same_nodes') and t.get('declared_resorted') and \
                t.get('hint_changed') and set(t['hint_changed']) <= mr['donors']:
            return 'merged-render-lists'
    return None


def renumbered(mf):
    """The model facts allow approving node numbers (`renumbered`)."""
    return bool(mf.get('unique') and mf.get('same_nodes') and mf.get('numbers_by_rule')
                and mf.get('reachable') is False and mf.get('anim_mismatches') == [0, 0]
                and (not mf.get('supermodel') or mf.get('supermodel_count') is not None))


def supermodel_count(mf):
    oc, cc, no, nc = (mf.get('node_count') or [None] * 4)
    sc = mf.get('supermodel_count')
    return bool(mf.get('supermodel') and isinstance(sc, int) and isinstance(oc, int) and no == nc
                and cc == sc + nc + 1 and (oc == no or oc > no))


def anim_header_count(mf, anim):
    x = (mf.get('animations') or {}).get(anim.lower())
    if not x:
        return False
    oh, ch, on, cn = x['node_count']
    return oh != on and ch == cn and on == cn and x.get('same_names') is True


def tree_sorted(mf):
    t = mf.get('tree') or {}
    n = t.get('differing_parents', 0)
    # per parent where the facts have it; results made before compare the
    # whole tree resorted
    resorted = t['differing_resorted'] == n if 'differing_resorted' in t else t.get('resorted_equals_compile')
    return bool(mf.get('unique') and mf.get('same_nodes') and resorted
                and n > 0 and t.get('differing_unsorted') == n)


def node_check(test, path, facts):
    m = EMITTER_TEXTURE.match(path)
    if m:
        e = facts.get('%s %s' % (test, m.group(1))) or {}
        return 'emitter-texture-junk' if e.get('chunkname') and e.get('texture_junk') else None
    f = facts.get('%s %s' % (test, path))
    if f and f.get('unique'):
        if path.endswith('.tree') and f.get('names_cut_only'):
            return 'name-cut-31'
        if (path.endswith('.name') or path.endswith('.parent')) and f.get('name_cut'):
            return 'name-cut-31'
    if test != 'compile':
        return None
    mf = facts.get('compile model.nodes') or {}
    if path == 'nodes.tree':
        return 'tree-sorted' if tree_sorted(mf) else None
    if NUMBER.match(path):
        return 'renumbered' if renumbered(mf) else None
    if path == 'model.node_count':
        return 'supermodel-count' if supermodel_count(mf) else None
    m = ANIM_COUNT.match(path)
    if m:
        return 'anim-header-count' if anim_header_count(mf, m.group(1)) else None
    m = AABB_COUNT.match(path)
    if m:
        a = facts.get('compile %s.aabb' % m.group(1)) or {}
        lv, fc = a.get('leaves') or [0, 0], a.get('faces') or [0, 0]
        if lv[0] > fc[0] and a.get('complete') and a.get('boxes_fit') and fc[0] == fc[1]:
            return 'aabb-stale-tree'
        return None
    m = PLANE.match(path)
    if m:
        a = facts.get('compile %s.aabb' % m.group(1)) or {}
        if a.get('boxes_same') and a.get('planes_differ', 0) > 0 and a.get('ties') == a['planes_differ']:
            return 'aabb-plane-tie'
    return None


def apply(res, approvals):
    """Re-score one roundtrip result in place under the approvals (None: no
    approvals, the plain status). Findings approved earlier are scored again."""
    if res.get('status') == 'error':
        return res
    findings = list(res.get('must', [])) + [x[:3] for x in res.get('approved', [])
                                            if tuple(x[:2]) != STABILITY]
    stable = res.get('stable')
    if stable is None and res.get('status') in ('pass', 'unstable'):
        stable = res['status'] == 'pass'  # made before 'stable' was recorded
    facts = res.get('facts', {})
    entries = approvals['entries'] if approvals else {}
    merged = merged_render_lists(facts.get('compile model.render_lists')) if entries else None
    mr = merged or {'receivers': set(), 'donors': set(), 'folded': set(), 'folding': set(), 'needs': set()}

    def label(mesh):
        m = MESH_NODE.match(mesh)
        return m.group(1).lower() if m else None

    def involved(mesh):
        return label(mesh) in mr['receivers'] | mr['donors'] | mr['folded']

    def donor(mesh):
        return label(mesh) in mr['donors']

    def merge_leaf(mesh, leaf):
        # the findings merged-render-lists covers on this mesh
        n = label(mesh)
        if n in mr['donors']:
            # restored: its own values were never drawn; what it draws now
            # is what its copies were drawn with (compared in world space)
            return leaf in MERGE_LEAVES or leaf in DONOR_CORNERS or leaf in DONOR_SETTINGS
        if n in mr['folded']:
            return leaf in FOLDED_LEAVES
        if n in mr['folding']:
            # the folded copies are its faces now, after its own: the
            # in-order comparison of its corners shifts
            return leaf in MERGE_LEAVES or leaf == 'face_count' or leaf in CORNER
        return leaf in ('triangles', 'vertex_count') and n in mr['receivers']

    def mesh_facts(mesh):
        # a donor's facts without the corner attributes the world-space
        # comparison has already found the same where they were drawn
        f = facts.get('compile ' + mesh)
        if f and donor(mesh):
            f = dict(f, differ={k: n for k, n in f['differ'].items() if k not in DONOR_CORNERS},
                     differ_bad_tangent={k: n for k, n in f['differ_bad_tangent'].items()
                                         if k not in DONOR_CORNERS})
        return f

    meshes = {}
    for i, (test, path, msg) in enumerate(findings):
        m = MESH_PATH.match(path)
        # decompile findings only of the meshes in a merged render list:
        # those are approved together with the mesh's compile findings
        if m and (test == 'compile' or involved(m.group(1))):
            meshes.setdefault(m.group(1), []).append((i, test, m.group(2)))
    verdict = [None] * len(findings)
    if entries:
        for mesh, items in meshes.items():
            merge = {i for i, _, leaf in items if merge_leaf(mesh, leaf)}
            leaves, needs = mesh_checks([leaf for i, t, leaf in items if i not in merge and t == 'compile'],
                                        mesh_facts(mesh))
            if merge:
                needs = needs | mr['needs']
            v = {i: 'merged-render-lists' if i in merge else leaves[leaf] if t == 'compile' else None
                 for i, t, leaf in items}
            if any(c is None or c not in entries for c in v.values()) or not needs <= set(entries):
                continue  # the whole mesh stays failed
            for i, c in v.items():
                verdict[i] = c
        for i, (test, path, msg) in enumerate(findings):
            if verdict[i] is None and not MESH_PATH.match(path):
                c = node_check(test, path, facts)
                if c is None and merged:
                    c = merged_node_check(path, mr, facts.get('compile model.nodes') or {})
                verdict[i] = c if c in entries else None
        # Numbers are approved only on the same tree: none of the tree, name,
        # parent or missing-node findings may be left.
        if any(c is None and (path.endswith(TREE_BLOCKERS) or msg == 'missing')
               for (test, path, msg), c in zip(findings, verdict)):
            verdict = [None if c == 'renumbered' else c for c in verdict]
    res['must'] = [x for x, c in zip(findings, verdict) if c is None]
    approved = [list(x) + [entries[c]['id']] for x, c in zip(findings, verdict) if c is not None]
    res.pop('reason', None)
    why = res.get('unstable_explained')
    if not why and (res.get('unstable_adjacency_only') or 0) > 0:
        why = {'adjacency': res['unstable_adjacency_only']}  # recorded before unstable_explained
    if (not res['must'] and stable is False and why
            and all(k in UNSTABLE and UNSTABLE[k][0] in entries for k in why)):
        for k in sorted(why):
            check, msg = UNSTABLE[k]
            approved.append(list(STABILITY) + ['the second compile differs from the first in ' + msg % why[k],
                                               entries[check]['id']])
        stable = True
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


def stability_approved(res):
    """The ids of the entries a scored result's second compile passes by
    (empty when it is stable on its own)."""
    return {x[3] for x in res.get('approved', []) if tuple(x[:2]) == STABILITY}


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
