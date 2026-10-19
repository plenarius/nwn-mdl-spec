# Binary layout (`MDL-BIN`)

The compiled model, as `nwmain-linux compilemodel` writes it on build
89.8193.37-17. Every offset below is confirmed by decoding all goldens with
[ksy/nwn_mdl.ksy](../ksy/nwn_mdl.ksy) (`ksy/check_ksy.py`), unless a rule
says otherwise. The layout is the 1.69 BioWare layout; EE added no version
field.

## Conventions

**MDL-BIN-001** All values are little-endian. Integers are as given (u1, u2,
u4, s2, s4); floats are IEEE-754 binary32. Vectors are 3 floats (x, y, z).
Structs are packed as listed; raw-data streams may start at any byte
(no alignment). *Confirmed: every golden.*

**MDL-BIN-002** A binary model starts with a 12-byte file header:

| Offset | Type | Field |
|---|---|---|
| 0 | u4 | 0: the binary marker. An ASCII model starts with text, so a reader tells the two apart by these four bytes |
| 4 | u4 | `raw_offset`: the size of the model data |
| 8 | u4 | `raw_size`: the size of the raw data |

The model data follows at file offset 12; the raw data at `12 + raw_offset`,
running to the end of the file. *Confirmed: every golden (the file size is
`12 + raw_offset + raw_size`).*

**MDL-BIN-003** An offset into the model data is a u4 relative to file
offset 12; 0 means none. An offset into the raw data is a u4 relative to
`12 + raw_offset`; 0xffffffff means none and 0 is a valid offset. *Confirmed:
every golden; nwnmdlcomp's CNwnPointer/CNwnPointer2, per Moonglow notes B.2.*

**MDL-BIN-004** An array definition is 12 bytes: u4 offset (model data), u4
count, u4 allocated size. A reader MUST use the count and ignore the
allocated size; when the count is 0 the offset can be anything. *Confirmed:
every golden.*

**MDL-BIN-005** A string field has a fixed size and holds a NUL-terminated
string; the bytes after the NUL are not cleared and differ between two
compiles of the same file. A reader MUST stop at the first NUL. Names are
compared case-insensitively by the engine (`FindMdlNode`, the supermodel
walk). *Confirmed: goldens and goldens/run2 (texture, emitter and
animation-root fields differ after the NUL).*

## The model header

**MDL-BIN-010** The **geometry header** (112 bytes) starts the model header
and every animation header:

| Offset | Type | Field |
|---|---|---|
| 0 | u4[2] | function pointers: runtime values (MDL-BIN-030) |
| 8 | char[64] | name: the model or animation name |
| 72 | u4 | root node (model data offset) |
| 76 | u4 | node count (MDL-NODE-030) |
| 80 | array | runtime array, empty |
| 92 | array | runtime array, empty |
| 104 | u4 | reference count: runtime |
| 108 | u1 | geometry type: 2 model, 5 animation |
| 109 | u1[3] | padding: uninitialised |

*Confirmed: every golden.*

**MDL-BIN-011** The **model header** (232 bytes) is at file offset 12:

| Offset | Type | Field | Written by the game's compiler |
|---|---|---|---|
| 0 | geometry header | | geometry type 2 |
| 112 | u1[2] | unknown | uninitialised |
| 114 | u1 | classification | [tables/classification.yaml](../tables/classification.yaml) |
| 115 | u1 | fog | 1, or 0 when the ASCII says `ignorefog` non-zero |
| 116 | u4 | child model count | 0 |
| 120 | array | animations: model data offsets of animation headers | |
| 132 | u4 | supermodel pointer | 0 (runtime) |
| 136 | vec3 | bounding box minimum | (-5, -5, -1) |
| 148 | vec3 | bounding box maximum | (5, 5, 10) |
| 160 | f4 | radius | 7, or 40 when the model has an emitter |
| 164 | f4 | animation scale | `setanimationscale`, default 1 |
| 168 | char[64] | supermodel name | `NULL` when there is none |

*Confirmed: every golden (bounds and radius in all 40; radius 40 in the four
probes with an emitter, 7 in the others); zspec_cls_* for classification and
fog.*

**MDL-BIN-012** A compiler MUST write classification, fog, animation scale
and supermodel name as above. It SHOULD write the bounds and radius as the
game does; what the engine uses them for was not read. *Confirmed (values):
every golden.*

## Nodes

**MDL-BIN-020** A **node** is a 112-byte header followed by the sub-headers
its flags name, in flag-bit order (light, emitter, reference, mesh, skin,
anim, dangly, aabb):

