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
