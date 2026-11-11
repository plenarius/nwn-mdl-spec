# Changelog

The spec is tagged per engine build. Each entry says which build it was
read on and what changed in the engine's behaviour since the last one.

## Unreleased (build 89.8193.37-17)

First draft:
- tables: controller ids per node class, node flags, keywords per parser,
  render hints, classification; reconciled from cleanmodels v4.9.0 and
  Moonglow e0ed4c4 and checked against the engine;
- 41 probes, 40 with engine goldens (compiled twice), expected JSON for
  each; the skin probe is pending an in-game rig;
- spec text for the binary layout, controllers, the ASCII format, meshes,
  node numbering and skins, with rule IDs; engine findings E1-E64;
- a standard-library runner, adapters for cleanmodels and Moonglow, stock
  tests by name, and the first reports;
- a Kaitai Struct description, checked by decoding every golden with the
  suite's own interpreter.

Added:
- MDL-MESH-065 (new probe zspec_animnrm): an animation's animmesh node is a
  mesh of its own, and the game's compiler reads its `normals`. Given, they
  are kept as written and the node keeps the geometry node's 4 vertices;
  left out, they are computed from that node's smoothing groups, and the
  animation node splits to 6 against the geometry node's 4. cleanmodels
  (main, 3003980) drops them in compile and decompile: its compile of the
  probe splits the node to 6 vertices, as it splits Layonara's
  `vff_explword*` models from 40 to 48. MDL-BIN-050 now lets a reader use
  an animmesh animation node's mesh header (stable in both compiles,
  except `lightmapped`); MDL-ASCII-061 says to repeat the normals.
- MDL-CTRL-036 (new probe zspec_dupctrl): a single-value controller line
  given twice in a node (`shadowradius 5`, then `shadowradius 15`, as in a
  Layonara `fx_flame01` light) gives two controllers, both written in
  order; the engine applies them in turn, so the last one's value is the
  one the node keeps (the same for a light's `radius` and a mesh's
  `alpha`). cleanmodels (main) keeps only the last, which gives the same
  value in game. The runner now pairs controllers of one id in order and
  compares the last in full (earlier ones as SHOULD), and its ASCII reader
  keeps a repeated single-value line as a second controller, as the engine
  does.
- MDL-NODE-020 covers a supermodel node numbered -1 (new probes zspec_mid
  and zspec_kid5): it still matches, takes -1, and the walk goes on to its
  children, which take the supermodel's numbers. cleanmodels (v4.17.5)
  stopped the walk there and gave them fresh numbers, so inherited
  animations no longer bound to them.
- MDL-MESH-010 confirmed for tangents (probe zspec_tanmerge): with tangents
  given in the file, a vertex that differs only in its tangent or its
  handedness is not merged; cleanmodels merged them, and one tangent won.
- MDL-BIN-006: an emitter's chunk name is a resref that may fill its 16
  bytes with no NUL (the game's compiler copies it with an unbounded
  `%s`); cleanmodels cut 16-character names to 15.
- MDL-BIN-053: a merged-mesh donor written back draws with the copy's
  normals, not its own, which can be (0, 0, 0) at back-to-back faces; a
  reader should give it the copy's.
- MDL-BIN-007 (probes zspec_name31, zspec_name32, zspec_name40,
  zspec_namelat): the game's compiler keeps 31 characters of a node name,
  hangs on a child of a longer one, and keeps bytes above 0x7F; cleanmodels
  decompile drops those bytes.
- MDL-NODE-040 covers animation nodes the geometry lacks (new probe
  zspec_animnum): they are found by path, not name, and one the walk does
  not find gets -1 under a matched parent and otherwise its declaration
  index in the animation. cleanmodels gave them 0, the root's number.
- E68: shadow volumes are built from the face records' planes and stored
  adjacency (`PartTriMesh::Project`); a missing neighbour counts as facing
  away. MDL-MESH-022 no longer says the readers are unknown and is now a
  MUST; MDL-MESH-021 notes that shadows use the face planes.