| Offset | Type | Field |
|---|---|---|
| 0 | u4[6] | function pointers: runtime (MDL-BIN-030) |
| 24 | u4 | inheritcolor |
| 28 | s4 | part number (MDL-NODE-010) |
| 32 | char[32] | name |
| 64 | u4 | geometry header pointer: runtime |
| 68 | u4 | parent pointer: runtime |
| 72 | array | children: model data offsets of child nodes, in tree order (MDL-NODE-011) |
| 84 | array | controller keys, 12 bytes each (MDL-CTRL-001) |
| 96 | array | controller data, floats |
| 108 | u4 | flags ([tables/node_flags.yaml](../tables/node_flags.yaml)) |

The flags are the only reliable type tag. Sub-header sizes: light 92,
emitter 216, reference 68, mesh 512, skin 192 (MDL-BIN-061), anim 56,
dangly 24, aabb 4. *Confirmed: every golden; node flags of every ASCII node
type in zspec_nodetypes, zspec_light, zspec_emitter, zspec_reference,
zspec_dangly, zspec_animmesh, zspec_aabb.*

**MDL-BIN-021** The node tree is read from the root (geometry header +72)
through the children arrays. A reader MUST NOT rely on the parent pointer
or the geometry header pointer: they hold runtime values. *Confirmed:
goldens and goldens/run2 (node +64 and +68 differ between two compiles).*

**MDL-BIN-030** These fields hold runtime values or uninitialised memory in
the game's output and differ between two compiles of the same ASCII: all
function pointers (geometry header +0, node +0, mesh header +0), node +64
and +68, geometry header +104 and +109, model header +112, the controller
key pad byte, the 3 bytes after the mesh triangle mode, the mesh
`lightmapped` byte, the string bytes after a NUL, and bytes of the model
data that nothing points to (zspec_reference has heap data after its last
node). A reader MUST ignore them. A compiler SHOULD write zeros there; the game's own files show it does
not care. *Confirmed: byte comparison of goldens/ with goldens/run2 (the
second compile of every probe).*

## Sub-headers

**MDL-BIN-040** **Light** (92 bytes):

| Offset | Type | Field |
|---|---|---|
| 0 | f4 | flare radius |
| 4 | array | unknown, empty |
| 16 | array | flare sizes (f4) |
| 28 | array | flare positions (f4) |
| 40 | array | flare colour shifts (vec3) |
| 52 | array | flare textures: offsets of NUL-terminated names |
| 64 | u4 | light priority |
| 68 | u4 | ambient only |
| 72 | u4 | dynamic type (`nDynamicType`, `isdynamic`) |
| 76 | u4 | affect dynamic |
| 80 | u4 | shadow |
| 84 | u4 | generate flare |
| 88 | u4 | fading light |

Colour, radius, multiplier, shadow radius and vertical displacement are
controllers. *Confirmed: zspec_light.*

**MDL-BIN-041** **Emitter** (216 bytes):

| Offset | Type | Field |
|---|---|---|
| 0 | f4 | deadspace |
| 4 | f4 | blast radius |
| 8 | f4 | blast length |
| 12 | u4 | x grid |
| 16 | u4 | y grid |
| 20 | u4 | spawn type |
| 24 | char[32] | update |
| 56 | char[32] | render |
| 88 | char[32] | blend |
| 120 | char[64] | texture |
| 184 | char[16] | chunk name |
| 200 | u4 | two-sided texture |
| 204 | u4 | loop |
| 208 | u2 | render order |
| 210 | u2 | padding |
| 212 | u4 | flags: 0x1 p2p, 0x2 p2p_sel, 0x4 affectedByWind, 0x8 m_isTinted, 0x10 bounce, 0x20 random, 0x40 inherit, 0x80 inheritvel, 0x100 inherit_local, 0x200 splat, 0x400 inherit_part |

Every other emitter parameter is a controller. *Confirmed: zspec_emitter
(two emitters with complementary flag patterns, 0x555 and 0x2aa).*

**MDL-BIN-042** **Reference** (68 bytes): char[64] ref model, u4
reattachable. *Confirmed: zspec_reference.*

**MDL-BIN-043** **Mesh** (512 bytes, after the node header and any light,
emitter or reference header):

