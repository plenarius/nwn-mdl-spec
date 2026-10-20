# Conformance reports: cleanmodels and Moonglow (2026-10-19)

- **cleanmodels v4.11.0** (1d740cb), **v4.10.0** (faf1af3) and **v4.9.0**
  (55a9df3), the published Linux builds, through
  `runner/adapters/cleanmodels.sh`. v4.10.0 was written against these
  results; v4.9.0 is kept for comparison. v4.11.0 (2026-10-20) changed what
  cleanmodels reports, not what it writes, and gives the same results as
  v4.10.0 on every probe, SHOULD notes included.
- **Moonglow Toolset** at e0ed4c4 (`crates/mg-mdl`, unchanged since 1.33.0),
  through `runner/adapters/moonglow/` (`mg_mdl::compile::compile_named` with
  supermodels looked up next to the input, and `mg_mdl::decompile`).
- Suite at this commit (46 probes with goldens, after zspec_kid4,
  zspec_tsort24/50/90, zspec_animtv and zspec_deton were added); engine build
  89.8193.37-17.

Full results for the probes: `<impl>.txt` (readable, MUST and SHOULD) and
`<impl>.json`. The stock-model results are summarised here only: their
details quote the game's own model data, which does not belong in this
repository; `mdlconf.py stock` regenerates them from any install.

| | compile | decompile | stock decompile |
|---|---|---|---|
| cleanmodels v4.11.0 | 46 pass | 46 pass | 14 pass |
| cleanmodels v4.10.0 | 46 pass | 46 pass | 14 pass |
| cleanmodels v4.9.0 | 7 pass, 39 fail | 42 pass, 4 fail | 12 pass, 2 fail |
| Moonglow e0ed4c4 | 27 pass, 19 fail | 44 pass, 2 fail | 13 pass, 1 fail |

(46 probes with goldens; `zspec_skin` pending. A probe fails on any MUST
check; most failing probes fail on one or two causes, listed below.)

The tables below describe cleanmodels v4.9.0 and Moonglow e0ed4c4; v4.10.0
and v4.11.0 fail none of their MUST checks. What it still reports at SHOULD level is
listed at the end.

## Where both differ from the engine

| Behaviour | Rule | Probes |
|---|---|---|
| `setfillumcolor` compiled as self-illumination; the engine does not read it | MDL-ASCII-070 | zspec_setfill |
| `ambient_only` read as `ambientonly`; the engine does not read it | MDL-ASCII-070 | zspec_light |
| light defaults: lightpriority 0 (engine 5), dynamic type 0 (1), fadingLight 0 (1); cleanmodels also affectdynamic and shadow 0 (1) | MDL-MESH-060 note; E50 | zspec_light, zspec_animfx, zspec_bezier2, zspec_transp |
| `orientation 0 0 0 a`: cleanmodels writes (0, 0, 0, cos(a/2)), Moonglow the identity; the engine a rotation about +X | MDL-ASCII-032 | zspec_orient |
| children not reordered when a child mesh has transparencyhint > 0 | MDL-NODE-012 | zspec_transp, zspec_tsort24, zspec_tsort50, zspec_tsort90 |
| a bezier key list on a geometry node is not compiled at all (the mesh loses its alpha) | MDL-CTRL-023 | zspec_bezier2 |
| animmesh animation sets: cleanmodels stores them set-major and writes them back to ASCII in vertex-major order; Moonglow writes the animation node with vertex count 0, so the loader copies nothing; neither lays them out over the merged vertices | MDL-BIN-045, MDL-MESH-062 | zspec_animmesh, zspec_animtv |
| `detonate` with column byte 0xff dropped when decompiling | MDL-CTRL-012 | zspec_deton, stock `vwp_flash_blured` |

## cleanmodels only