- MDL-MESH-025: a decompiler should share positions again where the stored
  neighbours show the source shared them (not every equal position), or a
  recompile loses their adjacency and adds silhouette edges.
- MDL-NODE-050: a worn robe's nodes directly under `torso_g` are drawn
  without their orientation (confirmed in game; the code was not found, see
  unknown.md, "Worn models").
- MDL-CTRL-033 covers the model root: the game's compiler writes a root's
  position and orientation when the ASCII gives them (cleanmodels dropped
  them).
- MDL-BIN-053: merged meshes, an index list drawing other meshes' triangles
  (render-0 donors with an empty list), in 1,015 base-game binaries; a
  faces-only reader must put the donors back (Layonara nwn-module#476).
- MDL-MESH-063 (and E66): what shaders read: UV set 1 as `vTcIn1`, a
  material's `textureN` as `texUnitN` / `textureNBound` for units 0 to 14 (corrected below: 0 to 10);
  custom shaders declare what the stock includes don't (in game: a custom
  shader reading `tverts1` and `texture7`).
- MDL-MESH-064 (and E67): what makes a mesh blended. `transparencyhint` only
  orders meshes; the pass comes from the material (`.mtr` `transparency`,
  `blending additive`, or diffuse alpha) or a faded part. In game: hair with a
  mask shader over a PLT drew as solid strips until its MTR set
  `transparency 1` (Layonara nwn-haks#34).
- MDL-BIN-048: slot 3 is also read as tangents when texture animation slots
  0-2 and 4 are unset, it holds a unit vector and every finite, non-zero
  vector is unit length; NaN and zero vectors in it are bad tangents, which
  a reader may fill from MDL-MESH-043. cleanmodels dropped 251 such streams
  in Layonara's haks, and compile generated new tangents.

Corrections after the first draft:
- MDL-MESH-063 (and E66): `texUnitN` / `textureNBound` exist for units 0 to
  10 only; units 11 to 15 are `texFBColor`, `texFBDepth`, `texUnitEnvCube`,
  `texUnitEnv` and `texUnitNoise` (a jump table in `ConnectShaderData`).
  Found by comparison with Moonglow's shader notes.
- MDL-SKIN-030, -031: a vertex weighing a skipped bone slot is not collapsed;
  it takes the slot's last matrix (stock `c_wings2`'s weights are non-zero).
  Only all-zero weights collapse.
- MDL-NODE-020 (and E45): a node the supermodel lacks gets -1 only when its
  parent matched; under an unmatched parent it gets the supermodel's count
  + 1 + its declaration index (new probe zspec_kid4).
- MDL-CTRL-012 (and E60, tables/controllers.yaml): a bare static `detonate`
  compiles with column byte 0xff (new probe zspec_deton).
- Runner: `roundtrip --approved FILE` and `approve` tell approved
  differences from failures (runner/approvals.py, runner/approvals/). An
  approval holds only where its condition is checked on the mesh or node
  (per-corner facts the round trip now records); approved findings are
  reported apart, and a model with only those is `pass-approved`. The round
  trip now checks stability whatever the findings, and pairs a node whose
  32-character name the compile cut to 31 (MDL-BIN-007) with the cut node
  when no other node has that name, reporting `name` instead of `missing`.
- Runner: more approved differences (runner/approvals/layonara.json,
  James 2026-11-10): node numbers no declaration order reproduces
  (`renumbered`), header counts against the haks' supermodel
  (`supermodel-count`) and of animation trees (`anim-header-count`),
  children nwnmdlcomp left out of transparency order (`tree-sorted`), aabb
  planes at a tie of MDL-MESH-052 (`aabb-plane-tie`), and three kinds of
  second-compile difference: vertices only dropped zero-area faces used
  (`dead-face-vertices`), the model box by 1 ulp (`bounds-ulp`) and 0.0
  against -0.0 in a float (`signed-zero`). The facts come from
  runner/nodefacts.py (a replica of libstdc++'s `std::sort`, the numbering
  rules, and whether any declaration order reproduces the original) and
  `mdlconf.explain_unstable`. The >16-children shuffle, numbers a
  part-number declaration reproduces and the supermodel -1 walk stay
  failures.