| Offset | Type | Field |
|---|---|---|
| 0 | u4[2] | function pointers: runtime |
| 8 | array | faces (32 bytes each, MDL-BIN-044) |
| 20 | vec3 | bounding box minimum (MDL-MESH-050) |
| 32 | vec3 | bounding box maximum |
| 44 | f4 | radius |
| 48 | vec3 | average (centroid) |
| 60 | vec3 | diffuse |
| 72 | vec3 | ambient |
| 84 | vec3 | specular |
| 96 | f4 | shininess |
| 100 | u4 | shadow |
| 104 | u4 | beaming |
| 108 | u4 | render |
| 112 | u4 | transparency hint |
| 116 | u4 | render hint ([tables/render_hints.yaml](../tables/render_hints.yaml)) |
| 120 | char[64] | texture 0 (`bitmap`, `texture0`) |
| 184 | char[64] | texture 1 |
| 248 | char[64] | texture 2 |
| 312 | char[64] | texture 3: the `materialname` |
| 376 | u4 | tile fade |
| 380 | array | vertex indices (strips): empty |
| 392 | array | leftover faces: empty |
| 404 | array | index list counts (u4): one entry, 3 × triangles |
| 416 | array | index list offsets (u4, raw data): one entry |
| 428 | u4 | unknown offset: 0xffffffff |
| 432 | u4 | unknown count: 0 |
| 436 | u1 | triangle mode: 3 |
| 437 | u1[3] | padding: uninitialised |
| 440 | u4 | temporary mesh data: runtime |
| 444 | u4 | positions (raw data, vec3 per vertex) |
| 448 | u2 | vertex count |
| 450 | u2 | texture count: the number of UV sets |
| 452 | u4[4] | UV sets 0-3 (raw data, 2 floats per vertex) |
| 468 | u4 | normals (raw data, vec3 per vertex) |
| 472 | u4 | colours (raw data, 4 bytes per vertex: r, g, b, a) |
| 476 | u4[3] | texture animation slots 0-2: none |
| 488 | u4 | texture animation slot 3: **tangents** (vec3 per vertex) |
| 492 | u4 | texture animation slot 4: none |
| 496 | u4 | texture animation slot 5: **handedness** (f4 per vertex, ±1) |
| 500 | u1 | lightmapped: uninitialised (MDL-BIN-051) |
| 501 | u1 | rotate texture |
| 502 | u2 | padding |
| 504 | f4 | normal sum: not compared |
| 508 | u4 | unknown |

*Confirmed: every mesh golden. Tangent and handedness slots: zspec_hint_mesh,
zspec_tanmirror, zspec_tanfile, cmtan01 (finding E12 for the runtime pool).*

**MDL-BIN-044** A **face** is 32 bytes: vec3 normal, f4 plane distance
(`-(normal · p0)`), u4 material (the surfacemat.2da row for walkmeshes),
s2[3] adjacent faces (-1 none), u2[3] vertex indices. *Confirmed: every
mesh golden; values per MDL-MESH-021.*

**MDL-BIN-045** **Anim** (animmesh, 56 bytes): f4 sample period, three
empty arrays (36 bytes), u4 vertex sets offset (model data), u4 texture
sets offset (model data), u4 vertex set count, u4 texture set count. The
sets hold `vertex count × set count` entries (vec3, and 2 floats for
texture sets) stored **vertex-major**: entry `vertex × sets + set`. The
geometry node carries counts of 0; the sets are on the animation's node,
whose own mesh header MUST carry the vertex count: the loader copies
`vertex count × sets` entries using the animation node's vertex count
(+448). *Confirmed: zspec_animmesh; the loader's animmesh branch
(0x4bd400, `FUN_005bd400` in Ghidra) reads the count at node +0x230.*

**MDL-BIN-046** **Dangly** (24 bytes): array of f4 constraints (one per
vertex), f4 displacement, f4 tightness, f4 period. *Confirmed: zspec_dangly.*

**MDL-BIN-047** **AABB** (4 bytes): u4 offset of the root tree entry. An
entry is 40 bytes: vec3 minimum, vec3 maximum, u4 left child, u4 right
child (0 on leaves), s4 face (-1 on inner nodes), u4 plane (MDL-MESH-052).
Entries follow in preorder. *Confirmed: zspec_aabb, zspec_aabbdef,
zspec_aabbdeg.*

**MDL-BIN-048** The tangent and handedness slots (mesh +488, +496) hold
another stream in 1.69 models: water meshes' bump-map animation (stock
`tcn01_a15_01`, node `Plane452`, 3.08e-36 …). A reader SHOULD read slot 3
as tangents when the render hint is 2 or 3, or when every vector in it is
unit length (squared length within 0.02 of 1), and otherwise as
something else. The game's compiler writes render hint 0 for meshes whose
hint comes from a material, with real tangents (cmtan01, zspec_mtrbmp), so
the hint alone cannot decide. *Confirmed: cmtan01, zspec_mtrbmp; stock data
(582 of the base game's binary meshes carry the bump-map stream, per
cleanmodels DECOMPILE.md).*