| Behaviour | Rule | Probes |
|---|---|---|
| mesh defaults: diffuse and ambient (0, 0, 0), shininess 0 (engine 1, 1, 1 and 1); animmesh shadow 0 | MDL-MESH-060 | every mesh probe |
| AABB node with no render line: render 1 (engine 0) | MDL-MESH-060 | zspec_aabbdef |
| a geometry node with no `orientation` gets orientation (0, 0, 0, 0.878), a non-unit quaternion, where the engine writes none (harmless for a static matrix, inferred) | MDL-CTRL-033, MDL-ASCII-032 | 29 probes |
| `orientation` with a non-unit axis not normalised | MDL-ASCII-032 | zspec_orient |
| part numbers in depth-first order, not declaration order | MDL-NODE-010 | zspec_nodeorder |
| a supermodel name used twice (`hand`): -1, where the engine's walk gives 2 | MDL-NODE-021 | zspec_kid |
| a node under an unmatched parent numbered by its position in the tree, not its declaration index | MDL-NODE-020 | zspec_kid4 |
| a static `detonate` line on a geometry emitter not compiled | MDL-CTRL-012 | zspec_deton |
| `classification Tiles` → 2 (engine 0) | MDL-ASCII-021 | zspec_cls_tiles |
| decompile reads three floats from a one-column position controller (what follows in the pool lands in y, z; the engine writes x only) | MDL-CTRL-014 | zspec_numbers (decompile) |
| a 100-byte skin header read as 64 bone entries: the garbage entry makes it treat the skin as skeleton-bound and drop every bone | MDL-BIN-061, MDL-SKIN-040 | stock `tni_udoor_19` |

## Moonglow only

| Behaviour | Rule | Probes |
|---|---|---|
| no material lookup in the library's compile: material-hinted meshes get no tangents | MDL-MESH-041 | cmtan01, zspec_mtrbmp |
| no tangent clone at a UV mirror seam | MDL-MESH-043 | zspec_tanmirror |
| degenerate faces kept; -0 and +0 not merged; `mirrorlist` ignored | MDL-MESH-010, MDL-MESH-020 | zspec_merge |
| normal generation differs from the engine's (back-to-back faces, shared smoothing bits) | MDL-MESH-031 | zspec_normals |
| AABB nodes merged globally instead of by adjacency; split plane +X (1) on a tie where the engine writes -Z (32) | MDL-MESH-012, MDL-MESH-052 | zspec_aabb, zspec_aabbdef, zspec_aabbdeg |

## Reported, not failed (SHOULD)

- Both write position and orientation controllers with default values where
  the engine writes none (MDL-CTRL-033). cleanmodels writes the model's real
  bounds and radius in the model header where the engine writes fixed values
  (MDL-BIN-012); Moonglow writes the engine's values.
- `orientationbezierkey`: cleanmodels compiles linear keys, Moonglow 0x14
  with 12 values; the engine 0x13 (MDL-CTRL-022 allows either).
- Moonglow generates tangents for an unknown render hint word (`Shiny`), and
  writes keyed detonate with column byte 0xff where the engine writes 0 (for
  a static `detonate` 0xff is the engine's byte: zspec_deton).
- cleanmodels keeps degenerate AABB faces (MDL-MESH-024 allows it) and
  decompiles cloned tangent vertices through the face list, so the clones'
  tangents come out wrong (MDL-BIN-049).
- Moonglow omits all-white vertex colour streams when decompiling
  (MDL-MESH-061), and rebuilds `tni_udoor_19`'s out-of-tree bone from the
  bone map (spec/unknown.md).
- On the malformed probe zspec_numbers (lenient), both read hexadecimal floats
  as invalid, keep the `PARENT` node, and differ from the engine on trailing
  junk.

## cleanmodels v4.10.0 and v4.11.0: reported, not failed (SHOULD)

- Position and orientation controllers with their default values on nodes
  whose source has no such line (MDL-CTRL-033); kept on purpose.
- The model's real bounds and radius in the model header where the engine
  writes fixed values (MDL-BIN-012), and a walkmesh's mesh radius and centre
  computed with its degenerate faces kept (MDL-MESH-024 allows keeping them).
- One-column controllers from malformed lines (zspec_numbers) written at
  full width, which gives the same runtime values (MDL-CTRL-014).
- `orientationbezierkey` compiled as linear keys (MDL-CTRL-022 allows it).
- Decompile: zero-valued emitter mid and percent controllers written where
  the golden has none; cloned tangent vertices read through the face list
  (MDL-BIN-049); the face records after a deleted degenerate face differ
  (zspec_merge, MDL-MESH-021).
