# Reconciling cleanmodels, Moonglow and the engine

The tables started from two implementations: cleanmodels v4.9.0
(`pkg/mdl/controllers.go`, `parser.go`) and Moonglow Toolset at e0ed4c4
(`crates/mg-mdl/src/ctrl.rs`, `keywords.rs`, `notes_models.md`). Every point
where they disagreed with each other, or where either disagreed with what
the engine was seen to do, is below with its resolution. "Probe" means the
question was settled by the engine's compile of that probe. Where a later
cleanmodels release changed its column, the cell says since which version.

## Controller IDs

| Item | cleanmodels | Moonglow | Engine (build 89.8193.37-17) | Settled by |
|---|---|---|---|---|
| position 8, orientation 20, scale 36 | same | same | written as listed | zspec_dummy, zspec_anim |
| mesh selfillumcolor 100, alpha 128 | same | same | written as listed | zspec_trimesh, zspec_anim |
| light color 76, radius 88, shadowradius 96, verticaldisplacement 100, multiplier 140 | same | same | written as listed | zspec_light, zspec_animfx |
| light 144 | dropped when decompiling; with a warning up to v4.10.0, an info note since v4.11.0 | `ctrl144` | never written by this build's compiler for any keyword | zspec_light, zspec_animfx: kept as `observed` (seen in older EE-compiled shipped files, value 1.0; meaning unknown) |
| emitter 80-216, 228 | same | same | written as listed | zspec_emitter, zspec_animfx |
| emitter three-stop values 448, 452, 464-466, 468, 472 | same (game ids) | same | written as listed, static, keyed and bezier | zspec_emitter, zspec_bezier2 |
| lightningsubdiv 220 | read when decompiling, not compiled since v4.9.0 | no id | no keyword in the emitter parser; nothing written for it, static or keyed | zspec_emitter, zspec_animfx, E37 |
| opacity | not compiled | listed as a keyword | not read | zspec_emitter |
| detonate column count | -1 ("no values") | 0 in the table; writes column byte 0xff | time-only keys; column byte 0 for `detonatekey` rows, 0xff for a bare static `detonate` | zspec_animfx, zspec_deton |
| nwnmdlcomp emitter ids 464/468/480-488 | read, compiler detected from the ids present | not read (game's reading kept) | the loader has no compiler switch: a 464 is percentStart, a 468 sizeMid | loader 0x4c01b0 (E36); **open**: no nwnmdlcomp binary was made (no nwnmdlcomp here) |
| bezier column byte | 0x10 \| value columns; nwnmdlcomp's 0x19 read too | the same | 0x10 \| value columns | cmbez01, zspec_bezier2, E33 |

## Keywords

| Item | cleanmodels | Moonglow | Engine | Settled by |
|---|---|---|---|---|
| `setfillumcolor` (misspelling) | read as selfillumcolor up to v4.9.0; not read since v4.10.0, with a warning naming selfillumcolor | read as selfillumcolor | **not read** | zspec_setfill |
| `ambient_only`, `fading_light`, `negativelight`, `lensflares` | `ambient_only` read as ambientonly up to v4.9.0; not read since v4.10.0, with a warning | listed as light keywords; `ambient_only` read | not read | zspec_light (lamp_b) |
| `n_dynamic_type`, `affect_dynamic` | — | listed | not in the light parser | 0x44baf0 (inferred, no probe) |
| `texture3` … `texture14` | — | listed | only texture0-2 and bitmap; slot 3 holds `materialname` | 0x44ced0; cmtan01 |
| `lightmapped` | read and written | listed | not read; the binary byte is uninitialised | 0x44ced0; zspec_trimesh and its second compile |
| `filedependency` (spelling) | — | accepted | only `filedependancy`; both are ignored anyway | 0x446330 |
| `classification Tiles` (plural) | 2 (any trailing S trimmed) | 0 | 0 (only `effects` has a plural) | zspec_cls_tiles, zspec_cls_effs |
| `PARENT` (upper case) | read | read | not read: `parent` is case-sensitive; the node drops out of the tree | zspec_numbers |
| `orientation 0 0 0 a` (zero axis) | rotation by a about no axis (w = cos(a/2), xyz 0) | identity | rotation by a about +X | zspec_orient |
| `orientation` with a non-unit axis | axis not normalised | normalised | normalised | zspec_orient |
| hexadecimal floats (`0x1p1`) | rejected (field left at its default) | rejected | read (sscanf) | zspec_numbers (malformed input: SHOULD) |

## Values the engine fills in

| Item | cleanmodels | Moonglow | Engine | Settled by |
|---|---|---|---|---|
| mesh diffuse, ambient, shininess when absent | 0 0 0, 0 0 0, 0 | 1 1 1, 1 1 1, 1 | 1 1 1, 1 1 1, 1 | every mesh probe |
| aabb render, shadow when absent | 1, 1 | 0, 0 | 0, 0 | zspec_aabbdef |
| light lightpriority, nDynamicType, affectdynamic, shadow, fadingLight when absent | 0, 0, 0, 0, 0 | 0, 0, 1, 1, 0 | 5, 1, 1, 1, 1 | zspec_light, zspec_animfx |
| emitter xgrid, ygrid when absent | 0 | 0 | uninitialised (differs between two compiles) | zspec_animfx, zspec_bezier2 with goldens/run2 |
| static controllers for keywords not given | position and orientation always written (orientation as a non-unit quaternion) | position and orientation always written | only the keywords given | every probe |

## Structure

| Item | cleanmodels | Moonglow | Engine | Settled by |
|---|---|---|---|---|
| node numbers (no supermodel) | depth-first order | file order | file order | zspec_nodeorder |
| child order | file order | file order | file order, except that children are sorted (other nodes first, then meshes by transparencyhint) when a child mesh has transparencyhint > 0 | zspec_transp, ReorderChildren 0x458120 |
| supermodel numbering: a name used twice in the supermodel (zspec_kid's `hand`) | -1 | 2 (the name walk) | 2: the name walk down the tree | zspec_kid, zspec_kid2 |
| supermodel numbering: a node the supermodel lacks, under an unmatched parent | supermodel count + 1 + tree position | supermodel count + 1 + declaration index | supermodel count + 1 + declaration index | zspec_kid4 |
| supermodel numbering: header node count | supermodel count + own count + 1 | the same | supermodel count + own count + 1 | zspec_kid, zspec_kid3 |
| skin header size | 192 bytes after the mesh header (816 in all) | 724 or 944 seen; size not relied on | 816 in the engine's HD parts; 724 and 944 in older files | data (E57); **open**: no skin golden yet |
| animmesh animation sets | stored set-major (as ASCII) | written with vertex count 0 in the animation node | vertex-major; the animation node's vertex count sizes the copy | zspec_animmesh, loader 0x4bd400 |
| tangents with mirrored UVs | clones the seam vertex | no clone | clones the seam vertex, rewrites the index list, leaves the face list | zspec_tanmirror |
| tangents from a material named by `bitmap` | generated | not generated (the library compile has no material lookup) | generated | zspec_mtrbmp |
| tangents for an unknown render hint word | none | generated | none | zspec_hints |
| AABB vertex merging | the engine's adjacency scheme | global merge | adjacency scheme | zspec_aabb |
| AABB split plane on a tie | -Z (32) | +X (1) | -Z (32) | zspec_aabb |
| degenerate faces | removed (except on AABB) | kept | removed (also on AABB, leaving a stale tree) | zspec_merge, zspec_aabbdeg |
| `orientationbezierkey` | compiled as linear orientation keys (by choice) | 0x14, 12 values a row | 0x13, rows cut to 9 values, not converted | cmbez01; MDL-CTRL-022 allows either |

The full results of the first run are in
[conformance/reports/](../conformance/reports/).
