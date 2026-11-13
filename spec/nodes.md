# Nodes, numbers and supermodels (`MDL-NODE`)

## The tree

**MDL-NODE-001** A model has one root node (the one whose parent is `NULL`).
Its tree is stored depth-first through the children arrays (MDL-BIN-021).
*Confirmed: every golden.*

**MDL-NODE-002** A `parent` line names its node's parent by name, compared
case-insensitively. The engine looks the name up when it reads the line, in
the tree built so far: depth first from the root, each node's children in
the order they were added, and the first node of that name wins. Where a
name is used twice, a child therefore joins the copy that comes first in
that walk, which need not be the nearest copy declared before it:
- of two copies under two siblings, the one under the earlier sibling wins,
  whichever copy was declared first;
- of a node and a child of the same name (`head` under `head`), the outer
  one wins, since the walk visits a parent before its children.

The same holds for an animation's nodes, looked up in the animation's own
tree. Only nodes declared before the child are in the tree when its line
is read, so a copy declared after the child is never its parent. A
compiler MUST resolve parents this way. A
decompiler SHOULD write nodes so that this lookup gives back the stored
parents, and SHOULD say so when no order can (a child under a copy the walk
always reaches second). *Confirmed: zspec_dupparent (geometry and animation
`move`: `c1` joins the `hook` under `armL`, declared second; `c2` the `grip`
under `armL`, declared first, though the one under `armR` is nearer; `c3`
the outer `head`); `FindMdlNode(MaxTree*, char const*)` 0x447520 starts at
the root (tree +0x50), `FindMdlNode(MdlNode*, char const*)` 0x4474a0
compares with `strcasecmp` (0x4474bd) and recurses through the children
(+0x68, count +0x70) in order, returning the first match; E42, E72.*

**MDL-NODE-003** Several `parent NULL` nodes: each makes itself the tree's
root when its `parent` line is read, so the last one is the root and the
trees under the earlier ones are not written. Their nodes still take part
numbers (MDL-NODE-010) and count in the header's node count. A node
declared after the last root whose parent is only in a dropped tree, or
whose parent exists nowhere, is not found, and the game's compiler crashes
on it. A compiler MUST write only the last root's tree, numbered as
declared, and SHOULD warn that the earlier trees are dropped; it MAY refuse
a model whose parent lookup fails, which the game cannot compile. *Confirmed:
zspec_root2 (root `second`, nodes 2 and 3 written, node count 4);
zspec_root2b (a node whose parent is under the first root, declared after
the second) crashes `compilemodel` in `MdlNode::InternalParseField`
(+0x3da, 0x448f8a, the unchecked `FindMdlNode` result); E42, E72.*

## Part numbers

**MDL-NODE-010** Without a supermodel, a compiler MUST number nodes in the
order the ASCII declares them, the root first at 0: the engine gives each
node the next number when it reaches its `endnode`. This is not the
depth-first order when a node is declared before an earlier sibling's
children. *Confirmed: zspec_nodeorder (declared a, b, a1, b1, a2 → numbers
1, 2, 3, 4, 5; stored depth-first as a, a1, a2, b, b1); `ParseNode` 0x447540
(the counter at the tree +0x58).*

**MDL-NODE-011** The children of a node are stored in declaration order,
except as MDL-NODE-012 says. *Confirmed: zspec_nodeorder, zspec_transp
(`keep`).*

**MDL-NODE-012** When a node has a child mesh with transparencyhint > 0, its
children are sorted: every child that is not a mesh first, in declaration
order, then the meshes by ascending transparencyhint (compared as signed
integers). The check and the sort are made for each node separately. A
compiler MUST store the children in this order. *Confirmed: zspec_transp
(children dummy, light, dummy, then meshes with hints 0, 1, 2),
zspec_numbers; `MdlNode::ReorderChildren` 0x458120 with the comparison at
0x453470.*

