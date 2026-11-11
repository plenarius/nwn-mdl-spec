# SPDX-License-Identifier: CC0-1.0
"""Node numbers, node order and aabb planes, as the game's compiler makes
them: the facts the round trip records for the approvals of
runner/approvals.py (standard library only).

- MDL-NODE-010/013/020: part numbers from a declaration order, with or
  without a supermodel;
- MDL-NODE-011/012: the stored children order, with the transparency sort
  done by libstdc++'s std::sort (engine_sort);
- MDL-NODE-040: animation node numbers from the model's geometry;
- MDL-MESH-052: an aabb inner node's plane from its children's boxes.
"""

F_MESH = 0x20
MESH_TYPES = ('trimesh', 'danglymesh', 'skin', 'animmesh', 'aabb')
ROOT = ('<root>',)
TIE = 1e-4  # centre deltas this close count as a tie (MDL-MESH-052)


def signed32(h):
    h = int(h or 0)
    return h - (1 << 32) if h >= 1 << 31 else h


# ------------------------------------------------------------ the sort

def key_less(a, b):
    """The comparison at 0x453470 on (is a mesh, signed transparencyhint):
    every non-mesh before every mesh, meshes by ascending hint."""
    if not a[0]:
        return b[0]
    if not b[0]:
        return False
    return a[1] < b[1]


def needs_sort(keys):
    """MDL-NODE-012: a node's children are sorted when one is a mesh with
    transparencyhint > 0."""
    return any(m and h > 0 for m, h in keys)


def engine_sort(a, less):
    """libstdc++'s std::sort (introsort, then insertion sort), in place,
    step for step, so that equal elements end where the game's compiler
    puts them (spec/nodes.md, MDL-NODE-012)."""
    n = len(a)
    if n < 2:
        return
    depth, k = 0, n
    while k > 1:
        depth += 1
        k >>= 1
    _introsort_loop(a, 0, n, 2 * depth, less)
    if n > 16:
        _insertion_sort(a, 0, 16, less)
        for i in range(16, n):
            _linear_insert(a, i, less)
    else:
        _insertion_sort(a, 0, n, less)


def _introsort_loop(a, first, last, depth, less):
    while last - first > 16:
        if depth == 0:
            _heap_sort(a, first, last, less)
            return
        depth -= 1
        mid = first + (last - first) // 2
        _median_to_first(a, first, first + 1, mid, last - 1, less)
        cut = _partition(a, first + 1, last, first, less)
        _introsort_loop(a, cut, last, depth, less)
        last = cut


def _median_to_first(a, result, x, y, z, less):
    if less(a[x], a[y]):
        if less(a[y], a[z]):
            i = y
        elif less(a[x], a[z]):
            i = z
        else:
            i = x
    elif less(a[x], a[z]):
        i = x
    elif less(a[y], a[z]):
        i = z
    else:
        i = y
    a[result], a[i] = a[i], a[result]


def _partition(a, first, last, pivot, less):
    while True:
        while less(a[first], a[pivot]):
            first += 1
        last -= 1
        while less(a[pivot], a[last]):
            last -= 1
        if first >= last:
            return first
        a[first], a[last] = a[last], a[first]
        first += 1


def _insertion_sort(a, first, last, less):
    for i in range(first + 1, last):
        if less(a[i], a[first]):
            v = a[i]
            a[first + 1:i + 1] = a[first:i]
            a[first] = v
        else:
            _linear_insert(a, i, less)


def _linear_insert(a, i, less):
    v = a[i]
    j = i - 1
    while less(v, a[j]):
        a[i] = a[j]
        i = j
        j -= 1
    a[i] = v


def _heap_sort(a, first, last, less):
    n = last - first
    if n >= 2:
        parent = (n - 2) // 2
        while True:
            _adjust_heap(a, first, parent, n, a[first + parent], less)
            if parent == 0:
                break
            parent -= 1
    while last - first > 1:
        last -= 1
        v = a[last]
        a[last] = a[first]
        _adjust_heap(a, first, 0, last - first, v, less)


