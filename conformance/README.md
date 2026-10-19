# Conformance suite

Probe models, the game's compile of each, and the expected data. All CC0.

| Folder | What |
|---|---|
| [probes/](probes/) | ASCII probes (and the `.mtr` materials two of them use) |
| [goldens/](goldens/) | `nwmain-linux compilemodel` of each probe, build 89.8193.37-17 |
| [goldens/run2/](goldens/run2/) | a second compile of each, to find the uninitialised fields |
| [expected/](expected/) | the decoded, tool-neutral view of each golden, with its volatile fields listed |
| [manifest.json](manifest.json) | each probe: what it isolates, the rules it supports, companion files, relaxations |
| [stock.yaml](stock.yaml) | stock models tested by name (extracted from your install at run time) |
| [reports/](reports/) | the first run's results for cleanmodels and Moonglow |
| [tools/](tools/) | `make_goldens.py` (headless golden maker), `scan_stock.py` (corpus survey) |

## The probes

| Probe | Isolates | Rules | |
|---|---|---|---|
| `cmbez01` | every float and colour bezier controller on a mesh, light and emitter, and orientationbezierkey | MDL-CTRL-020, MDL-CTRL-022, MDL-CTRL-032 | golden |
| `cmtan01` | a mesh with no renderhint whose materialname names an .mtr with a normal-mapped hint | MDL-MESH-041, MDL-BIN-048 | golden |
| `zspec_aabb` | an AABB walkmesh: face materials, the authored tree, split planes, the adjacency merge | MDL-MESH-012, MDL-MESH-051, MDL-MESH-052, MDL-BIN-047 | golden |
| `zspec_aabbdef` | an AABB walkmesh with no render or shadow line | MDL-MESH-060 | golden |
| `zspec_aabbdeg` | an AABB walkmesh with a degenerate face: deleted, tree not re-indexed | MDL-MESH-024 | golden |
| `zspec_anim` | linear key lists (counted, endlist, empty line inside), events, transtime, animroot, a single value in an animation | MDL-CTRL-031, MDL-CTRL-035, MDL-ASCII-050, MDL-ASCII-060, MDL-NODE-040, MDL-NODE-042 | golden |
| `zspec_animfx` | linear keys on a light and an emitter, detonate, lightningsubdivkey | MDL-CTRL-012, MDL-CTRL-013, MDL-CTRL-002 | golden |
| `zspec_animmesh` | an animmesh animation: sample period, vertex and texture sets | MDL-BIN-045, MDL-MESH-062, MDL-ASCII-061 | golden |
| `zspec_bezier2` | position, shadowradius, verticaldisplacement, colorMid, sizeStart_y and percentEnd bezier keys; a bezier key list on a geometry node | MDL-CTRL-020, MDL-CTRL-023 | golden |
| `zspec_cls_door` | classification door, ignorefog 1 | MDL-ASCII-021, MDL-ASCII-022 | golden |
| `zspec_cls_effs` | classification Effects (plural) | MDL-ASCII-021 | golden |
| `zspec_cls_gui` | classification gui, ignorefog 0 | MDL-ASCII-021, MDL-ASCII-022 | golden |
| `zspec_cls_item` | classification item | MDL-ASCII-021 | golden |
| `zspec_cls_tile` | classification TILE (upper case) | MDL-ASCII-021 | golden |
| `zspec_cls_tiles` | classification Tiles (plural) | MDL-ASCII-021 | golden |
| `zspec_crlf` | zspec_dummy with CRLF line ends | MDL-ASCII-001 | golden |
| `zspec_dangly` | danglymesh displacement, tightness, period, constraints | MDL-BIN-046 | golden |
| `zspec_dummy` | model header fields; position, orientation, scale, inheritcolor | MDL-BIN-011, MDL-CTRL-003, MDL-CTRL-030 | golden |
| `zspec_emitter` | every emitter header field and flag, every static emitter controller, lightningsubdiv and opacity | MDL-BIN-041, MDL-CTRL-002, MDL-CTRL-013 | golden |
| `zspec_hint_mesh` | renderhint NormalAndSpecMapped: generated normals and tangents | MDL-MESH-040, MDL-MESH-042, MDL-MESH-043 | golden |
| `zspec_hints` | renderhint None, NormalTangents, an unknown word, lower case | MDL-MESH-040, MDL-MESH-042 | golden |
| `zspec_kid` | numbering against a supermodel; a name the supermodel uses twice; a node it lacks; the node count | MDL-NODE-020, MDL-NODE-021, MDL-NODE-030, MDL-NODE-040 | golden |
| `zspec_kid2` | the supermodel name walk: case, a duplicate name under a different parent, a name under the wrong parent | MDL-NODE-020, MDL-NODE-021 | golden |
| `zspec_kid3` | the node count with a supermodel (second data point) | MDL-NODE-030 | golden |
| `zspec_light` | every light header field, flares, static light controllers; light spellings the engine does not read | MDL-BIN-040, MDL-ASCII-070, MDL-CTRL-011 | golden |
| `zspec_merge` | vertex merging: groups and materials, UV splits, -0, degenerate faces, mirrorlist | MDL-MESH-010, MDL-MESH-011, MDL-MESH-020, MDL-MESH-021, MDL-MESH-050 | golden |
| `zspec_mtrbmp` | a mesh whose bitmap names an .mtr with a normal-mapped hint | MDL-MESH-041 | golden |
| `zspec_nodeorder` | nodes declared out of depth-first order: numbers and child order | MDL-NODE-010, MDL-NODE-011 | golden |
| `zspec_nodetypes` | camera, an unknown type word, mixed-case type words | MDL-ASCII-030 | golden |
| `zspec_normals` | normal generation from smoothing groups | MDL-MESH-031 | golden |
| `zspec_numbers` | malformed numbers and words: hex floats, trailing junk, comma decimals, 1.#INF, TRUE/false, PARENT | MDL-ASCII-040, MDL-ASCII-041, MDL-ASCII-031, MDL-NODE-012 | golden (lenient) |
| `zspec_numfmt` | well-formed number forms, tabs, comments, keyword case | MDL-ASCII-001, MDL-ASCII-003, MDL-ASCII-010, MDL-ASCII-040 | golden |
| `zspec_orient` | the orientation keyword: zero axis, zero angle, non-unit axis, negative and large angles | MDL-ASCII-032 | golden |
| `zspec_reference` | reference nodes | MDL-BIN-042 | golden |
| `zspec_setfill` | the misspelling setfillumcolor next to selfillumcolor | MDL-ASCII-070 | golden |
| `zspec_skin` | a whole-model skin weighted to two bones | MDL-SKIN-001, MDL-SKIN-013 | pending |
| `zspec_super` | the supermodel for zspec_kid*: a name used twice | MDL-NODE-021 | golden |
| `zspec_tanfile` | tangents given in the file with a normal-mapped hint | MDL-MESH-044 | golden |
| `zspec_tanmirror` | tangent generation across a UV mirror seam: vertex clones | MDL-MESH-043, MDL-BIN-049 | golden |
| `zspec_transp` | child order when a child mesh has transparencyhint > 0 | MDL-NODE-012, MDL-NODE-013 | golden |
| `zspec_trimesh` | trimesh material fields, two UV sets, vertex colours, static selfillumcolor and alpha | MDL-BIN-043, MDL-BIN-080, MDL-MESH-060 | golden |

