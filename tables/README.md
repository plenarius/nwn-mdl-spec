# Tables

Machine-readable data for implementations to generate their own tables from
(CC0). Build 89.8193.37-17 unless an entry says otherwise.

| File | What |
|---|---|
| [controllers.yaml](controllers.yaml) | Binary controller IDs by node class, value widths, ASCII keywords, defaults; ids the engine does not write; nwnmdlcomp's emitter IDs |
| [node_flags.yaml](node_flags.yaml) | Node content flag bits, sub-header sizes, ASCII node type words |
| [keywords.yaml](keywords.yaml) | Every ASCII keyword each engine parser reads (with its address), how it is matched and parsed; words the engine does not read |
| [render_hints.yaml](render_hints.yaml) | The render hint field and which values generate tangents |
| [classification.yaml](classification.yaml) | The classification byte |
| [reconciliation.md](reconciliation.md) | Where cleanmodels, Moonglow and the engine disagreed, and how each case was settled |

## Format

Plain YAML in a small subset, so a reader with no YAML library (the
runner's `runner/miniyaml.py`) can load it:

- block mappings (`key: value`, nested by indentation);
- block lists whose items are scalars or **flow** mappings, one per line
  (`- {id: 8, name: position}`);
- flow lists (`[a, b]`);
- scalars: integers (decimal or `0x` hex), floats, `true`/`false`/`null`,
  quoted strings and bare words;
- `#` comments.

Any YAML library reads the same data (the files are checked against PyYAML).

## Fields that recur

- `status`: `confirmed`, `inferred`, `untested` or `observed` (seen in data,
  meaning unknown). See [CONTRIBUTING.md](../CONTRIBUTING.md).
- `evidence`: probe names (`zspec_*`, `cmbez01`, `cmtan01` in
  `conformance/probes/`), engine findings (`E12`, in
  [engine/findings.md](../engine/findings.md)) or addresses (objdump
  addresses in `nwmain-linux`; Ghidra adds 0x100000).
- `applies` (controllers): the node class whose id space the entry belongs
  to. A node's classes, most specific first: `emitter` (flag 0x4), `light`
  (0x2), `mesh` (0x20), then `base` for every node.
