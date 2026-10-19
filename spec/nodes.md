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

The sort is `std::sort`, which keeps the declaration order of equal
elements only up to 16 children; beyond that their order is whatever
libstdc++'s introsort leaves ([unknown.md](unknown.md)).

**MDL-NODE-013** Part numbers are not affected by the sort or by nodes left
out of the tree (MDL-ASCII-031): a number is used even by a node that is not
written. *Confirmed: zspec_transp (numbers in declaration order), zspec_numbers
(number 5 unused in the file).*

## Supermodels

**MDL-NODE-020** With a supermodel, the engine numbers a node by walking its
path from the root down the supermodel's tree, child by child, matching
names case-insensitively: a node whose path exists in the supermodel takes
that supermodel node's part number; any other node gets -1. The roots
always match each other, whatever their names. A compiler MUST number
nodes this way and so needs the supermodel. *Confirmed: zspec_kid (`hips` 1,
`hand` 2, `foot` 5, `extra` -1), zspec_kid2 (`Arm` 3 matches `arm`; `hand`
under it 4; `foot` directly under the root -1), zspec_kid3.*

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