def _adjust_heap(a, first, hole, n, v, less):
    top = second = hole
    while second < (n - 1) // 2:
        second = 2 * (second + 1)
        if less(a[first + second], a[first + second - 1]):
            second -= 1
        a[first + hole] = a[first + second]
        hole = second
    if n % 2 == 0 and second == (n - 2) // 2:
        second = 2 * (second + 1)
        a[first + hole] = a[first + second - 1]
        hole = second - 1
    parent = (hole - 1) // 2
    while hole > top and less(a[first + parent], v):
        a[first + hole] = a[first + parent]
        hole = parent
        parent = (hole - 1) // 2
    a[first + hole] = v


def sort_children(kids, key):
    """The children as the game's compiler stores them (MDL-NODE-011/012)."""
    out = list(kids)
    if needs_sort([key[c] for c in out]):
        engine_sort(out, lambda x, y: key_less(key[x], key[y]))
    return out


def in_sort_order(kids, key):
    """Whether no child is ordered after one the comparison puts after it."""
    return not any(key_less(key[kids[i + 1]], key[kids[i]]) for i in range(len(kids) - 1))


def stored_order(root, kids_of, key):
    """The depth-first stored order the game's compiler writes for these
    children lists (in declaration order)."""
    out, seen, stack = [], set(), [root]
    while stack:
        n = stack.pop()
        if n is None or n in seen:
            continue
        seen.add(n)
        out.append(n)
        stack.extend(reversed(sort_children(kids_of.get(n, []), key)))
    return out


# ------------------------------------------------------------ trees

class Geo:
    """A geometry tree from a view's nodes (binary: stored depth-first),
    names lower-cased and cut to 31 characters as the game's compiler stores
    them (MDL-BIN-007). `unique` is False when two nodes share a name
    (model_facts gives such nodes labels first, unique_labels)."""

    def __init__(self, nodes):
        self.names = [n['name'].lower()[:31] for n in nodes]
        self.unique = len(set(self.names)) == len(self.names)
        self.parent, self.kids, self.num, self.key = {}, {}, {}, {}
        for n in nodes:
            nm = n['name'].lower()[:31]
            p = n['parent'].lower()[:31] if n.get('parent') else None
            mesh = bool(n.get('flags', 0) & F_MESH)
            self.parent.setdefault(nm, p)
            self.num.setdefault(nm, n.get('number'))
            self.key.setdefault(nm, (mesh, signed32(n.get('mesh', {}).get('transparencyhint', 0)) if mesh else 0))
            if p is not None:
                self.kids.setdefault(p, []).append(nm)
        self.root = self.names[0] if self.names else None
        self.path = {}
        stack = [(self.root, ROOT)] if self.root is not None else []
        while stack:
            n, path = stack.pop()
            if n in self.path:
                continue
            self.path[n] = path
            stack.extend((c, path + (c,)) for c in self.kids.get(n, []))
        self.bypath = {p: n for n, p in self.path.items()}


class Super:
    """A supermodel's part numbers by path from its root (MDL-NODE-020) and
    its header node count (MDL-NODE-030)."""

    def __init__(self, count, bypath):
        self.count, self.bypath = count, bypath

    @classmethod
    def from_binary(cls, view):
        """From a binary's view: a node's parent is the latest node of that
        name before it in the stored (depth-first) order."""
        bypath, latest = {}, {}
        for i, n in enumerate(view['nodes']):
            nm = n['name'].lower()[:31]
            if i == 0:
                path = ROOT
            else:
                pp = latest.get((n.get('parent') or '').lower()[:31])
                if pp is None:
                    continue
                path = pp + (nm,)
            bypath.setdefault(path, n['number'])
            latest[nm] = path
        return cls(view['model']['node_count'], bypath)

    @classmethod
    def from_ascii(cls, text, sup):
        """From an ASCII model, numbered as the game's compiler would number
        it (MDL-NODE-010, or MDL-NODE-020 against its own supermodel `sup`)."""
        decl = ascii_declarations(text)
        nums = ref_numbers([(n, p) for n, p, _ in decl], sup)
        parent = {n: p for n, p, _ in decl}
        bypath, path = {}, {}
        for n, p, _ in decl:
            if p is None:
                path[n] = ROOT
        changed = True
        while changed:
            changed = False
            for n, p, _ in decl:
                if n not in path and p and p in path:
                    path[n] = path[p] + (n,)
                    changed = True
        for n, pt in path.items():
            bypath.setdefault(pt, nums[n])
        del parent
        count = len(decl) if sup is None else sup.count + len(decl) + 1
        return cls(count, bypath)