The sort is libstdc++'s `std::sort`: introsort (median-of-three pivot,
partitioning down to runs of 16 or fewer, heap sort past 2·⌊log2 n⌋ levels),
then insertion sort. It keeps the declaration order of equal elements (all
non-meshes, or meshes with equal hints) only up to 16 children; past that, a
compiler MUST reproduce libstdc++'s algorithm step for step with this
comparison, since a stable sort gives a different order. Only the geometry
tree is sorted: `ImportMaxTree` (0x447ef0) calls `ReorderChildren` on the
model's root, not on animation trees. *Confirmed: zspec_tsort24,
zspec_tsort50, zspec_tsort90 (a replica of libstdc++'s algorithm reproduces
all three orders; a stable sort none); `__introsort_loop` (0x4586e0) and
`__insertion_sort` (0x458490) called from `ReorderChildren`, the tail call at
0x447f74.*

**MDL-NODE-013** Part numbers are not affected by the sort or by nodes left
out of the tree (MDL-ASCII-031): a number is used even by a node that is not
written. *Confirmed: zspec_transp (numbers in declaration order), zspec_numbers
(number 5 unused in the file).*

## Supermodels

**MDL-NODE-020** With a supermodel, the engine numbers a node by walking its
path from the root down the supermodel's tree, child by child, matching
names case-insensitively; the roots always match each other, whatever their
names. A node whose path exists in the supermodel takes that supermodel
node's part number. A node whose path does not exist gets -1 when its parent
matched, and otherwise the supermodel's header node count + 1 + its own
declaration index (the number MDL-NODE-010 gives it, moved past the
supermodel's). A supermodel node numbered -1 (one its own supermodel lacks)
still matches: the node takes -1 and the walk goes on to its children, which
take the supermodel's numbers, or -1 where the supermodel lacks them. A
compiler MUST number nodes this way and so needs the supermodel. *Confirmed:
zspec_kid (`hips` 1, `hand` 2, `foot` 5, `extra` -1), zspec_kid2 (`Arm` 3
matches `arm`; `hand` under it 4; `foot` directly under the root -1),
zspec_kid3, zspec_kid4 (`extra` and `lone` -1 under matched parents; under
unmatched ones, declared out of tree order, `deep_a` 11 = 6 + 1 + 4,
`deep_b` 12, `deeper` 14, `lone_c` 17), zspec_kid5 against zspec_mid (whose
`cape` is -1 and its children `cape_a` 10, `cape_b` 11): `cape` -1, `cape_b`
11 and `cape_a` 10, declared in another order, `cape_x`, which zspec_mid
lacks, -1. The code doing it was not read.*

**MDL-NODE-021** A name the supermodel uses twice is resolved by the walk:
the node takes the number of the supermodel node at the same path.
*Confirmed: zspec_kid (`hand` under `hips` → 2), zspec_kid2 (`hand` under
`arm` → 4).*

**MDL-NODE-030** The geometry header's node count is the number of nodes in
the file without a supermodel; with one, it is the supermodel's own header
count plus the model's node count plus 1. *Confirmed: every golden; zspec_kid
and zspec_kid2 (6 + 5 + 1 = 12), zspec_kid3 (6 + 2 + 1 = 9).*

**MDL-NODE-031** Supermodels contribute animations, not nodes: a creature's
instance tree is built from its own model's root (`NewCAurObject`,
`CreateInstanceTree(model + 0x50)`), and animations are found by walking the
supermodel chain, a model's own overriding a supermodel's of the same name.
*Read in code (behaviour.md, "Skin binding: further notes"); animation
lookup per Moonglow notes C2.*

## Animation nodes

