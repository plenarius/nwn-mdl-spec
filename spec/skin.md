# Skinned meshes (`MDL-SKIN`)

**Goldens pending.** `nwmain-linux compilemodel` refuses a model whose skin
has not been bound yet ("contains skinmeshes not yet initialized"), and a
skin is bound only when a creature using the model is drawn
(MDL-SKIN-010). The suite's probe `zspec_skin` therefore has no golden; the
rules below rest on the engine's code (E20–E28, read on this build) and on
engine-compiled files examined outside this repository (Beamdog's HD body
parts, third-party test models compiled in game). They are confirmed in
that sense, and will be backed by goldens when an in-game rig exists.

## The ASCII

**MDL-SKIN-001** `weights` has one row per vertex of `verts`: up to four
pairs `bone weight`, bone a node name. A counted list skips only truly
empty lines (MDL-ASCII-050): a line of spaces is a vertex with no weights.
*Confirmed: `Parse<SkinVertexWeight>` 0x44fd00, E28.*

## When and against what a skin is bound

**MDL-SKIN-010** An ASCII skin is bound at the first draw of the first
instance of its model (`PartSkin::PostProcess` 0x483120, called from
`RenderSkinned` 0x482c70), against the tree that instance sits in, and
never again. A binary skin is never rebound: its bone map, bind lists and
per-vertex references are used as written. So a compiler writes, and a
decompiler reads, the bound state. *Confirmed: E20.*

**MDL-SKIN-011** The tree is found by walking up from the skin's part through
the parent links to the top part, then depth-first down, descending only
into children whose node belongs to the current part (so attached models
are skipped). A bone's **tree position** is its index in that walk. Bone
names are matched case-insensitively against it; the name `root` is
always position 0. *Confirmed: `GatherBones` 0x482b10, `MakeInlinePartList`
0x482690, `FindPartIndexDFS` 0x482750, E21.*

**MDL-SKIN-012** For a whole creature model the tree is the model's own. A
**body part** (neck, chest, arm, …, attached under the creature skeleton
node `capart.2da` names for its slot) is bound against the **creature
skeleton**: its tree positions are the skeleton's. Heads and robes are not
parts in this sense: the engine loads them as separate objects
(`AttachToObject`) and they bind to their own tree. A compiler that writes
a binary body part MUST number its bones against the skeleton it will be
worn on, and size the bind lists to that skeleton. *Confirmed: E22 (the
engine's HD neck `pmh0_neck001`: 3 nodes, bind lists of 56 entries, bone map
4 5 2 = neck_g, head_g, torso_g in `pmh0`); `Gob::Append` 0x4422a0;
`CNWCAnimBaseParts::LoadModel` 0x9db550; in-game confirmation of the
consequence (MDL-SKIN-030) in E22's rig test.*

## Bone numbering

**MDL-SKIN-013** Bones are numbered by first use: going through the vertices
in their final GPU order and each vertex's weight slots in order, a bone
whose tree position has no number yet gets the next (0, 1, 2, …); the bone
list (skin +64) and the bone map (`boneindexarray`) record it. Weights of 0
are skipped. *Confirmed: asm 0x483830-0x4839e9, E26.*

**MDL-SKIN-014** A weight whose name matches no tree position is dropped:
the slot is not advanced, the next influence overwrites it, and the
leftover slots at the end of the vertex are never written (they hold
whatever the pool held). The remaining weights are not renormalised.
A compiler MUST drop such influences the same way (and SHOULD warn).
*Confirmed: E26.*

**MDL-SKIN-015** Each vertex has four slots: four weights (f4) in one raw
stream and four bone references (s2, indices into the bone list) in
another. *Confirmed: E26; the HD parts.*

## Bind lists

**MDL-SKIN-020** For each tree position the engine stores `qbone_ref_inv =
−q` and `tbone_ref_inv = (−q) × (−p)`, where (p, q) is that node's transform
relative to the skin node and `−` on a quaternion negates w only (its
inverse, negated). So an identity is stored with w = −1. q and −q give the
same rotation. *Confirmed: `operator-(Quaternion)` 0x5b5d50, bind loop
0x483418, E24.*

**MDL-SKIN-021** The bind lists and the bone map have one entry per tree
position of the tree the skin is bound to (MDL-SKIN-012). The bone map's
count is at skin +24. *Confirmed: E22, E25.*

**MDL-SKIN-022** Unused bone list slots are 0 (the constructor zeroes them).
Bone constant indices are allocated and never written (uninitialised).
Parsed `qbone_ref_inv`/`tbone_ref_inv` rows in an ASCII win over the bind
(they are indexed from 0 and the bind appends after them). *Confirmed:
constructor 0x43c190, `InternalParseField` 0x44dbf0, E25, E27.*

## What the renderer does

**MDL-SKIN-030** For each bone slot i of 64, the renderer reads the tree
position t from the bone list; it skips the slot if t < 0 or t ≥ the number
of parts gathered, and stops at the second t = 0. The vertex shader sums
`weight × bone matrix × position` over the slots with weight > 0, starting
from (0, 0, 0, 0), with no normalisation. A vertex with no valid influence
is therefore drawn at clip-space (0, 0, 0, 0), collapsing the triangles
around it; a bone slot the renderer skips keeps the matrix of the previous
skin drawn that frame. *Confirmed: `ExecuteSkinGPU` 0x482800,
`GLRender::SetBoneMatrix` 0x4cbbb0, `inc_transform.shd`, E25; in game (E22's
rig: a part bound to its own tree rendered torn).*

**MDL-SKIN-031** A decompiler MUST keep a vertex's weights as the binary
gives them, and SHOULD warn about vertices with no valid influence (the
stock `c_wings2` has 102). *Confirmed (data): stock `c_wings2`.*

## Decompiling body parts

**MDL-SKIN-040** A skin whose bone map is longer than the file's own tree, or
whose bones lie past its last node, is bound to a skeleton (MDL-SKIN-012). A
decompiler MUST name its bones from that skeleton (found like a
supermodel: `p<race><gender><phenotype>` for a part named
`p<race><gender><phenotype>_<slot><number>`), and without it leave them
unnamed and say so; naming them after the part's own nodes gives wrong
bones. *Confirmed: E23 (the HD neck's bones on positions 4 and 5 do not
exist in its own 3-node tree).*

The skin header's size varies between files (MDL-BIN-061); that is about
layout, not binding: a reader MUST NOT conclude from a bone list read past
its real length that a skin is bound elsewhere.