def ascii_supermodel(text):
    """The supermodel an ASCII model names ('' for none)."""
    for ln in text.splitlines():
        w = ln.split()
        if len(w) > 2 and w[0].lower() == 'setsupermodel':
            return '' if w[2].upper() == 'NULL' else w[2].lower()
        if w and w[0].lower() == 'beginmodelgeom':
            break
    return ''


def ascii_declarations(text):
    """The geometry nodes of an ASCII model in declaration order: a list of
    (name, parent, (is a mesh, transparencyhint)), names lower-cased and
    cut to 31 characters (MDL-BIN-007); the
    parent is None for NULL and False when the node has no parent line. The
    structural words are matched case-sensitively, as the engine does
    (spec/ascii.md)."""
    out, cur, geom = [], None, False
    for ln in text.splitlines():
        w = ln.split()
        if not w:
            continue
        low = w[0].lower()
        if not geom:
            geom = low == 'beginmodelgeom'
            continue
        if low == 'endmodelgeom':
            break
        if w[0] == 'node' and len(w) > 2:
            cur = [w[2].lower()[:31], False, w[1].lower() in MESH_TYPES, 0]
            out.append(cur)
        elif w[0] == 'endnode':
            cur = None
        elif cur is not None and w[0] == 'parent' and len(w) > 1:
            cur[1] = None if w[1].upper() == 'NULL' else w[1].lower()[:31]
        elif cur is not None and low == 'transparencyhint' and len(w) > 1:
            try:
                cur[3] = int(w[1])
            except ValueError:
                pass
    return [(n, p, (m, h if m else 0)) for n, p, m, h in out]


def ref_numbers(decl, sup):
    """{name: part number} the game's compiler gives a declaration order
    [(name, parent)] (MDL-NODE-010; with a supermodel MDL-NODE-020, walking
    on through supermodel nodes numbered -1)."""
    num, matched = {}, {}
    for i, (n, p) in enumerate(decl):
        if sup is None:
            num[n] = i
        elif p is None:
            matched[n] = ROOT
            num[n] = sup.bypath.get(ROOT, -1)
        elif p is not False and p in matched:
            path = matched[p] + (n,)
            if path in sup.bypath:
                matched[n] = path
                num[n] = sup.bypath[path]
            else:
                num[n] = -1
        else:
            num[n] = sup.count + 1 + i
    return num


def reachable(geo, sup):
    """Whether some declaration order makes the game's compiler give exactly
    this tree's part numbers and stored order. Generous where the spec
    leaves room (gaps in the numbers, MDL-NODE-013; a child declared before
    its parent), so that it never calls a reachable tree unreachable.

    A node is fixed when its number does not depend on the order (with a
    supermodel: its path is in the supermodel, or its parent's is) and free
    otherwise (its number gives its declaration index). Children of a node
    are all fixed or all free. Fixed children can be declared in any order,
    so their stored order is reachable when it is in sort order, or needs no
    sort (std::sort's result depends only on the comparisons, so any sorted
    order is the sort of some declaration order). Free children are declared
    in the order of their numbers, which must give the stored order."""
    offset = 0 if sup is None else sup.count + 1
    fixed, idx = {}, {}
    for n in geo.names:
        path = geo.path.get(n)
        if sup is not None and path is not None and (path in sup.bypath or path[:-1] in sup.bypath):
            fixed[n] = sup.bypath.get(path, -1)
        else:
            idx[n] = (geo.num[n] if isinstance(geo.num[n], int) else -1) - offset
    if any(geo.num[n] != v for n, v in fixed.items()):
        return False
    if any(i < 0 for i in idx.values()) or len(set(idx.values())) != len(idx):
        return False
    for p, kids in geo.kids.items():
        if all(c in fixed for c in kids):
            if needs_sort([geo.key[c] for c in kids]) and not in_sort_order(kids, geo.key):
                return False
        elif all(c in idx for c in kids):
            if sort_children(sorted(kids, key=lambda c: idx[c]), geo.key) != kids:
                return False
        else:
            return False  # not as the rule gives it
    return True