**MDL-NODE-040** An animation's nodes are numbered by walking each one's path
from the animation's root down the model's own geometry tree, child by child,
matching names case-insensitively; the roots always match. A node whose path
exists in the geometry takes that geometry node's part number (with a
supermodel, the number MDL-NODE-020 gave it, -1 included). A node whose path
does not exist gets -1 when its parent matched, and otherwise its declaration
index in the animation: its position in the animation's list of nodes, the
root being 0, whether or not the model has a supermodel. The walk is by path:
a name the geometry has under another parent does not match. A compiler MUST
number animation nodes this way; giving a node the geometry lacks the root's
number (0) would bind its keys to the root (MDL-NODE-043). *Confirmed:
zspec_anim, zspec_bezier2 (`lamp` keeps 3), zspec_kid (`extra` -1 in
`kidanim`), zspec_animnum (`x` and `y` -1 under matched parents; `x_kid` 3
and `b` 4, their declaration indices, where their positions in the tree are 2
and 3 and the geometry's own `b`, under `a`, is 2); and in 577 Layonara
binaries whose animations have nodes their geometry lacks (87,000 animation
nodes, 13,300 of them missing from the geometry, 2,100 in models with a
supermodel), every one numbered as above.*

**MDL-NODE-041** An animation node keeps the node type of its geometry node:
its flags and full sub-headers are written (MDL-BIN-071), though only its
controllers matter. A compiler SHOULD write the geometry node's flags. A
node the geometry lacks takes its own type word instead (MDL-NODE-044).
*Confirmed: zspec_anim (`blade` 0x21 in `swing`), cmbez01; behaviour.md, "Animation blocks".*

**MDL-NODE-042** An animation's node count is the number of nodes in its own
tree: the nodes its ASCII lists. *Confirmed: zspec_anim (`idle`: 2),
zspec_bezier2 (4 of the model's 5).*

**MDL-NODE-043** The engine binds animation nodes to model nodes by part
number, not by name: a skeleton and its supermodels rewritten with fresh
numbers under the same names stop posing their creatures. A compiler MUST
therefore keep the numbering of MDL-NODE-010 and MDL-NODE-020. *Confirmed
in game by the Moonglow Viewer session of 2026-10-07 (Moonglow notes B.19);
not re-tested for this suite.*

**MDL-NODE-044** An animation node whose path the geometry lacks
(MDL-NODE-040) is written as the type its own type word names, whatever keys
it has: `node trimesh` gives flags 0x21 and a mesh header, `node light` 0x3
and a light header, `node emitter` 0x5 and an emitter header, `node dummy`
0x1. A mesh header there is empty (no vertices, faces or textures, the
default material fields), the same as the mesh header of an animation node
the geometry has (MDL-BIN-071); no sub-header of such a node is meaningful
(MDL-BIN-050). Its controllers are the keys its type reads, in the order of
their lines (MDL-CTRL-034), the shared ones (position, orientation, scale)
included; a key its type does not read is dropped (`alphakey` on a dummy),
and the node is kept with no controllers. A compiler MUST write the
controllers its declared type reads and SHOULD write that type's flags,
whether or not the node has a key of its type (a `node trimesh` with only
`positionkey` is still 0x21). A decompiler SHOULD write the type word the
flags give (`trimesh` for 0x21, `light` for 0x3, `emitter` for 0x5), so a
compile of its output gets the type back. *Confirmed: zspec_animnogeo
(animation `open`, every node -1 under the matched root: trimesh `x`
0x21 with position, alpha, orientation; light `y` 0x3 with color,
position, radius; trimesh `z` 0x21 with selfillumcolor, scale; dummy `w`
0x1 with position; trimesh `v`, only `positionkey`, 0x21 with position;
emitter `u` 0x5 with birthrate, position; dummy `t`, only `alphakey`, 0x1
with no controllers; mesh `m`, which the geometry has, the same empty mesh
header as `x`, `z` and `v`). Layonara's `tvd_udoor_09`, compiled by an
earlier compiler, stores its geometry-less `09_DWK_wg_closed` the same way
(0x21, an alpha controller). What the engine does with such a node at run
time is not observed (see [unknown.md](unknown.md)).*

**MDL-NODE-045** An animation's `animroot` is looked up among the
animation's own nodes, depth first from its root, by exact name (case
counts). When a node matches, the compiler prunes the animation's tree to
the path from the root to that node and the node's own subtree: every
other child of each node on the path is dropped with its subtree. When no
node matches (a name that exists nowhere, the name in another case, or a
node only the geometry has), the engine logs `Model <model> animroot
<name> node not matching existing node.` and keeps the whole tree, so the
animation plays on all its nodes as if its animroot were the root. An
animroot of `NULL` (any case) or none prunes nothing. Either way the
animroot is stored as written (MDL-BIN-070), and the animation's node count
stays that of the ASCII, before pruning (MDL-NODE-042). The pruning happens
only when the ASCII is read: the binary loader does not repeat it and
nothing at run time reads the animroot again, so a compiled animation
plays the tree that was written. A compiler MUST prune this way, MUST keep
the whole tree when the animroot matches no node, and MUST store the
animroot as written, case included. A decompiler MUST write an animroot
with which a compile gives back the stored animation tree. When the stored
tree is the stored animroot's cut (the root, the path to the node it
matches and that node's subtree), or the stored animroot matches no node,
that is an animroot that matches the same node, case for case, or none:
writing it as stored does that, while changing its case alone (`ARM` to
`arm` over a node `arm`) makes a recompile prune. A binary compiled by the
game is always this case, since its compiler stored the cut. When the
stored tree is wider than the stored animroot's cut (a binary another
compiler wrote, which the game plays as stored because the binary loader
does not prune), it is an animroot that matches no node, so the compile
keeps the whole tree; writing the stored one would cut the nodes outside
it.
A tool SHOULD warn when an animroot other than `NULL` matches no node of
its animation. *Confirmed: zspec_animroot (geometry root, `arm` with
`hand`, `leg`; `prune`, animroot `arm`: root, `arm`, `hand` written, `leg`
dropped, node count 4; `missing` (`nosuchnode`), `case` (`ARM`) and
`geomonly` (`leg`, which only the geometry has): every node written, the
animroot stored as written, and the log message for each). Code: E71
(`Animation::PostProcess` 0x453600, `findnode` 0x461600). Wider trees: 9
Layonara binaries the game did not compile (`a_ogre` and its four variants,
`a_skeleton`, `c_bugbeara`, `c_goblina`, `c_nasher`) keep animated nodes
outside their animroot's cut (`headconjure`, `handconjure`, `ogre_hair`, a
leg chain); cleanmodels PR #144 writes `ROOTDUMMY`, which matches no node,
and their trees, part numbers and keys round-trip exactly.*