- MDL-MESH-066, MDL-MESH-067 (new) and E69, read in the client's
  disassembly (not checked in game): a mesh with render 0 is never drawn,
  whatever its index list holds (`PartTriMesh::IsPartRenderable`, called by
  every draw path); a shadow volume is gated by `shadow` and `beaming`, not
  `render`, and built from the face list (`PartTriMesh::Project`,
  `GetProjectsShadows`). MDL-BIN-053 now says a render-0 donor casts its
  faces' shadow and a receiver's copies cast none, so writing donors with
  render 1 changes no shadow (Layonara's 1,158 merged models, compared in
  world space). The unknown.md item on render-0 meshes with an index list is
  settled in code. From the MDL pipeline Phase 2 render-list analysis.
- Runner: approval `merged-render-lists` (runner/approvals/layonara.json,
  James 2026-11-11). For a model with merged render lists (MDL-BIN-053) the
  round trip records `compile model.render_lists`
  (`mdlconf.render_list_facts`): every drawn triangle and every shadow face
  of the original and the compile, in world space, paired one to one, with
  the drawing state, animation and corner attributes compared. When the
  whole model draws and casts shadows as before, the donors' `render`,
  `normal`, `tangent` and `handedness` (their own, never drawn; the copies
  the game drew are compared and found the same) and the receivers' and
  donors' `triangles` and `vertex_count` findings are approved, in the
  decompile and the compile; the meshes' other findings still need their
  own entries. A receiver's mesh facts pair the compile with its own faces,
  the start of its index list. On run 6's 1,177 render-list models
  (cleanmodels 3003980) it holds on 998: 481 pass-approved, 511 unstable,
  6 fail on other findings (node numbers, aabb trees, controller keys).
- Runner: `run` checks a compile's face-record vertex indices against the
  golden (MDL-MESH-043, MDL-BIN-049; cleanmodels before PR #138 wrote tangent
  clones there), and accepts a decompile that leaves tangents out when
  compiling its ASCII gives them back exactly (cleanmodels PR #137).
- Runner: an `allow` entry can be limited with `match`; zspec_bezier2 now
  allows dropped bezier handles on a geometry node in compiles too, as
  MDL-CTRL-023 says, while a missing controller or a wrong first value stays
  a MUST failure.
- MDL-NODE-012: past 16 children the order is libstdc++'s `std::sort`,
  reproduced by a replica (zspec_tsort24, zspec_tsort50, zspec_tsort90); the
  open question is closed.
- MDL-MESH-062, MDL-BIN-045, E54: animmesh sets are laid out over the merged
  vertices; the texture set count divides by the tvert count (zspec_animtv).
- MDL-ASCII-040: where glibc's sscanf ends a number.
- MDL-CTRL-014 (new) and E65: the engine applies a controller by its column
  count: 1, 3 or 4 floats written from the runtime field, the rest keeping
  the runtime constructors' values (position 0, colours 0, orientation the
  identity); any other count is skipped. Readers must use the column count;
  MDL-CTRL-021 now says nwnmdlcomp's 0x19 bezier controllers are skipped in
  game. The runner compares a short controller through those initial values.
- The `.ksy` compiles with kaitai-struct-compiler 0.10 and 0.11; strings
  are ISO-8859-1 (old files hold bytes above 127); `check_ksy.py
  --generated DIR` checks a generated parser, which decodes every golden and
  all 25,597 base-game binaries identically (ksy/README.md).
- Reports rerun on the 46 probes.
- Report for cleanmodels v4.10.0 (46 compile, 46 decompile, 14 stock).
- Report for cleanmodels v4.11.0: the same results as v4.10.0. The
  reconciliation table notes where cleanmodels changed since v4.9.0 (light
  144, `setfillumcolor`, `ambient_only`).
- Report for cleanmodels v4.12.0: the same results as v4.10.0; the
  reconciliation table notes that it ignores `lightmapped`.
- Report for cleanmodels v4.13.0: the same results as v4.10.0 (no probe has
  merged render lists or a root transform).