def anim_mismatches(view, geo):
    """How many animation nodes are not numbered as MDL-NODE-040 gives
    against this view's own geometry (a node the geometry lacks under a
    parent it lacks takes its position in the animation's stored list)."""
    bad = 0
    for a in view.get('animations', []):
        latest = {}
        for i, n in enumerate(a['nodes']):
            nm = n['name'].lower()[:31]
            if i == 0:
                path = ROOT
            else:
                pp = latest.get((n.get('parent') or '').lower()[:31])
                path = pp + (nm,) if pp is not None else None
            if path is not None:
                latest[nm] = path
            if path is not None and path in geo.bypath:
                want = geo.num[geo.bypath[path]]
            elif path is not None and path[:-1] in geo.bypath:
                want = -1
            else:
                want = i
            if n.get('number') != want:
                bad += 1
    return bad


# ------------------------------------------------------------ the facts

def node_paths(nodes):
    """Each node's path from the root: a tuple of (name, k), names
    lower-cased and cut to 31 characters as the game's compiler stores them
    (MDL-BIN-007), k the node's occurrence among its parent's children of
    that name. A node's parent is the latest node of its parent name before
    it (in stored depth-first order, or in declaration order, a parent comes
    before its children). A node whose parent is not found is placed under
    ('?', 1)."""
    latest, count, out = {}, {}, []
    for i, n in enumerate(nodes):
        nm = n['name'].lower()[:31]
        par = n.get('parent')
        par = par.lower()[:31] if par and par.upper() != 'NULL' else None
        if par is None:
            base = ()
        else:
            pi = latest.get(par)
            base = out[pi] if pi is not None else (('?', 1),)
        k = count[(base, nm)] = count.get((base, nm), 0) + 1
        out.append(base + ((nm, k),))
        latest[nm] = i
    return out


def _signature(n):
    """What tells apart siblings of one name: node type, the first keys of
    position and orientation, and a mesh's vertex count and first vertex."""
    def floats(v):
        try:
            return tuple(float(x) for x in v)
        except (TypeError, ValueError):
            return None

    def first(name):
        for c in n.get('controllers', []):
            if c.get('name') == name and c.get('keys'):
                return floats(c['keys'][0].get('v') or [])
        return None
    m = n.get('mesh') or {}
    pos = (m.get('vertices') or {}).get('position') or []
    return (n.get('flags'), first('position'), first('orientation'), m.get('vertex_count'),
            floats(pos[0]) if pos else None)


def _alike(a, b, level):
    """Two signatures alike: in everything (level 0), or in node type and
    transform only (level 1; an ASCII mesh numbers its vertices its own
    way), floats within 1e-4."""
    def near(x, y):
        if x is None or y is None:
            return x is y
        return len(x) == len(y) and all(abs(p - q) <= 1e-4 * max(1.0, abs(p), abs(q)) for p, q in zip(x, y))
    if a[0] != b[0] or not near(a[1], b[1]) or not near(a[2], b[2]):
        return False
    return level > 0 or (a[3] == b[3] and near(a[4], b[4]))


def pair_nodes(exp_nodes, act_nodes):
    """For each node of `exp_nodes`, the index of its node in `act_nodes`
    (None when there is none): paired by path (node_paths). Siblings that
    share a name (the transparency sort, or a decompiler, can put them in
    another order) pair first with one alike in everything _signature
    holds, then with one alike in node type and transform, then in order."""
    ep, ap = node_paths(exp_nodes), node_paths(act_nodes)
    egroups, agroups = {}, {}
    for i, pt in enumerate(ep):
        egroups.setdefault((pt[:-1], pt[-1][0]), []).append(i)
    for j, pt in enumerate(ap):
        agroups.setdefault((pt[:-1], pt[-1][0]), []).append(j)
    out = [None] * len(exp_nodes)
    for key, es in egroups.items():
        as_ = list(agroups.get(key, []))
        if len(es) > 1 or len(as_) > 1:
            for level in (0, 1):
                for i in es:
                    if out[i] is not None:
                        continue
                    sig = _signature(exp_nodes[i])
                    for j in as_:
                        if _alike(sig, _signature(act_nodes[j]), level):
                            out[i] = j
                            as_.remove(j)
                            break
        for i in es:
            if out[i] is None and as_:
                out[i] = as_.pop(0)
    return out


