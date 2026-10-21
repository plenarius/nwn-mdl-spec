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

Corrections after the first draft:
- MDL-NODE-020 (and E45): a node the supermodel lacks gets -1 only when its
  parent matched; under an unmatched parent it gets the supermodel's count
  + 1 + its declaration index (new probe zspec_kid4).
- MDL-CTRL-012 (and E60, tables/controllers.yaml): a bare static `detonate`
  compiles with column byte 0xff (new probe zspec_deton).
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
