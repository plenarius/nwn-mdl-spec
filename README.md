# NWN:EE model format (MDL): specification and conformance suite

A shared, evidenced description of the model files (`.mdl`) of Neverwinter
Nights: Enhanced Edition, with tests any implementation can run.

**Status:** draft, read on engine build 89.8193.37-17 (Linux
`nwmain-linux`, commit 26c6e573). Nothing here is official: it is what the
game was seen to do, with the evidence for each claim. 46 probes have engine
goldens; one (a skinned mesh) is pending.

## Why

At least five projects read and write Neverwinter Nights: Enhanced Edition model files:
- [cleanmodels](https://github.com/plenarius/cleanmodels) (Go, with a Python port);
- [Moonglow Toolset](https://github.com/jadzziaa/moonglow-toolset) (Rust, `crates/mg-mdl`);
- [Neverblender](https://github.com/gyoerkaa/mdltools) (Python);
- [NWNArmory](https://github.com/dunahan/nwnarmory) (Rust);
- [nwnrs](https://github.com/urothis/nwnrs) (Rust);
- and older C++ tools (nwnmdlcomp / NWNExplorer, xoreos).

Each one re-derives the format from the same thin sources. Each one learns the engine's real behaviour separately, usually from a bug report.

Comparing cleanmodels with Moonglow in October 2026 turned up bugs in both. Most of them were wrong entries in a table:
- a controller ID the game never writes;
- a render hint value;
- emitter IDs that differ between compilers;
- skin bones numbered against the wrong tree.

One shared, evidenced source of truth, with tests any implementation can run, would have caught all of them. The first run of this suite
([conformance/reports/](conformance/reports/)) found more: default values,
number reading, node numbering, child order and keywords the engine does not
read, in both tools. cleanmodels 4.10.0 was then fixed against it and passes
every probe.

## What is here

| Folder | What it is |
|---|---|
| [spec/](spec/) | The normative text: binary layout, controllers, ASCII grammar, meshes, node numbering, skins. Every rule has a stable ID (`MDL-MESH-012`) and cites its evidence. |
| [engine/](engine/) | What the engine does, finding by finding, with function addresses, build and status (confirmed, inferred, untested). The spec's evidence. |
| [tables/](tables/) | Machine-readable data (YAML): controller IDs per node class, node flags, keywords per parser, render hints, classification. Generate your tables from these. |
| [ksy/](ksy/) | A [Kaitai Struct](https://kaitai.io) description of the binary layout, checked by decoding every golden. |
| [conformance/](conformance/) | Probe models (CC0), the game's own compile of each (the goldens), and the expected data as JSON. |
| [runner/](runner/) | A standard-library Python runner and adapters for cleanmodels and Moonglow. |

## Running the suite

Your implementation needs a command line with two verbs:

```sh
<impl> compile   <in.mdl> <out.mdl>   # ASCII in, binary out
<impl> decompile <in.mdl> <out.mdl>   # binary in, ASCII out
```

Then, with Python 3.8 or later and nothing else:

```sh
python3 runner/mdlconf.py run --impl myimpl --cmd /path/to/myimpl
```

Each probe is compiled and its output decoded and compared with the expected
data; each golden is decompiled and the ASCII read and compared. Checks are
MUST (the engine's behaviour, failing them fails the probe) or SHOULD
(reported). See [runner/README.md](runner/README.md) for the contract and
[conformance/README.md](conformance/README.md) for what each probe covers.

## How it works

### Specification

[spec/](spec/) is the normative text: the binary layout (headers, every node
type, MDX streams, pointer rules), controllers and their encoding (bezier
included), the ASCII grammar (keywords, lists, number reading, case rules),
the conversion rules (vertex merging, normals, tangents, node numbering
against a supermodel, child order, skin binding of body parts) and what the
engine does with a controller at runtime. Each rule is a MUST or SHOULD
statement with a stable ID (`MDL-SKIN-014`) that implementations can cite in
comments and tests.

### Evidence

Every claim about the engine names the build it was read on, its evidence (a
function and address, an engine-compiled golden, or an in-game test) and a
status: **confirmed**, **inferred** or **untested**. Only confirmed behaviour
is normative; the rest is in [spec/unknown.md](spec/unknown.md).
[engine/behaviour.md](engine/behaviour.md) has the findings themselves.
[CONTRIBUTING.md](CONTRIBUTING.md) has the rules.

### Machine-readable data

- [tables/](tables/) (YAML): controller IDs per node class with column counts
  and defaults, the emitter IDs of the game's compiler and of nwnmdlcomp,
  ASCII keywords per parser with aliases, render hints, node flags,
  classification, and how cleanmodels' and Moonglow's tables were reconciled.
  Generate your tables from these rather than copying them by hand.
- [ksy/](ksy/): a Kaitai Struct description of the binary layout. Checked
  with kaitai-struct-compiler 0.11 by decoding every golden and all 25,597
  binary models of the base game.

### Conformance suite

- **Probes:** small ASCII models written for the suite (CC0), each isolating
  one behaviour.
- **Goldens:** the game's own compile of each probe, made headless with
  `nwmain-linux compilemodel` ([conformance/tools/make_goldens.py](conformance/tools/make_goldens.py)),
  twice, so fields the engine leaves uninitialised are found and not compared.
- **Expected results as JSON:** a decoded, tool-neutral view of each golden,
  so implementations are compared on data, not bytes.
- **Stock-model tests by name:** behaviour seen in the game's own models,
  extracted from your install when the tests run.
- **Runner:** [runner/mdlconf.py](runner/mdlconf.py), standard-library
  Python, with adapters for cleanmodels and Moonglow.

### Not done yet

- A golden for a skinned mesh: the engine compiles one only while a creature
  using it is on screen, which needs an in-game rig.
- Regenerating the goldens after a game patch in CI: it needs the game and an
  X server, so it is a manual step (`make_goldens.py`, then `mdlconf.py
  check-goldens`) until there is a self-hosted runner with the game.
- The Windows build: everything here was read on the Linux build; where the
  C library matters (how numbers are read), the Windows build's was not
  checked.

### Versioning and governance

The spec is tagged per engine build, with a changelog of behaviour that
changed between builds ([CHANGELOG.md](CHANGELOG.md)). A change to
normative text needs evidence: a golden, or an engine citation with the
build. The repository is meant to belong to no single tool, with maintainers
from several projects.

## Licences

- Text (`spec/`, `engine/`, the Markdown files): [CC-BY 4.0](LICENSE-TEXT).
- Tables, probes, goldens, expected files, the `.ksy` and the runner: [CC0 1.0](LICENSE-DATA). The goldens are the engine's output from CC0 inputs.
- **No Beamdog game assets are in this repository.** Stock models are named, never copied; the stock tests extract them from your own install.

## Related

- [nwn.wiki](https://nwn.wiki) — the community wiki; its MDL pages describe the keywords for builders. This repository links to it rather than duplicating it.
- xoreos-docs `templates/NWN1MDL.bt` — the 010 Editor template most implementations started from.