def unique_labels(trees):
    """Labels that tell apart nodes sharing a name, the same in every tree:
    `trees` is a list of [(name, parent)] lists (names lower-case, cut to 31
    characters). A name used once in each tree keeps it; a name used more
    often is labelled name#parent#k, k its occurrence among its parent's
    children of that name in the list's order. None when a shared name is a
    parent in any tree (which of them a child names is then a guess)."""
    dup = set()
    for t in trees:
        names = [n for n, _ in t]
        dup |= {n for n in names if names.count(n) > 1}
    if any(p in dup for t in trees for _, p in t):
        return None
    out = []
    for t in trees:
        count, labels = {}, []
        for n, p in t:
            if n in dup:
                k = count[(n, p)] = count.get((n, p), 0) + 1
                labels.append('%s#%s#%d' % (n, p, k))
            else:
                labels.append(n)
        out.append(labels)
    return out


def _relabelled(nodes, labels):
    return [dict(n, name=lab) for n, lab in zip(nodes, labels)]


def model_facts(exp, act, ascii_text, sup):
    """What the approvals need about a compile's node numbers and order:
    `exp` the original's view, `act` the compile's, `ascii_text` the ASCII it
    was compiled from, `sup` the supermodel the compile used (a Super; None
    when there is none or it was not found). Names are cut to 31 characters
    (MDL-BIN-007). Nodes that share a name are told apart by unique_labels
    (`duplicates`: how many names are shared); when a shared name is a
    parent, or the model has a supermodel, `unique` is False and nothing
    else is computed."""
    def pairs(nodes):
        return [(n['name'].lower()[:31], n['parent'].lower()[:31] if n.get('parent') else None) for n in nodes]
    decl = ascii_declarations(ascii_text)
    sname = (exp['model'].get('supermodel') or '').lower()
    sname = '' if sname == 'null' else sname
    trees = [pairs(exp['nodes']), pairs(act['nodes']), [(n, p or None) for n, p, _ in decl]]
    labels = unique_labels(trees)
    dups = len({n for t in trees for n, _ in t if [m for m, _ in t].count(n) > 1})
    if labels is not None and dups:
        # a shared name: the compile's nodes take their original's label
        # (pair_nodes), and, without a supermodel, the ASCII's declarations
        # the label of the compiled node their index numbers (MDL-NODE-010)
        pairing = pair_nodes(exp['nodes'], act['nodes'])
        alab = list(labels[1])
        for i, j in enumerate(pairing):
            if j is not None:
                alab[j] = labels[0][i]
        labels[1] = alab
        bynum = {n.get('number'): lab for n, lab in zip(act['nodes'], alab)}
        if not sname and sorted(bynum) == list(range(len(decl))) and len(bynum) == len(act['nodes']):
            labels[2] = [bynum[i] for i in range(len(decl))]
    if labels is not None and dups and sname:
        labels = None  # supermodel paths go by name
    f = {'unique': labels is not None,
         'supermodel': sname,
         'node_count': [exp['model'].get('node_count'), act['model'].get('node_count'),
                        len(exp['nodes']), len(act['nodes'])]}
    if dups:
        f['duplicates'] = dups
    anims = {}
    am = {x['name'].lower(): x for x in act.get('animations', [])}
    for ea in exp.get('animations', []):
        aa = am.get(ea['name'].lower())
        if aa is not None and ea.get('node_count') != aa.get('node_count'):
            anims[ea['name'].lower()] = {
                'node_count': [ea.get('node_count'), aa.get('node_count'), len(ea['nodes']), len(aa['nodes'])],
                'same_names': sorted(n['name'].lower()[:31] for n in ea['nodes'])
                == sorted(n['name'].lower()[:31] for n in aa['nodes'])}
    if anims:
        f['animations'] = anims
    if sname:
        f['supermodel_count'] = sup.count if sup is not None else None
    else:
        sup = None
    if labels is None:
        return f
    o, c = Geo(_relabelled(exp['nodes'], labels[0])), Geo(_relabelled(act['nodes'], labels[1]))
    decl = [(lab, p if p is not False else False, k) for lab, (_, p, k) in zip(labels[2], decl)]

    def anim_view(view):
        # animation nodes labelled as their geometry nodes are
        out = []
        for a in view.get('animations', []):
            al = unique_labels([pairs(a['nodes'])])
            out.append(dict(a, nodes=_relabelled(a['nodes'], al[0]) if al else a['nodes']))
        return {'animations': out}
    f['same_nodes'] = sorted(o.parent.items(), key=str) == sorted(c.parent.items(), key=str)
    if sname and sup is None:
        return f
    ref = ref_numbers([(n, p) for n, p, _ in decl], sup)
    f['numbers_by_rule'] = all(c.num[n] == ref.get(n) for n in c.names)
    f['reachable'] = reachable(o, sup)
    f['anim_mismatches'] = [anim_mismatches(anim_view(exp), o), anim_mismatches(anim_view(act), c)]
    if o.names != c.names and f['same_nodes']:
        # the original's stored tree with the transparency sort applied
        resorted = stored_order(o.root, o.kids, o.key)
        differ = [p for p in o.kids if o.kids[p] != c.kids.get(p)]
        f['tree'] = {
            'resorted_equals_compile': resorted == c.names,
            'differing_parents': len(differ),
            'differing_unsorted': sum(1 for p in differ if needs_sort([o.key[x] for x in o.kids[p]])
                                      and not in_sort_order(o.kids[p], o.key)),
            # differing parents whose compiled children are their original
            # children with the transparency sort applied, parent by parent
            # (a parent whose children do not differ needs nothing)
            'differing_resorted': sum(1 for p in differ if c.kids.get(p) == sort_children(o.kids[p], o.key)),
            # differing nodes where std::sort moves equal children (more than
            # 16): a stable sort of the stored order would keep them
            'ties_moved': sum(1 for p in differ if needs_sort([o.key[x] for x in o.kids[p]])
                              and sort_children(o.kids[p], o.key) != sorted(o.kids[p], key=o.key.get))}
        # The nodes whose sort key (is a mesh, transparencyhint) the compile
        # changed, and whether every differing parent's children are the
        # ASCII's declared children sorted by the compiled keys while the same
        # declaration sorted by the original's keys gives the original's
        # children: then the new keys alone re-sorted them (MDL-NODE-012).
        dk = {}
        for n, par, _ in decl:
            if par:
                dk.setdefault(par, []).append(n)
        try:
            f['tree']['hint_changed'] = sorted(n for n in o.key if n in c.key and o.key[n] != c.key[n])
            f['tree']['declared_resorted'] = bool(differ) and all(
                sort_children(dk.get(p, []), c.key) == c.kids.get(p) and
                sort_children(dk.get(p, []), o.key) == o.kids[p] for p in differ)
        except KeyError:
            f['tree']['declared_resorted'] = False
    return f


