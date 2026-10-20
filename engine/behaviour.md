# What the engine does with models

Build 89.8193.37-17 (`nwmain-linux`). Addresses are objdump addresses
(Ghidra adds 0x100000). See [README.md](README.md) for the conventions.

## Pipeline

`MdlNodeTriMesh::InternalPostProcess` (0x4577c0) runs, for a mesh that has
no GPU vertices yet (an ASCII mesh): `ProcessVerts` → `InternalGenVertices`
(virtual: merging and degenerate faces) → `BuildNeighborLists` →
`BuildVertexIndices` → `GenerateVertexData` → `CalculateTangentSpaceBasis`.
A mesh loaded from a binary already has GPU vertices; only
`CalculateTangentSpaceBasis` runs. AnimMesh, DanglyMesh and Skin have their
own variants of the chain. *Confirmed (code).*

`compilemodel` (a thin wrapper, E14) writes the in-memory state after this
pipeline, and for skins after the first-draw bind (E20). The serialiser
(0x4bc560: a size pass 0x4b99c0, one allocation, a copy pass 0x4bbfc0,
`fwrite`) copies struct fields, copies arrays and reads the GPU vertex
pools back; it calls no vector, quaternion or normalising maths. So an
engine-compiled file is the state the game renders. *Confirmed (call graph;
not every line read).*

## Meshes (E1–E19)

**E1 Vertex merging.** Each node type has its own `InternalGenVertices`.
TriMesh (0x454610), AnimMesh, DanglyMesh and Skin build a vertex per face
corner and scan the whole vertex list in order, taking the first equal one
(`operator==`) or appending. Only the AABB variant (0x454920) differs: a
corner joins a vertex only through an earlier face with at least two equal
corners. `BuildVertexIndices` merges nothing. *Confirmed (asm for TriMesh and
AABB; the others by call targets); goldens zspec_merge, zspec_aabb.*

**E2 The merge key.** `NodeVertex::operator==` (0x45a300) compares the face's
mirrorlist byte, position, normal (float `==`, so −0 == +0), UV sets 0-3,
and colour and tangent with handedness when present. Material and smoothing
group are not compared. `NodeVertexAnim::operator==` (0x45a550) adds three
animation vertex lists, `NodeVertexDangly::operator==` (0x45a8d0) the
constraint, and the skin path `SkinVertexWeight::operator==` (0x43d270, E16).
*Confirmed (code); zspec_merge.*

**E3 `mirrorlist`.** An optional mesh list, parsed as `List<int>` by the
trimesh parser (0x44ced0), one integer per face. Its low byte enters the
merge key, so faces with different values never share a vertex. Absent, it
is 0 for every face. It is not stored in binaries. *Confirmed (code);
zspec_merge (`mirror`).*

**E4 `BuildVertexIndices`.** Copies each face's three u16 indices (face +0x1a,
+0x1c, +0x1e) into one flat index buffer. No merging. *Confirmed (code).*

**E5 Degenerate faces.** After merging, faces are walked backward and a face
with two equal GPU indices is deleted. Vertices it introduced stay.
*Confirmed (code); zspec_merge (`degen`).*

**E6 Degenerate faces on walkmeshes.** The same delete loop (0x454c59-0x454cc1)
runs for AABB nodes after their adjacency merge. Nothing re-indexes the
authored tree: `MdlNodeAABB::InternalParseField` (0x44dba0) passes the `aabb`
text to `Parse` and stores the returned tree. After a deletion every later
leaf points one face too far. *Confirmed (code; golden zspec_aabbdeg: 3
faces, leaves 0-3). The in-game effect is not observed.*

**E7 AABB tree.** `Parse(char const*, AABB*&)` (0x446ed0) reads `"%f %f %f %f
%f %f %d %d"` per entry; the stored tree equals the authored one entry for
entry. *Confirmed (code; zspec_aabb, zspec_aabbdeg).*

**E8 Normal generation.** `ProcessVerts` (0x454dd0), only when the mesh has
no normals. Per corner: for earlier faces sharing the vertex and a smoothing
bit, reuse its stored normal if dot(face normal, that normal) ≥ −0.99
(double constant at 0x13f0548); otherwise sum the area-weighted cross
products of this face and later faces that share the vertex and a bit. A
zero sum gives the normalised face normal; otherwise the sum is normalised.
*Confirmed (code); zspec_normals.*

