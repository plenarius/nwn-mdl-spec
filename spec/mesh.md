# Compiling meshes (`MDL-MESH`)

An ASCII mesh indexes positions and UVs separately per face corner; the
binary has one vertex list that every stream shares. This file says how
the engine gets from one to the other, and what else it computes. The
pipeline (`MdlNodeTriMesh::InternalPostProcess`, 0x4577c0; behaviour.md, "Pipeline"):
`ProcessVerts` (normals, bounds) → `InternalGenVertices` (merging,
degenerate faces) → `BuildNeighborLists` → `BuildVertexIndices` →
`GenerateVertexData` → `CalculateTangentSpaceBasis`.

## Vertex merging

**MDL-MESH-010** Each face corner becomes a candidate vertex holding the
face's `mirrorlist` value (low byte, 0 without one), the position, the
normal, UV sets 0-3, the colour, and the tangent and handedness when the
mesh has them; a skin vertex adds its bone names (and weights for unnamed
bones), a danglymesh vertex its constraint, an animmesh vertex its
animation data. Two candidates are the same vertex when all of these are
equal, floats compared with `==` (so -0 equals +0). The material and the
smoothing group are **not** part of the key. *Confirmed: zspec_merge
(`shared`: different groups and materials merge; `uvsplit`: different UVs do
not; `negzero`: -0 and +0 merge; `mirror`: different mirrorlist values do
not); `NodeVertex::operator==` 0x45a300, E2, E3, E16.*

**MDL-MESH-011** Vertices are merged against the whole list: corners are
taken face by face, corner by corner, and each joins the first earlier
vertex it equals or is appended. The vertex order is therefore the order of
first appearance. *Confirmed: every mesh golden (vertex order and count);
`MdlNodeTriMesh::InternalGenVertices` 0x454610, E1.*

**MDL-MESH-012** AABB (walkmesh) nodes merge differently: a corner joins an
existing vertex only through an earlier face that has at least two corners
equal to this face's, the first such face wins, and a face with no such
neighbour gets three new vertices. *Confirmed: zspec_aabb (8 vertices where
a global merge gives 6); `MdlNodeAABB::InternalGenVertices` 0x454920, E1.*

## Degenerate faces and face records

**MDL-MESH-020** After merging, faces are walked from last to first and a
face with two corners on the same vertex is deleted. The vertices it
introduced stay. *Confirmed: zspec_merge (`degen`: 3 faces → 2, 4
vertices); E5.*