def aabb_entries(entries):
    """(entry, left, right) for each inner entry of an aabb tree stored
    depth-first, left subtree first (face -1 for an inner entry); None when
    the list is not such a tree."""
    out, pos = [], [0]

    def walk(depth):
        if pos[0] >= len(entries) or depth > 4096:
            raise ValueError
        i = pos[0]
        pos[0] += 1
        if entries[i]['face'] != -1:
            return i
        left = walk(depth + 1)
        right = walk(depth + 1)
        out.append((i, left, right))
        return i
    try:
        walk(0)
    except (ValueError, RecursionError):
        return None
    return out if pos[0] == len(entries) else None


AXIS = {1: (0, 1), 2: (1, 1), 4: (2, 1), 8: (0, -1), 16: (1, -1), 32: (2, -1)}


def plane_at_tie(plane, d):
    """Whether a plane is one MDL-MESH-052 could give at a tie: its axis is
    within TIE of the largest |centre delta| and its sign is the delta's on
    that axis (-Z, 32, for a zero delta)."""
    if plane not in AXIS:
        return False
    ax, sign = AXIS[plane]
    ad = [abs(x) for x in d]
    if ad[ax] < max(ad) - TIE:
        return False
    if d[ax] == 0:
        return plane == 32
    return (d[ax] > 0) == (sign > 0)