**E9 Tangents.** `CalculateTangentSpaceBasis` (0x457710) gates (E11) then
calls 0x456190. Per triangle: t = ((v2−v0)(p1−p0) − (v1−v0)(p2−p0)) / det,
not normalised; w = +1 if det ≥ 0 else −1. det = 0 is not skipped: t = the
mean of the three normals with components rotated, w = +1. Accumulate per
vertex, then Gram-Schmidt against the normal and normalise. *Confirmed
(code); zspec_hint_mesh, zspec_tanmirror.*

**E10 Tangent clones.** When a later triangle's w differs from the vertex's
stored w, a new vertex is appended (once per source vertex and w) and the
corner's index rewritten. UV sets, colour, dangly constraints and skin
weights are copied to the clone. AnimMesh nodes overwrite instead. *Confirmed
(code); zspec_tanmirror (see E53 for which index is rewritten).*

**E11 Tangent gating.** Only for shader/material type 2 or 3, only if the
position, UV0 and normal pools exist, `this+0x270 == 3`, and the tangent
pool is still unset (−1). Tangents already in the file are used as they
are. *Confirmed (code); zspec_hints, zspec_tanfile.*

**E12 GPU vertex layout.** `GenerateVertexData` (0x453ab0): position vec3,
UV0-3 vec2, normal vec3, tangent vec3 and a separate float handedness pool,
colour bytes `(int)(f × 255 + 0.5) & 0xff` with alpha 0xff (the runtime pool;
the file stores the same, zspec_trimesh). No bitangent stream. *Confirmed
(code); zspec_trimesh.*

**E13 Bounds.** `ProcessVerts` also computes the minimum, maximum, centroid
(mean of the source vertices) and radius (largest distance from the
centroid). Surface area is computed separately
(`ComputeLocalSurfaceArea`). *Confirmed (code); zspec_merge.*

**E14 `compilemodel`.** `FindModel`, then `compilemodelsinternal`
(0x448410), which only checks for an unbound skin and calls
`IODispatcher::Write`. The work is in the post-process chain. *Confirmed
(code).*

**E15 Face adjacency.** Engine-compiled walkmeshes carry real neighbour ids
in each face (3 × s16 at face +0x14, −1 none). The engine recomputes them
when it loads a walkmesh (`CNWTileSurfaceMesh::ComputeTriangleAdjacency`
0x4269a0, called from `LoadWalkMesh` and `LoadDefaultWalkMesh`). The values
come from `BuildNeighborLists`: source vertex indices, either direction,
lowest face wins, computed on the source face list. *Confirmed (data,
caller); inferred: the stored values are not used by walkmesh code.*

**E16 Skin, anim and dangly vertex equality.** `SkinVertexWeight::operator==`
(0x43d270): same bone count, then per slot the bone name (strcasecmp) for
named bones; the weight is compared only for a bone with no name.
`NodeVertexDangly::operator==` adds the constraint. `NodeVertexAnim::operator==`
adds three animation vertex lists. *Confirmed (code).*

**E17 Legacy binaries.** Some base-game binaries (`Red_M_Torso`,
`pmh0_head001`, `ctl_compass`) hold exact duplicate vertices (position, UV,
normal and colour identical), which E2 would always merge. They were not
written by the EE compile path; most likely BioWare's original exporter.
*Inferred (the duplicate counts equal the vertex-count differences against an
EE compile of the same ASCII).*

**E18 `Vector::Normalize`** (0x5b3700): a vector whose squared length is
within 1e-5 of 1 is returned unchanged; zero becomes (1, 0, 0); otherwise v
× sqrt(1/length²) in float32. *Confirmed (asm); zspec_orient (zero axis),
zspec_merge (degenerate face normal).*

**E19 Face normal and plane distance.** `BuildNeighborLists` writes each
face's unit normal and plane distance −(n · p0). *Confirmed (code); see E53
for the numbering.*

## Skin binding and rendering (E20–E28)

Read with headless Ghidra; `PartSkin::PostProcess`'s end was read in
assembly. Structure offsets: `Part` +0x08 `MdlNode*`, +0x10 position,
+0x1c orientation, +0x38/+0x40 children, +0x48 parent. `MdlNodeSkin`
+0x278 the ASCII-only temporary arrays, +0x284 GPU vertex count (0 = not
bound yet), +0x2c8 weights, +0x2e0/+0x2e8 `boneindexarray`, +0x2f0
`qbone_ref_inv`, +0x300 `tbone_ref_inv`, +0x310 `boneconstantindices`,
+0x320 bone list (64 × s16).