**MDL-MESH-021** Each face record's normal and plane distance (`-(n ·
p0)`) are computed on the **source** face list before the deletion, by
position: after a deletion the records from the deleted face onwards hold
the values of the source face of the same index, not their own. A
degenerate source face's normal is the zero vector normalised, (1, 0, 0).
A compiler SHOULD reproduce this; it changes nothing the suite could see in
game. *Confirmed: zspec_merge (`degen`: the second face keeps normal (1, 0,
0), distance -1, from the deleted face); `BuildNeighborLists`, E19.*

**MDL-MESH-022** The face adjacency (three s2 per face, the face sharing the
edge from corner k to k+1, -1 for none) is computed on source vertex indices
in either direction, the lowest face number winning, with the same
source-numbering effect as MDL-MESH-021. The engine recomputes adjacency at
load for walkmeshes (`ComputeTriangleAdjacency` 0x4269a0); what else reads
the stored values is unknown. A compiler SHOULD write them as the engine
does. *Confirmed: zspec_merge, zspec_tanmirror, zspec_aabb (values); E15.*

**MDL-MESH-023** The index list (MDL-BIN-049) holds the surviving faces'
three vertex indices each, in face order, until tangent generation rewrites
it (MDL-MESH-043). *Confirmed: every mesh golden; `BuildVertexIndices`, E4.*

**MDL-MESH-024** The deletion also runs on AABB nodes, but the authored
tree (MDL-MESH-051) is not re-indexed: after a deletion every later leaf
points one face too far, and the last leaf past the end. A compiler MAY
keep degenerate faces on AABB nodes so the tree stays valid, and SHOULD
warn either way. *Confirmed: zspec_aabbdeg (3 faces, tree leaves 0-3);
`MdlNodeAABB::InternalParseField` 0x44dba0, E6. The in-game effect of the
stale tree is not observed.*

## Normals

**MDL-MESH-030** A mesh with `normals` keeps them as written. *Confirmed:
zspec_merge, zspec_tanfile.*

**MDL-MESH-031** Without `normals`, the engine computes one per corner from
the smoothing groups: for corner c of face f at vertex v, it first looks at
earlier faces (lower index) that use v and share a smoothing bit with f; if
one's stored normal n has `dot(face normal of f, n) ≥ -0.99`, c takes n.
Otherwise c sums the area-weighted face normals (unnormalised cross
products) of f and of the later faces that use v and share a bit with f;
the sum is normalised, or, if exactly zero, f's own unit normal is used.
Smoothing group 0 never joins another face. Normalisation is
`Vector::Normalize` (MDL-MESH-032). The result depends on face order.
*Confirmed: zspec_normals (pyramid, back-to-back faces, shared and unshared
bits, unequal areas, group 0); `ProcessVerts` 0x454dd0, E8.*

**MDL-MESH-032** `Vector::Normalize` returns a vector whose squared length is
within 1e-5 of 1 unchanged, turns the zero vector into (1, 0, 0), and
otherwise multiplies by `sqrt(1 / length²)` in float32. A one-ulp
difference splits vertices (MDL-MESH-010), so a compiler that wants the
game's vertex count MUST normalise the same way. *Read in assembly
(0x5b3700, E18); its effect on vertex counts is confirmed on the oracle
fixtures of cleanmodels (not in this repository).*

## Render hints and tangents

**MDL-MESH-040** The render hint field (mesh +116) is what
`SharedMaterial::ExtractRenderHint` (0x4c5410) returns for the mesh's
`renderhint` word, case-insensitively: `NormalAndSpecMapped` 2,
`NormalTangents` 3, `None` 1, anything else 0, no word 0. *Confirmed:
zspec_hints, zspec_hint_mesh.*

**MDL-MESH-041** A mesh with no `renderhint` takes the hint of its material:
the `.mtr` named by `materialname`, or else the `.mtr` named by `bitmap`
(texture 0). The hint field then stays 0, but tangents are generated as for
the material's hint. A compiler MUST look the material up both ways, from
the same places the game would find it (the model's folder in this
suite's runs; in game, the resource manager). *Confirmed: cmtan01
(`materialname`), zspec_mtrbmp (`bitmap`): both hint 0 with tangents.*

**MDL-MESH-042** Tangents are generated only for hints 2 and 3 (from the mesh
or its material), only when the mesh has UVs and normals, and only when the
file gives no tangents. Hint 1, 0 or an unknown word gives none. *Confirmed:
zspec_hints (`None`, `Shiny`: no tangents; `NormalTangents`, lower-case
`normalandspecmapped`: tangents); `CalculateTangentSpaceBasis` 0x457710,
E11.*

**MDL-MESH-043** The tangent of each triangle (p positions, (u, v) UV set 0)
is `t = ((v2 − v0)(p1 − p0) − (v1 − v0)(p2 − p0)) / det` with `det = (u1 −
u0)(v2 − v0) − (u2 − u0)(v1 − v0)`, not normalised, and its handedness w =
+1 if det ≥ 0, else −1. When det = 0, t is the average of the three corner
normals with its components rotated to (y, z, x), and w = +1. Each corner
adds t to its vertex; the first triangle to reach a vertex sets its w; a
later triangle with the other w **clones** the vertex (once per source
vertex and w; the clone copies UVs, normal, colour, constraints and skin
weights), adds to the clone and rewrites that corner in the index list. The
face records keep the old index. Finally each tangent is made orthogonal to
the normal and normalised (`t − n (n · t)`, MDL-MESH-032). Animmesh nodes
overwrite instead of cloning. A vertex no triangle touches keeps
handedness 0. *Confirmed: zspec_hint_mesh, zspec_tanmirror (two clones
appended, index list rewritten, faces not), cmtan01; `FUN_00556190`
(0x456190), E9, E10.*

**MDL-MESH-044** Tangents given in the ASCII (`tangents`, x y z w per
vertex) are stored as written, with w as the handedness. *Confirmed:
zspec_tanfile.*

**MDL-MESH-045** Tangents are written to the slot-3 stream and the
handedness to the slot-5 stream (MDL-BIN-043); there is no bitangent
stream. Without tangents both offsets are 0xffffffff, and the engine
computes tangents at load for normal-mapped materials. *Confirmed: every
mesh golden; E11, E12.*

## Bounds

**MDL-MESH-050** The mesh's bounding box, average and radius are computed
over the **source** vertices (`verts`, before merging): minimum, maximum,
their mean, and the largest distance from the mean. *Confirmed: zspec_merge
(`negzero`, `degen`: the averages include the merged and the unused
vertices); `ProcessVerts`, E13.*

## Walkmesh trees

**MDL-MESH-051** An AABB node's tree is parsed from the ASCII as written
(`aabb` followed by one entry per line, `minx miny minz maxx maxy maxz
face`, preorder, face -1 on inner nodes) and stored entry for entry; the
engine builds no tree of its own. *Confirmed: zspec_aabb, zspec_aabbdeg;
`Parse(char const*, AABB*&)` 0x446ed0, E7.*

**MDL-MESH-052** The engine adds each inner node's plane, from its two
children's box centres: x if |dx| is strictly the largest, else y if |dy|
> |dz|, else z; written as 1 (+X), 2 (+Y) or 4 (+Z), or 8, 16, 32 for the
negative axes when the right child lies on the lower side; a tie is -Z
(32). Leaves have 0. *Confirmed: zspec_aabb (root +X 1; two inner nodes whose
children have equal boxes: 32); the rule as a whole from cleanmodels'
`TestOracleAabbTreeMatchesGame` over its oracle walkmeshes (not in this
repository).*

## Default values

**MDL-MESH-060** A mesh whose ASCII does not give them gets diffuse (1, 1, 1),
ambient (1, 1, 1), specular (0, 0, 0), shininess 1, shadow 1, render 1,
beaming 0, transparencyhint 0, tilefade 0, rotatetexture 0. An AABB node
gets render 0 and shadow 0. A compiler MUST write these defaults; a
decompiler MAY omit a value equal to its default. *Confirmed: every mesh
golden (e.g. zspec_merge), zspec_aabbdef.*

**MDL-MESH-061** A colour stream is stored only when the ASCII has `colors`
(MDL-BIN-080). A decompiler SHOULD write the colours it finds; omitting a
stream in which every vertex is white (255, 255, 255, 255) loses nothing the
default shaders use. *Confirmed: zspec_trimesh. Equivalence of an all-white
stream and none: inferred (the default shaders do not read vertex colours,
Moonglow notes A.4).*

**MDL-MESH-062** An animmesh animation's vertex and texture sets come from
`animverts` and `animtverts`, listed set by set (set 0's vertices, then set
1's, …) over the node's source `verts` and `tverts`: the vertex set count is
the `animverts` count divided by the node's `verts` count, the texture set
count the `animtverts` count divided by its `tverts` count. Each vertex the
merge produces (MDL-MESH-011) takes its source vertex's entries and its
source tvert's, and the merge compares them, so a vertex split by its UVs
carries its sets twice. The sets are stored vertex-major over those merged
vertices (MDL-BIN-045). *Confirmed: zspec_animmesh, zspec_animtv (4 verts and
5 tverts, one vertex split: 5 merged vertices, 3 sets of each kind);
`NodeVertexAnim::operator==` 0x45a550.*

## What shaders read

**MDL-MESH-063** A mesh's UV set 1 (`tverts1`) reaches a shader as the
vertex attribute `vTcIn1`, and a material's `textureN` (N 0 to 10) as the
uniform `texUnitN`, with `textureNBound` non-zero when one is bound. Units 11
to 15 are not named that way: the engine gives them `texFBColor` (11),
`texFBDepth` (12), `texUnitEnvCube` (13), `texUnitEnv` (14) and
`texUnitNoise` (15), each with a bound flag of its own. The stock shader
includes declare only `vTcIn` and units 0 to 5: a custom shader (an MTR's
`customshadervs` / `customshaderfs`) that reads UV set 1 or a unit above 5
MUST declare those inputs itself. *Confirmed: `ConnectShaderData`
0x4ce8e0; the stock `inc_common` shader include; in game, E66.*

## Opaque or blended

**MDL-MESH-064** `transparencyhint` orders meshes (MDL-NODE-012) but does not
make a mesh blended. A visible mesh is drawn blended only when its material
is not opaque: the material's `.mtr` sets `transparency 1`, its blending is
`additive`, or its diffuse texture has alpha (an environment map makes it
opaque). A mesh whose transparency comes only from a custom shader or a
separate mask texture, over a diffuse without alpha (a PLT), MUST name an MTR
with `transparency 1` to be blended. A checker SHOULD warn when a mesh has
transparencyhint > 0 and a material that cannot be blended. *Confirmed:
`PartTriMesh::GetIsOpaque` 0x43cee0, `Material::GetIsOpaque` 0x4c6190,
`SharedMaterial::ParseField` 0x4c6760; in game, E67.*