def aabb_facts(exp, act):
    """For an aabb tree whose planes differ: whether every box and face is
    the same (as the runner compares them) and how many planes differ, and
    at how many of those both planes are at a tie of the two largest axes."""
    import math

    def same(x, y):
        return all(abs(a - b) <= 1e-4 * max(1.0, abs(a), abs(b))
                   for a, b in zip(x['min'] + x['max'], y['min'] + y['max'])) and x['face'] == y['face']

    def delta(entries, left, right):
        cl = [(a + b) / 2 for a, b in zip(entries[left]['min'], entries[left]['max'])]
        cr = [(a + b) / 2 for a, b in zip(entries[right]['min'], entries[right]['max'])]
        return [cr[k] - cl[k] for k in range(3)]
    f = {'boxes_same': len(exp) == len(act) and all(same(x, y) for x, y in zip(exp, act)),
         'planes_differ': 0, 'ties': 0}
    if not f['boxes_same']:
        return f
    try:
        if any(not math.isfinite(float(v)) for e in exp + act for v in e['min'] + e['max']):
            f['boxes_same'] = False
            return f
    except (TypeError, ValueError):
        f['boxes_same'] = False
        return f
    inner = aabb_entries(exp)
    if inner is None or inner != aabb_entries(act):
        f['boxes_same'] = False
        return f
    for i, left, right in inner:
        if exp[i]['plane'] != act[i]['plane']:
            f['planes_differ'] += 1
            if plane_at_tie(exp[i]['plane'], delta(exp, left, right)) and \
                    plane_at_tie(act[i]['plane'], delta(act, left, right)):
                f['ties'] += 1
    if any(x['plane'] != y['plane'] for x, y in zip(exp, act) if x['face'] != -1):
        f['ties'] = -1  # a leaf's plane differs: not a tie
    return f


def aabb_stale_facts(emesh, exp, amesh, act):
    """For an aabb tree whose entry count differs: the leaves and faces of
    the original and the compile, and whether the compile's tree is whole
    and true to its faces: a tree (aabb_entries) whose leaves name each of
    its faces once, each leaf's box that face's box, and each inner box the
    union of its children's (all within 1e-4). The original's tree can hold
    more leaves than faces when faces were deleted after it was built
    (MDL-MESH-024)."""
    def leaves(entries):
        return [e['face'] for e in entries if e['face'] != -1]
    nf = len(amesh.get('faces', []))
    f = {'leaves': [len(leaves(exp)), len(leaves(act))],
         'faces': [len(emesh.get('faces', [])), nf],
         'complete': sorted(leaves(act)) == list(range(nf)), 'boxes_fit': False}
    inner = aabb_entries(act)
    if inner is None or not f['complete']:
        return f
    pos = amesh.get('vertices', {}).get('position', [])

    def near(x, y):
        try:
            return all(abs(float(a) - float(b)) <= 1e-4 * max(1.0, abs(float(a)), abs(float(b)))
                       for a, b in zip(x, y)) and len(x) == len(y)
        except (TypeError, ValueError):
            return False
    try:
        for e in act:
            if e['face'] != -1:
                ps = [pos[i] for i in amesh['faces'][e['face']]['v']]
                lo = [min(float(p[k]) for p in ps) for k in range(3)]
                hi = [max(float(p[k]) for p in ps) for k in range(3)]
                if not (near(e['min'], lo) and near(e['max'], hi)):
                    return f
        for i, left, right in inner:
            lo = [min(float(act[left]['min'][k]), float(act[right]['min'][k])) for k in range(3)]
            hi = [max(float(act[left]['max'][k]), float(act[right]['max'][k])) for k in range(3)]
            if not (near(act[i]['min'], lo) and near(act[i]['max'], hi)):
                return f
    except (IndexError, KeyError, TypeError, ValueError):
        return f
    f['boxes_fit'] = True
    return f

