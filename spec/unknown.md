# Observed, inferred and unknown

Nothing on this page is normative. Each item says what is known, how, and
what would settle it.

## Controllers

- **Scalar bezier evaluation.** For a 1-column bezier controller,
  `GetFloatValue` (0x498480) calls `InterpolateBezier(v0, v0 + v1, out0,
  out0 + in1, t)`: the curve ends at v0 + v1, not at the next key's value,
  and the first key's in handle is unused. The vector form (P0 = v0, P1 = v0
  + out0, P2 = v1 + in1, P3 = v1) is consistent; the scalar one looks like an
  engine bug. Past the last key both bezier paths read beyond the
  controller's data. *Read in code (E35); not seen on screen. An in-game
  probe animating alpha or scale with bezier keys would settle what players
  see.*
- **`orientationbezierkey`.** The engine keeps 9 of a row's 12 values,
  unconverted, as a 3-column vector, which the vector path writes into the
  node's quaternion (MDL-CTRL-022). What that looks like on screen, and what
  to tell a builder beyond "it does not work", is open.
- **Light controller 144.** 1,408 lights in 665 base-game models, all written
  by an older EE compiler, carry it with value 1.0 (E64). This build's
  compiler writes it for no keyword. The loader maps it into the light
  (runtime offset 0xa8); what reads that offset was not traced.
- **nwnmdlcomp's emitter ids.** No base-game emitter uses ids 464-488 or the
  game's 448-472 (E64), so nothing shipped relies on the game reading
  nwnmdlcomp's numbering. Haks were not surveyed. No nwnmdlcomp binary with
  three-stop values was made, so the ids come from nwnmdlcomp's source only.
- **Three-stop emitter values.** The game's compiler stores `colorMid`,
  `alphaMid`, `sizeMid`, `sizeMid_y` and `percentStart/Mid/End`; Moonglow's
  client measurements (notes B.20a) found they change nothing on screen.
  Not re-checked here.

## ASCII

- **Animation node controllers in a supermodel's animation**: whether an
  animation node with no controllers is always written. The game kept such
  nodes in every probe (zspec_anim's root, zspec_kid's `hips`), but an
  earlier engine compile of a third-party creature (cleanmodels' findings,
  answer 5) omitted its skin nodes from every animation. What decides it is
  unknown.
- **Overlong values.** A static controller line with more values than the
  controller's width (`scale 2 3 4`) was not probed: the probe line was in a
  node that dropped out of the tree. The engine reads up to some number of
  floats and sets the column count from it (MDL-CTRL-030); the upper limit
  for a single value is not known.
- **`radius`, `bmin`, `bmax` at the geometry level** (`Model::InternalParseField`
  0x447990) and **`bmin`, `bmax` on a mesh**: read by the engine, never probed.
  Whether the computed bounds overwrite them is unknown.
- **`texindices1-3`**: per-face UV indices for the extra UV sets. Read by the
  trimesh parser; not probed.
- **`vertexindices`, `vertexindicescount`, `leftoverfaces`**: read; not
  probed.
- **`animlength <name> <time>`**: read as a case-sensitive word in an
  animation; not probed.
- **Comment lines inside counted lists** are read as rows (from the list
  parsers' skip rule, MDL-ASCII-003); not probed for vertex lists.
- **Several `parent NULL` nodes**: each makes itself the root in turn
  (`MdlNode::InternalParseField` sets the tree's root), so the last one is
  presumably the root and the others drop out. Not probed.
- **A `parent` naming a node that does not exist**: `FindMdlNode`'s result is
  used without a check (0x448bb0); presumably a crash. Not probed.
- **Node names longer than 32 characters, model and texture names longer
  than their fields**: truncation and collisions not probed.

## Meshes

- **Merged meshes (MDL-BIN-053).** Which compiler wrote them is not known:
  the base game ships them and this build's compiler does not make them,
  which points at BioWare's earlier compiler; no older compiler was run.
  Whether the engine would draw a render-0 mesh that has an index list is
  not shown by them either, since every donor's list is empty. An in-game
  probe with render 0 and a full index list would settle it.

- **The stale AABB tree** after a degenerate walkmesh face is deleted
  (MDL-MESH-024): what pathfinding and collision do with leaves pointing past
  the face list was not observed.
- **Face adjacency**: walkmeshes recompute it at load; whether anything reads
  the stored values of render meshes is unknown (MDL-MESH-022).
- **Mesh bounds and the model's bounds/radius**: what the engine uses them
  for (culling?) was not read.
- **Emitter `xgrid`/`ygrid` absent**: uninitialised in the game's compile
  (MDL-BIN-052); what the game's runtime load of the ASCII does with them was
  not observed.
- **Vertex colours**: whether an all-white colour stream and no stream are
  the same for every shader (MDL-MESH-061).
- **The normal sum** at mesh +504 was not compared.

## Skins

- **No skin golden.** `compilemodel` needs the creature on screen
  (MDL-SKIN-010), so the whole of [skin.md](skin.md) rests on code reading
  and on engine-compiled files outside this repository. A small test module
  that puts a creature with each skin probe on screen, then runs
  `compilemodel`, would give the goldens.
- **Skin header sizes** (MDL-BIN-061): 100, 192 and 320 bytes all occur in
  game files, with no field to tell them apart; the sizes come from the
  first data offset after each skin node, not from code.
- **Which uninitialised fields matter**: bone constant indices and leftover
  weight slots are uninitialised (MDL-SKIN-022, MDL-SKIN-014). A leftover
  slot with a garbage weight > 0 and a garbage bone would distort its vertex;
  whether that happens in shipped files was not surveyed.
- **Bone list entries past the tree.** In stock `tni_udoor_19` (100-byte skin
  header) bone 17's list entry is 109, outside the 46-node tree, while the
  bone map gives position 6. By the code (64 entries copied, MDL-BIN-061;
  out-of-tree positions skipped, MDL-SKIN-030) the engine drops that bone,
  leaving 27 corners of the two curtains with no influence (drawn at the
  origin). Not observed in game. A decompiler that rebuilds the bone list
  from the bone map gets the bone the author meant; the suite checks such
  corners as SHOULD.
- **The quaternion sign** of `qbone_ref_inv` in BioWare-compiled files (w = +1
  for an identity in `c_marilith2`, w = −1 from the EE compiler): both
  render the same; the old compiler's maths was not read.

## Worn models

- **Why MDL-NODE-050 happens, and how far it reaches.** The code that
  drops the orientation of a robe node under `torso_g` was not found. Open:
  whether it comes from how the robe is attached to the wearer
  (`CNWCAnimBaseParts::LoadModel` 0x9db550 loads it as an object of its own,
  `AttachToObject`; MDL-SKIN-012), and whether it also applies to
  children of the other bones above the waist (`neck_g`, the shoulders and
  arms), to `rootdummy`'s, to cloaks and to body parts. Only `pelvis_g`
  was seen to keep a child's orientation, on one sample. *A probe robe with
  one marker mesh per bone, each turned 90 degrees, worn in game, would map
  it; reading what poses a worn robe's nodes would explain it.*

## Process

- **Golden regeneration after a patch** needs a machine with the game and an
  X server; the CI workflow here runs the self-checks only.
- **Moonglow's compile has no material lookup** in its library API, so its
  adapter cannot show material-hinted tangents; the toolset application may
  supply materials another way (not checked).