**MDL-BIN-049** The engine draws the **index list** (mesh +404/+416), not the
face list: the loader copies the index buffer from the raw data and the
face records separately (E31). The two agree except after tangent
generation cloned vertices (MDL-MESH-043), where only the index list
refers to the clones. A reader that rebuilds triangles MUST use the index
list when there is one. *Confirmed: zspec_tanmirror (index list
`0 1 2 0 2 3 6 4 5 6 5 7`, faces still `1 4 5`, `1 5 2`); E31.*

## Uninitialised fields

**MDL-BIN-050** Besides MDL-BIN-030, the game's output holds uninitialised
memory in the type-specific headers of **animation** nodes (mesh, emitter
and light headers there), and in the fields named in MDL-BIN-051 and
MDL-BIN-052. A reader MUST NOT use an animation node's sub-headers except
the anim header and the mesh vertex count of an animmesh node (MDL-BIN-045).
*Confirmed: goldens/run2 (zspec_anim's mesh triangle mode, cmbez01's emitter
grid differ in animation nodes).*

**MDL-BIN-051** The mesh `lightmapped` byte (+500) is not read from the
ASCII (no `lightmapped` keyword in `MdlNodeTriMesh::InternalParseField`,
0x44ced0) and is uninitialised in the game's output. *Confirmed: 0x44ced0
strings; goldens and goldens/run2.*

**MDL-BIN-052** An emitter whose ASCII has no `xgrid` or `ygrid` gets
uninitialised values there (two compiles differ). A compiler SHOULD write a
defined value; the base game's binary emitters use 1 × 1 (2,015 of 7,099)
and 0 × 0 (390) for single-frame textures, so either looks safe. What the
engine's own load of such an ASCII emitter does with the garbage was not
observed. *Confirmed (uninitialised): zspec_animfx, zspec_bezier2 and their
run2 compiles; stock counts from a scan of the install (E64). The value to
write is a recommendation, not engine behaviour.*

## Skin

**MDL-BIN-060** **Skin** (after the mesh header):

| Offset | Type | Field |
|---|---|---|
| 0 | array | weights: compiler temporary, empty |
| 12 | u4 | weights (raw data): 4 f4 per vertex |
| 16 | u4 | bone references (raw data): 4 s2 per vertex, an index into the bone list below |
| 20 | u4 | bone map (model data): s2 per tree position, its bone index or -1 (`boneindexarray`) |
| 24 | u4 | bone map count: the size of the tree the skin is bound to (MDL-SKIN-021) |
| 28 | array | `qbone_ref_inv`: one quaternion per tree position, stored w, x, y, z |
| 40 | array | `tbone_ref_inv`: one vec3 per tree position |
| 52 | array | bone constant indices: one u4 per tree position, uninitialised (E27) |
| 64 | s2[64] | bone list: the tree position of each bone; unused slots 0 (E25) |

*Inferred from the engine's HD parts and cleanmodels' layout (E57); no skin
golden yet: `compilemodel` needs a creature on screen to compile a skin.*

**MDL-BIN-061** Skin headers of three sizes exist in game files: 192 bytes
(the EE compiler's HD parts, `pmh0_chest001`), 100 bytes (BioWare 1.69 and
some EE files: a 17-entry bone list and one more word used as an 18th slot,
`c_halaster`, `tni_udoor_19`) and 320 bytes (older EE builds: 256 bytes after the
arrays, the bone list at their start and zeros after it, `c_golemerald`,
`c_kocrachn`). No field tells them apart. A reader
MUST find the skin's data through its offsets and MUST NOT index the bone
list with a bone that no vertex references. Nothing follows the skin header
in a node, so a reader need not know its size. *Inferred from data (first
data offset after each skin node, measured in the named stock files; not
copied here).*

## Animations

**MDL-BIN-070** An **animation header** (196 bytes): geometry header (type
5; its root is the animation's own node tree), f4 length, f4 transition
time, char[64] animation root, array of events. An event is 36 bytes: f4
time, char[32] name. *Confirmed: zspec_anim.*

**MDL-BIN-071** An animation's nodes are full node structs with the flags
of the geometry node of the same name (a trimesh in an animation is
`0x21` with a mesh header). Only their name, part number, children,
controllers and, for animmesh nodes, the anim header and the vertex count
are meaningful (MDL-BIN-050). *Confirmed: zspec_anim, cmbez01,
zspec_animmesh; behaviour.md, "Animation blocks".*

## Vertex colours

**MDL-BIN-080** Colours are 4 bytes per vertex, r, g, b, a; the game's
compiler writes alpha 255 and `round(c × 255)` for each ASCII component (1 →
255). A colour stream is written only when the ASCII has `colors`.
*Confirmed: zspec_trimesh (colours `1 0 0` → `255 0 0 255`); other mesh
goldens have none.*
