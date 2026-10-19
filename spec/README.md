# The specification

What a Neverwinter Nights: Enhanced Edition model file is, and what the
game does with it, written so a reader or writer can be built from it.

**Build:** 89.8193.37-17 (Linux `nwmain-linux`, commit 26c6e573). Every
rule was read on this build. A later patch may change behaviour; the
changelog records what changed and when.

| File | Rules | What |
|---|---|---|
| [binary.md](binary.md) | `MDL-BIN-*` | The compiled file: headers, nodes, sub-headers, raw data, pointers, uninitialised fields |
| [controllers.md](controllers.md) | `MDL-CTRL-*` | Controller structs, ids, columns, bezier keys, how ASCII becomes controllers |
| [ascii.md](ascii.md) | `MDL-ASCII-*` | The text format as the engine reads it: lines, case, numbers, lists, keywords |
| [mesh.md](mesh.md) | `MDL-MESH-*` | Compiling a mesh: vertex merging, degenerate faces, normals, render hints, tangents, bounds, walkmesh trees, defaults |
| [nodes.md](nodes.md) | `MDL-NODE-*` | Node numbers, tree order, supermodels, animation nodes |
| [skin.md](skin.md) | `MDL-SKIN-*` | Skinned meshes: binding, bone numbering, bind lists, what the renderer does |
| [unknown.md](unknown.md) | — | Observed or unknown behaviour, and open questions. Not normative. |

## Reading the rules

Each rule has an ID, a statement, and its evidence:

> `MDL-NODE-010` A compiler MUST number nodes in the order the ASCII
> declares them, the root 0. *Confirmed: zspec_nodeorder; E43.*

- **MUST** / **MUST NOT**: what the game's own compiler does, and what an
  implementation has to do to produce a file the game treats the same way.
  The suite checks these; failing one fails the probe.
- **SHOULD**: what the engine does where a difference is harmless or the
  engine's behaviour is a defect an implementation may avoid. The suite
  reports these.
- **MAY**: explicitly allowed variation.

"Compiler" means anything that writes binary models from ASCII; "decompiler"
anything that writes ASCII from binary; "reader" anything that reads
either. Rules about what the *engine* does are statements of fact with
their evidence; rules for implementations follow from them.

Evidence names a probe (`zspec_*`, `cmbez01`, `cmtan01`: the ASCII in
[conformance/probes/](../conformance/probes/), the game's compile in
[conformance/goldens/](../conformance/goldens/)), an engine finding (`E12`,
in [engine/behaviour.md](../engine/behaviour.md)), or a function and address
(objdump addresses; Ghidra adds 0x100000). Behaviour that is only inferred
is not stated as a rule: it is in [unknown.md](unknown.md).

## Words

- **model data**: the part of a binary file after the 12-byte file header up
  to the raw data. Offsets into it are relative to file offset 12.
- **raw data**: the vertex streams at the end of the file. Offsets into it
  are relative to `12 + raw_offset`. (Other documents call it the MDX part.)
- **node class**: emitter, light, mesh or base, from the node flags; controller
  ids are per class.
- **tree position**: a node's index in the depth-first walk of a tree.
- **part number**: the number stored in a node header (`MDL-NODE-010`).
- **corner**: one of a face's three vertices, before any merging.