**E20 When a skin is bound.** `RenderSkinned` (0x482c70) calls the skin
part's `PostProcess` (vtable slot 0xe0) on every draw. `PartSkin::PostProcess`
(0x483120) works only while the ASCII temporary arrays exist and ends with
`RemoveTemporaryArrays`, which clears them (0x454379). So an ASCII skin is
bound at the first draw of the first instance, once per loaded model,
against that instance's tree. A binary skin is never rebound. +0x284 is set
in the same function (0x483719); `modelHasUninitializedSkinmesh` (0x44e030)
tests it, which is why `compilemodel` needs the creature on screen.
*Confirmed (code).*

**E21 Which tree, in which order.** The bind and the renderer walk up from
the skin's part through the parent links (+0x48) to the top part, then
depth-first down (`GatherBones` 0x482b10, `MakeInlinePartList` 0x482690,
same order), descending only into children whose node's parent is the
current part's node (attached models are skipped). Tree position = index in
that list. Bone names are resolved by `FindPartIndexDFS` (0x482750):
case-insensitive; `root` is always 0; not found gives −1. *Confirmed
(code).*

**E22 Body parts bind to the creature skeleton.** For a part attached to a
creature (`Gob::Append` 0x4422a0: the part's root is appended under the
named skeleton part and its parent link set), the top part is the skeleton,
so tree positions are skeleton positions. Data: Beamdog's engine-compiled HD
neck `pmh0_neck001` (3 nodes) has bind lists of 56 entries (the `pmh0`
skeleton's node count) and the bone map 4 5 2 (`neck_g`, `head_g`, `torso_g`
in `pmh0`). For an ASCII part this is harmless (names resolve at the first
draw); a binary part's positions are used as written. Heads and robes are
not parts: `CNWCAnimBaseParts::LoadModel` (0x9db550) appends part slots 0-17
under their `capart.2da` node, but loads the robe (slot 18) with
`NewCAurObject` and `AttachToObject`, and `CNWCAnimBaseHead::LoadModel`
(0x9d4660) attaches the head with `AttachToObject` at `head_g`; such
objects bind to their own tree (all 132 skinned HD robes have bind lists the
size of their own file). *Confirmed (code and data); in game (2026-10-14:
the HD neck bound to its own tree rendered torn on a male human; bound to
`pmh0` it rendered correctly).*

**E23 Decompiling a skinned part.** Naming a part's bones through its own
node list gives wrong names: on `pmh0_neck001`, `torso_g` (skeleton
position 2) becomes the file's own position 2 (its shadow mesh), and
positions 4 and 5 do not exist in the file. The skeleton is needed.
*Confirmed (data).*

**E24 Bind maths.** `operator-(Quaternion)` (0x5b5d50) negates w only: with w
stored first that is the inverse, negated. The bind loop (0x483418) stores
per tree position `tbone = (−q) × (−p)` and `qbone = −q`, where (p, q) is
that bone's transform relative to the skin node (`GatherBones` is seeded
with the inverse of the skin part's chain). So `qbone_ref_inv` has w = −1
for an identity. q and −q give the same matrix (`ExecuteSkinGPU` and
`operator*(Quaternion, Vector)` are quadratic in q). The `orientation`
axis-angle conversion is not used for bind lists; they come from the parts'
live transforms. *Confirmed (code).*

**E25 What the renderer does per bone.** `ExecuteSkinGPU` (0x482800): for
each bone slot i of 64, t = bone list[i]; skipped if t < 0 or t ≥ the
number of gathered parts; the second t == 0 ends the loop (the constructor
0x43c190 zeroes the list). Otherwise it updates the gathered transform in
place with `tbone[t]`/`qbone[t]`, builds the matrix and calls
`SetBoneMatrix(i)`. Neither bind list's length is checked.
`GLRender::SetBoneMatrix` (0x4cbbb0) stores into one global `m_bones[64]`
shared by every skin and ignores i ≥ 64. The shader (`inc_transform.shd`)
sums `weight × m_bones[index] × pos` over the four slots with weight > 0,
from (0, 0, 0, 0), unnormalised; since pos.w = 1 the result's w is the sum
of the applied weights, so the perspective divide renormalises partial
weights. *Confirmed (code).*

**E26 Bone numbering and dropped influences.** Per GPU vertex, in GPU order,
per slot: write reference −1 and weight −1.0, then the slot's weight.
Weight 0: keep (−1, 0) and advance. A name that did not resolve, or a
position past the tree: do not advance, so the next slot overwrites it;
slots left at the end are never written and hold whatever the pool held. A
resolved bone whose tree position has no number gets the next one (0, 1,
2, …), recorded in the bone list and `boneindexarray`. More than 64
distinct bones write past the 64-entry list. *Confirmed (asm
0x483830-0x4839e9).*