`cmbez01` and `cmtan01` were written for cleanmodels' and Moonglow's
comparison in October 2026 by the same author, and moved here.

## The JSON view

Both the expected files and the runner's decoding of an implementation's
output use one shape (`runner/mdlview.py`):

- `model`: `name`, `classification` (the byte), `fog` (the byte),
  `animationscale`, `supermodel` (`NULL` for none), `node_count`, and the
  header's `bmin`, `bmax`, `radius`.
- `nodes`: depth-first, each with `name`, `parent`, `type`, `flags`,
  `number` (part number), `inheritcolor`, `controllers`, and per type:
  - `controllers`: `id`, `name`, `columns`, `bezier`, `colbyte`, `keys`
    (`t`, `v`, and `in`/`out` for bezier keys); orientation values are
    quaternions x, y, z, w;
  - `mesh`: material fields, `renderhint`, `textures` (slots 0-3),
    `vertex_count`, `face_count`, `vertices` (`position`, `uv0`-`uv3`,
    `normal`, `color` as bytes, `tangent`, `handedness`), `faces` (`v`,
    `material`, `normal`, `distance`, `adjacent`), `index_lists`, bounds;
  - `light`, `emitter`, `reference`, `dangly`, `aabb` (preorder entries),
    `animmesh` (sets in ASCII order: set by set), `skin` (weights per
    vertex by bone name, bone map, bind lists).
- `animations`: `name`, `length`, `transtime`, `animroot`, `events`,
  `node_count`, `nodes` (name, parent, type, flags, number, controllers,
  animmesh).

Floats are written as the shortest decimal that reads back to the same
float32. An expected file adds `probe`, `build`, `golden_sha256` and
`volatile`: the paths whose values differed between the two engine compiles
(MDL-BIN-030, MDL-BIN-052), which are never compared.

## What is compared

A **compile** test runs the implementation on the probe (with its companion
files next to it), decodes the binary and compares it with the expected
file. MUST checks: the model header fields, the tree (names, parents, order,
flags, part numbers), every controller (id, columns, bezier, keys within
1e-5 relative), light, emitter, reference, dangly, AABB and animmesh data,
mesh material fields, vertex and face counts, and every drawn corner's
position, UVs, normal (1e-4), colour and tangent (1e-3) with its handedness
sign. SHOULD checks: bounds, face normals, distances and adjacency, the
vertex order, the column byte of bezier controllers, and controllers the
golden lacks or has whose value is the default.

A **decompile** test runs the implementation on the golden, reads its ASCII
the way the engine would (`runner/mdlview.py`, following spec/ascii.md) and
compares the same data, except what an ASCII cannot carry (part numbers,
vertex order, bounds). Missing tangents and extra controllers are SHOULD.

Corners are compared through the index list (what the game draws,
MDL-BIN-049), so an implementation is free to number vertices its own way
as long as each drawn corner carries the same data; the vertex count is
still checked for compiles.

Relaxations, each tied to a rule, are in the manifest: `lenient` (the probe
is malformed input, every check is SHOULD) and `allow` (a path where the
spec lets an implementation differ from the engine).

## Making goldens

See [CONTRIBUTING.md](../CONTRIBUTING.md#probes-and-goldens). The skin
probe is pending: `compilemodel` needs a creature using the model on screen.

## Stock models

`python3 runner/mdlconf.py stock --impl NAME --cmd COMMAND` extracts each
model in [stock.yaml](stock.yaml) from your install, has the implementation
decompile it, and compares the ASCII with the runner's decoding of the
binary. Nothing from the game is stored in this repository.