## Worn models

**MDL-NODE-050** When a part-based creature wears a robe (its
`parts_robe.2da` model, such as `pmh0_robe202`), a node of the robe whose
parent is `torso_g` is drawn without its orientation: as if it were the
identity. Its position is kept, and so are the orientations of the nodes
below it, which are applied from there. The game's compiler keeps the
orientation in the binary (a `compilemodel` of such a robe has the same
orientation controller as the ASCII), so the loss happens at run time. A
tool that writes robes SHOULD put such a rotation into the node's own
vertices and normals, and into its children's positions and orientations,
leaving the node at the identity: that is drawn as modelled. A checker
SHOULD warn about a non-identity orientation on a direct child of
`torso_g` in a robe. *Confirmed in game (build 89.8193.37-17, 2026-10-22),
on a human male wearing two of a server's robes, loaded as ASCII from
`development/`, compared front, side and back:*

- *A cape panel hung from a shoulder pad that is a child of `torso_g` and is
  turned 180 degrees about x stood up above the shoulder instead of hanging
  down. It still did with the pad renamed, with the turn written `1 0 0
  3.14159` instead of `-1 0 0 -3.14159`, at 172 degrees, with the panel a
  trimesh instead of a danglymesh, and with the panel on another texture.
  With the pad turned 90 degrees about x and the panel's own transform
  adjusted to keep the modelled placement, the panel stuck out backward,
  where the pad's turn left out puts it. Hung from `torso_g` itself, with
  its transform composed from the pad's and its own, the panel stuck out
  backward: where its vertices lie with no rotation at all. With the pad's
  turn put into the pad's vertices and the panel's transform (the pad at the
  identity), it hung as modelled.*
- *A figure draped over the shoulder, a danglymesh child of `torso_g` turned
  2.73 radians, lay in front of the wearer; with its turn put into its
  vertices and its five children's transforms, it was draped as modelled.*
- *A belt that is a child of `pelvis_g`, turned 0.64 radians, looked the
  same with and without its turn put into its vertices: the rule is not one
  for every bone.*

*BioWare's robes and cloaks never depend on it: in the base game, nodes
under a body bone are turned by at most 0.06 radians, apart from dummies
(`Impact`).*