**E27 Uninitialised skin fields.** `boneconstantindices` (+0x310) is resized
to the tree size (`realloc`, 0x48398a) and never written by the bind (only
`InternalParseField` writes it, from ASCII). Dropped-influence slots (E26)
are unwritten pool memory. The bone list's unused slots are the
constructor's zeros. `qbone_ref_inv`/`tbone_ref_inv` lines in an ASCII are
parsed (0x44dbf0) into the same lists and the bind appends after them, so
the parsed entries win. *Confirmed (code).*

**E28 ASCII weights list.** `Parse<SkinVertexWeight>` (0x44fd00): with a
count it reads that many entries, skipping only lines whose first byte is
NUL, `\n` or `\r` (mask 0x2401); a line of spaces is an entry with no bones.
Without a count it reads to `endlist` with the same rule. *Confirmed
(code).*

### Skin binding: further notes

- A part root's own transform counts: `CreateInstanceTreeR` (0x43c6b0)
  builds each part (the `Part` constructor starts at identity) and runs its
  node's controllers (`MdlNode::InternalControl` 0x4990c0); `Gob::Reset`
  (0x499bd0), just before the bind, re-applies them at time 0
  (`AnimateHierarchy`). *Confirmed (code).*
- Supermodel chains: `NewCAurObject` builds a creature's instance tree from
  its own model's root (`CreateInstanceTree(model + 0x50)`); supermodels
  contribute animations, not nodes. *Confirmed (code; every HD part binds to
  exactly its skeleton's 56 own nodes).*
- Every skinned part in the HD patch haks (21,918) is reproduced bind entry
  for bind entry by binding against the skeleton as E21-E22 describe.
  *Confirmed (data).*

### Animation blocks

In the game's compile, an animation node keeps its geometry node's type and
headers: a trimesh node in an animation carries the 512-byte mesh header
(flags 0x21; skin 0x61, dangly 0x121). *Confirmed (data; zspec_anim).* The
same compile of a third-party creature omitted animation nodes that had no
controllers (its six skin nodes, in every animation); the probes here kept
such nodes (zspec_anim's root): what decides it is open.

## Resource priority, armour, loading (E29–E32)

**E29 Resource priority.** Higher id wins. `CExoResMan::SetupDefaultSearchPath`
(0x53ca40): base keys 1,000,000+, `override/` 12,000,000, `development/`
71,000,000 (the only directory with dynamic reload, `SetAllowDynamicReload`),
vaults 80-81,000,000, temp 99,000,000. `AttachPatchFiles`: the `patch/` haks
(Beamdog's `bdhd_*.hak`) at 13,000,000+. `LoadModuleStart`: the module at
20-23,000,000 and its haks at 30-31,000,000. So the HD patch haks outrank
`override/` but not a module, its haks or `development/`, and replace stock
robes, cloaks and armour parts and their textures under the same names.
*Confirmed (asm constants; engine log KeyTable lines).*

**E30 Armour, robe and cloak textures.** `CNWCCreatureAppearance::CreateBodyParts`
(0x734440) builds each part model's name as `<body>_<slot>` + `%03u`; its
palette texture is the same name if that PLT exists, else the phenotype-0
and then the human (`PMH0_`/`PFH0_`) name with the same number, and it
replaces the model's texture with it (`CNWCObject::ReplaceTexture`): the
bitmap in the model is not what is drawn. `CreateCloak` (0x736c90) takes the
model and texture from `cloakmodel.2da`. *Confirmed (decompile).*

**E31 Binary model loading.** `IODispatcher::ReadSync` (0x4bf670) hands every
binary model to one converter (0x4bd400, per node type; meshes 0x4bc9b0) with
no branch on header values. It copies faces into the face list, the vertex,
UV, normal and colour arrays from the raw data into GPU pools with plain
`memcpy`, and each index buffer from the raw data at its offset with its
count of u16. *Confirmed (asm).*

**E32 Skeleton and part fallbacks by phenotype.** `CreateBodyParts`: the
skeleton is `P` + gender + race + phenotype; when it does not exist and the
phenotype is not 0, the race's phenotype 0 skeleton is used (hard-coded, not
`DefaultPhenoType`). A part keeps the asked-for phenotype; when it does not
exist, phenotype.2da `DefaultPhenoType` is tried once; failing that the slot
stays empty. Heads (`CreateHead` 0x731bb0) fall back the same way.
*Confirmed (decompile; the load call's resref argument inferred).*

## Bezier controllers (E33–E37)

**E33 ASCII bezier keys.** `Parse(const char*, AurGenericKey&)` (0x446ae0)
reads at most 10 floats a row (time + 9). `AddBezierController` (0x448a30)
stores the times, then each row's values, and sets the column byte to
`((floats in row 0 − 1) / 3) | 0x10`. Keywords: base `positionbezierkey`,
`orientationbezierkey`, `scalebezierkey`; light `color`, `radius`,
`shadowradius`, `verticaldisplacement`, `multiplier`; trimesh
`selfillumcolor`, `alpha`; every emitter controller. *Confirmed (code);
cmbez01, zspec_bezier2.*

**E34 `orientationbezierkey`.** Its 13-float rows are cut to 10, not converted
from axis-angle (only 5-float rows are), and get column byte 0x13, so they
are evaluated as a 3-column vector written into the rotation. *Confirmed
(code; cmbez01). Effect on screen inferred.*

**E35 Evaluation.** `NewController::Control` (0x498f20) dispatches on the
column count: 1 `GetFloatValue` (0x498480), 3 the vector path (0x498180),
both testing 0x10 and using `InterpolateBezier` (float 0x5b9140, vector
0x5b8fd0); 4 `GetQuaternionValue` (0x498640) always slerps. Vector: P0 = v0,
P1 = v0 + out0, P2 = v1 + in1, P3 = v1. Scalar: `InterpolateBezier(v0, v0 +
v1, out0, out0 + in1, t)`, which does not match the vector form. Past the
last key both bezier paths read beyond the controller's data. *Confirmed
(code); not observed in game.*

**E36 Binary bezier and static controllers.** The loader (0x4c01b0) copies
the 12-byte keys and the data unchanged, remapping only the type (binary id
→ runtime offset, by id ranges per node class), so a binary 0x10 controller
is evaluated like an ASCII-built one. On a geometry node, `Gob::Reset`
(0x499bd0) animates at t = 0 and both paths return the first value before
testing 0x10. *Confirmed (code); zspec_bezier2 (geometry `alphabezierkey`
stored as 0x11 with its handles).*

**E37 `lightningsubdiv`.** The emitter parser has no `lightningsubdiv`
keyword, static, `key` or `bezierkey`; the other lightning parameters are
there. The engine's compile of the stock `vdr_bubbles_m`, which has
`lightningsubdivkey`, has no controller for it. *Confirmed (code; data;
zspec_emitter, zspec_animfx).*

## The ASCII reader (E38–E50, new)

**E38 Top level.** One dispatcher (0x446330, unnamed) recognises
`filedependancy`, `setsupermodel`, `setanimationscale`, `classification`,
`newmodel`, `newanim`, `beginmodelgeom`, `donemodel` and `ignorefog` with
`strncasecmp` on each word's length, so they are case-insensitive prefixes.
Inside a geometry or animation block `ImportMaxTree` (0x447ef0) hands lines
to the tree's parser until a line starting with `done` or `end`
(case-sensitive). `node` is a case-sensitive 4-byte compare (0x447963).
*Confirmed (code); every golden.*

**E39 Classification.** `classification(char*)` (0x446440): `tile` 2,
`character` 4, `effect` or `effects` 1, `door` 8, compared with strcasecmp;
anything else leaves the byte (0). *Confirmed (code); zspec_cls_tile,
zspec_cls_tiles (0), zspec_cls_effs, zspec_cls_gui, zspec_cls_item,
zspec_cls_door, zspec_dummy.*

**E40 `ignorefog`.** The fog byte is 0 when `ignorefog` is non-zero, else 1.
*Confirmed: zspec_cls_door, zspec_cls_gui.*

**E41 Node types.** `ParseNode` (0x447540) reads `%s %s` (type and name) and
compares the type with strcasecmp against camera, emitter, light, trimesh,
animmesh, danglymesh, reference, aabb, skin; any other word gives a plain
`MdlNode`. Lines go to the node's parser (leading whitespace skipped) until
one starts with `endnode` (case-sensitive, 7 bytes). The camera parser
(0x449000) reads nothing of its own; cameras are written with flags 0x9.
*Confirmed (code); zspec_nodetypes.*

**E42 `parent`.** `MdlNode::InternalParseField` (0x448bb0) matches `parent`
with a case-sensitive 6-byte compare, reads a word, and if it is `NULL`
(strcasecmp) makes the node the tree's root; otherwise it looks the parent
up (`FindMdlNode`) and appends the node to its children, without checking
the lookup. A node with no recognised `parent` line is in no tree and is
not written. *Confirmed (code); zspec_numbers (`PARENT`).*

**E43 Part numbers and order.** At `endnode`, `ParseNode` gives the node
the tree's next number (tree +0x58, then incremented): numbers follow
declaration order, a dropped node included. Children are appended in
declaration order. The file is written depth-first. *Confirmed (code);
zspec_nodeorder, zspec_numbers, zspec_transp.*

**E44 Child order and transparency.** After parsing, `MdlNode::ReorderChildren`
(0x458120) recurses through the tree; where a node has a child trimesh with
transparencyhint (+0x11c) > 0, it sorts that node's children with
`std::sort` and the comparison at 0x453470: a non-mesh is less than a mesh;
two meshes compare by transparencyhint (signed). *Confirmed (asm);
zspec_transp, zspec_numbers.*

**E45 Supermodel numbering.** A model with a supermodel numbers its nodes
from the supermodel: by the path from the root, names compared
case-insensitively, a matched node takes the supermodel node's number; an
unmatched one gets −1 when its parent matched, and otherwise the
supermodel's count + 1 + its declaration index; the roots match. The header
node count is the supermodel's count + the model's own + 1. Animation nodes
are numbered the same way. *Confirmed (goldens zspec_kid, zspec_kid2,
zspec_kid3, zspec_kid4); the code doing it was not read.*

**E46 Key lists.** `Parse<AurGenericKey>` (0x44e570) reads `"%d %c"` after the
keyword. A count alone: that many rows, skipping lines whose first byte is
NUL, `\n` or `\r`. A count followed by another character: the rows are
copied as binary data (`AurResGetData`). No count: rows to a line starting
with `endlist` (case-sensitive, 7 bytes), same skipping. Count 0 clears the
list. *Confirmed (code); zspec_anim (counted with an empty line, endlist
form). The binary form is not probed.*

**E47 Static values and orientation.** `AddGenericControllerSingle` (0x4486f0)
makes one key at time 0 with column byte = the number of floats read; with
four floats it converts axis-angle to a quaternion through
`Vector::Normalize` (zero axis → (1, 0, 0)), sin and cos of half the angle.
`AddGenericController` (0x4488d0) sets column byte = floats in the row − 1;
`Parse(AurGenericKey)` converts a row of exactly five floats. (`Parse(char
const*, Quaternion&)`, 0x4469c0, used for `qbone_ref_inv` rows, instead
maps a zero axis to the identity.) *Confirmed (code); zspec_orient (zero axis
→ rotation about X; non-unit axis normalised), zspec_numbers (one column
for `position 1.5abc 2 3`), zspec_anim.*

**E48 Numbers.** `Parse(char const*, float&)` (0x446770) is `sscanf("%f")`;
vectors use `"%f %f %f"` (0x4466a0). `Parse(char const*, int&)` (0x446790):
`%d`; if nothing was read, `%s` compared with `TRUE`/`FALSE` (strcasecmp),
else unchanged. `Parse(char const*, bool&)` (0x446900): the words true,
false, 1, 0 (strcasecmp). Faces: `%d` × 8 (0x446c50). *Confirmed (code);
zspec_numbers, zspec_numfmt.*

**E49 Keywords per parser.** The words each parser compares, read from the
string references in each function, are in
[tables/keywords.yaml](../tables/keywords.yaml). Notably absent:
`setfillumcolor`, `texture3` and up, `lightmapped`, `center` (trimesh
0x44ced0); `lightningsubdiv`, `opacity` (emitter 0x449090); `ambient_only`,
`fading_light`, `negativelight`, `lensflares`, `n_dynamic_type`,
`affect_dynamic` (light 0x44baf0). `materialname` is stored in texture slot
3; `bitmap` and `texture0` share slot 0; `isdynamic` and `nDynamicType` share
a field. *Confirmed (code); zspec_setfill, zspec_light (lamp_b),
zspec_emitter, cmtan01.*

**E50 Defaults.** For a keyword not given, the game's compiler writes: mesh
diffuse and ambient (1, 1, 1), specular 0, shininess 1, shadow 1, render 1,
beaming 0, transparencyhint 0, tilefade 0; AABB render 0 and shadow 0;
light lightpriority 5, ambientonly 0, dynamic type 1, affectdynamic 1, shadow
1, generateflare 0, fadingLight 1, flareradius 0; reference refModel empty,
reattachable 0; and no controller at all for a controller keyword not given.
*Confirmed (goldens: every mesh probe, zspec_aabbdef, zspec_light,
zspec_numbers, zspec_reference).*

## Compiled output (E51–E63, new)

**E51 Light controller 144.** Not written by this build's compiler for any
light keyword, static or keyed. The loader (0x4c01b0) maps light ids ≥ 0x4c
by +0x18 like the other light ids, so 144 lands at runtime offset 0xa8; what
reads it was not traced. *Confirmed (zspec_light, zspec_animfx; code for the
mapping).*

**E52 A material named by `bitmap`.** With no `renderhint` and no
`materialname`, a mesh whose bitmap names an `.mtr` with
`renderhint NormalAndSpecMapped` gets tangents, with hint field 0, as with
`materialname`. *Confirmed: zspec_mtrbmp, cmtan01.*

**E53 Which index the tangent clone rewrites, and face records after a
deletion.** Tangent generation rewrites the corner in the index list (what
the GPU draws); the 32-byte face records keep the pre-clone index. Face
normals and plane distances are computed on the source face list by
position, so after a degenerate face is deleted the later records carry the
values of the source face with the same index (a degenerate source face's
normal is (1, 0, 0) from E18). *Confirmed: zspec_tanmirror, zspec_merge
(`degen`).*

**E54 Animmesh animations.** `MdlNodeAnimMesh::InternalPostProcess` divides
the animation node's `animverts` count by its own vertex count (0x4578c9,
`idivl`), so an animation node without `verts` crashes the engine (SIGFPE,
reproduced with `nwmain-linux compilemodel`); the `animtverts` count is
divided by its tvert count. The sets are stored vertex-major over the
merged (GPU) vertices, each taking its source vertex's and source tvert's
entries; `NodeVertexAnim::operator==` (0x45a550) compares them when
merging. The binary loader's animmesh branch (0x4bd400) copies `vertex
count (node +0x230) × sets` entries, so the animation node's own vertex
count must be right. *Confirmed (in-engine crash with backtrace; asm;
zspec_animmesh, zspec_animtv; loader code).*

**E55 Runtime and uninitialised fields.** Compiling every probe twice and
comparing the bytes: function pointers, geometry and parent pointers,
reference counts, header padding, the controller key pad byte, the mesh
`lightmapped` byte, the 3 bytes after the triangle mode, string bytes after
the NUL, unreferenced model data, the type-specific headers of animation
nodes, and emitter `xgrid`/`ygrid` when the ASCII does not set them all
differ between the two compiles. Everything the suite compares is
identical. *Confirmed: conformance/goldens/ against
conformance/goldens/run2/.*

**E56 AABB nodes.** E6 is shown by a golden (zspec_aabbdeg). An AABB node
with no `render`/`shadow` lines gets 0 and 0 (zspec_aabbdef). The split
plane of an inner node whose children have equal boxes is −Z (32)
(zspec_aabb). *Confirmed.*

**E57 Skin header sizes in files.** Measured as the distance from a skin
node's start to the first model data it owns: 816 bytes (a 192-byte skin
header) in the engine's HD part `pmh0_chest001`; 724 (100) in
`tni_udoor_19` (EE) and BioWare files; 944 (320) in `c_golemerald` and
`c_kocrachn` (older EE). The in-memory skin node has a 64-entry bone list
(+0x320), which the loader's skin branch (0x4bd400) fills with 128 bytes
from node +0x2b0 whatever the file's size: in a 724-byte file, entries 17
onwards come from what follows (stock `tni_udoor_19`: 109 for bone 17, past
its 46-node tree). *Sizes inferred (data); the copy confirmed (code); no
skin golden.*

**E58 Node counts.** Without a supermodel the header node count is the
number of nodes written; an animation's is the number of nodes in its tree.
*Confirmed: every golden.*

**E59 Model header constants.** The game's compiler writes bounding box
(−5, −5, −1)-(5, 5, 10) and radius 7, or radius 40 when the model has an
emitter, whatever the geometry. *Confirmed: every golden.*

**E60 Detonate.** `detonatekey` rows with a time only give column byte 0; a
bare `detonate` line on a geometry emitter gives one key at time 0 with
column byte 0xff (sscanf's -1, stored as the float count by
`AddGenericControllerSingle`, 0x4486f0). *Confirmed: zspec_animfx,
zspec_deton.*

**E61 Emitter header.** The layout of MDL-BIN-041 and the flag bits are
confirmed by two emitters with complementary flags (0x555, 0x2aa); every
emitter controller keyword compiles to the id in the table, static and
keyed. *Confirmed: zspec_emitter, zspec_animfx, zspec_bezier2.*

**E62 Strings.** String fields are NUL-terminated with uninitialised bytes
after the NUL. `NULL` is not special for textures (`bitmap NULL` stores
`NULL`); the supermodel name is `NULL` when there is none. *Confirmed:
zspec_aabb, every golden, goldens/run2.*

**E63 Geometry-node bezier keys.** A `<keyword>bezierkey` list on a geometry
node is stored as a bezier controller with its handles (column byte 0x11
for alpha). *Confirmed: zspec_bezier2.*

## The base game's models (E64, new)

**E64 Corpus survey** (`conformance/tools/scan_stock.py` over
`data/nwn_base.key`, 2026-10-19). 32,832 models, 25,598 of them binary; by
the geometry header's function pointers, 18,874 BioWare (0x40bbc0), 4,786
nwnmdlcomp (0x46ab0c), 1,935 an older EE compiler (4, 0), 3 other.
(Moonglow's scan counted 25,597 binaries and 18,873 BioWare.) On emitters
and lights:
- no emitter uses id 220 or any of 448, 452, 464-466, 468, 472, 480-488;
- no controller anywhere has the bezier bit;
- light id 144 occurs only in EE-compiled files: 1,408 controllers in 665
  models, column byte 1 (e.g. `ptm_candle01n`);
- detonate (228) has column byte 0 (8), 1 (12) and 0xff (6), BioWare only;
- emitter grids: 4 × 4 in 2,795 emitters, 1 × 1 in 2,015, 5 × 5 in 1,136,
  2 × 2 in 563, 0 × 0 in 390, others in the rest (7,099 emitters).

*Confirmed (data); nothing is copied; the counts can be regenerated from
any install.*

## Runtime (E65, new)

**E65 Column counts at runtime.** `NewController::Control` (0x498f20) reads
the low nibble of the column byte (`movzx eax, [rdi+0xa]; and eax, 0xf`)
and handles 1 (`GetFloatValue`, then one `movss` store at the field, 0x498fa8),
3 (vector) and 4 (quaternion slerp); any other count returns without a
write. The field is the one the loader mapped the id to (E36), so a count
below the keyword's width writes only the first floats and leaves the rest
as they are: at reset the constructors' values, `Part::Part` (0x43c800:
position 0, orientation (1, 0, 0, 0) with w first, scale 1),
`PartTriMesh::PartTriMesh` (0x43cb50: selfillumcolor 0, alpha 1 at +0xa0),
`PartLight::PartLight` (0x43d1d0: colour 0 at +0x64, multiplier 1 at +0xa4),
`PartEmitter::PartEmitter` (0x4abfe0: colorEnd +0x78, colorStart +0x84,
colorMid +0x220, all 0). nwnmdlcomp's 0x19 (E64, MDL-CTRL-021) is therefore
skipped. *Confirmed (code); zspec_numbers; two base-game controllers
(`ttf02_m31_03`, `ttf02_s12_01`); on-screen effect not observed.*

## Shaders (E66, new)

**E66 What a shader is given.** `GLRender::ConnectShaderData` (0x4ce8e0)
names a program's inputs. It binds the vertex attribute `vTcIn` (0x4ce92a)
and `vTcIn1` (0x4ce996, attribute location 11: `mov $0xb,%esi` before the
call through `rbx` at 0x4ce99d) among the others. For each texture unit N it
formats the uniform names `texUnit%d` (0x4cf083) and `texture%dBound`
(0x4cf0a6) and stores their locations at +0x1c84 + 4N and +0x1cc4 + 4N; the
loop ends at N = 15 (`cmp $0xf,%r14d`, 0x4cf0e3), so units 0 to 14. The
stock shader includes declare only `vTcIn` and units 0 to 5 (`inc_common`,
with `NORMAL_MAP` ... `SELF_ILLUMINATION_MAP` for 1 to 5), so a custom shader
that reads UV set 1 or a higher unit declares `attribute vec2 vTcIn1;`,
`uniform sampler2D texUnitN;` and `uniform lowp int textureNBound;` itself.
*Confirmed (code for the names, the location and the range). In game: a
tile model whose ground trimesh has `tverts1` (0 to 1 over the tile) and
`materialname` naming an MTR with `customshadervs` / `customshaderfs`,
`texture0` (its colour texture) and `texture7` (a 1 m checkerboard DDS); the
custom vertex shader passes `vTcIn1` on, the fragment shader multiplies by
`texture2D(texUnit7, …)` when `texture7Bound != 0`. The checkerboard showed
on the ground, aligned to the tile, fading with the fog (Layonara
Landscaper's shadow-map shaders, 2026-10-20). So `tverts1` reaches
`vTcIn1` and an MTR's `texture7` reaches `texUnit7`.*
