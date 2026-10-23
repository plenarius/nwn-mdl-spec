# Nodes, numbers and supermodels (`MDL-NODE`)

## The tree

**MDL-NODE-001** A model has one root node (the one whose parent is `NULL`).
Its tree is stored depth-first through the children arrays (MDL-BIN-021).
*Confirmed: every golden.*

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
supermodel's). A compiler MUST number nodes this way and so needs the
supermodel. *Confirmed: zspec_kid (`hips` 1, `hand` 2, `foot` 5, `extra`
-1), zspec_kid2 (`Arm` 3 matches `arm`; `hand` under it 4; `foot` directly
under the root -1), zspec_kid3, zspec_kid4 (`extra` and `lone` -1 under
matched parents; under unmatched ones, declared out of tree order, `deep_a`
11 = 6 + 1 + 4, `deep_b` 12, `deeper` 14, `lone_c` 17). The code doing it was
not read.*

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

**MDL-NODE-040** An animation's nodes take the part number of the model node
of the same name (through the same walk as MDL-NODE-020 when the model has a
supermodel), or -1. *Confirmed: zspec_anim, zspec_bezier2 (`lamp` keeps 3),
zspec_kid (`extra` -1 in `kidanim`).*

**MDL-NODE-041** An animation node keeps the node type of its geometry node:
its flags and full sub-headers are written (MDL-BIN-071), though only its
controllers matter. A compiler SHOULD write the geometry node's flags.
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

