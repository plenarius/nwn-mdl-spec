# NWN:EE model format (MDL): specification and conformance suite

A shared, evidenced description of the model files (`.mdl`) of Neverwinter
Nights: Enhanced Edition, with tests any implementation can run.

**Status:** first draft, read on engine build 89.8193.37-17 (Linux
`nwmain-linux`, commit 26c6e573). Nothing here is official: it is what the
game was seen to do, with the evidence for each claim.

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
read, in both tools.

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

## What to build (the plan this repository follows)

A standalone repository in a neutral GitHub organisation, for example `nwn-formats/mdl`. Maintainers come from several projects, and no single tool owns it.

### 1. Normative specification (Markdown)

- **Binary layout:** headers, node types, mesh, skin, dangly, AABB, emitter, light, animation and controller structures, MDX streams, pointer rules.
- **ASCII grammar:** keywords, lists (counted and `endlist`), number syntax, case rules, comments, what the engine skips.
- **Conversion rules,** both directions. For example: vertex merging, normals from smoothing groups, tangent generation, skin bone numbering, node numbering against a supermodel, bezier key layout.
- **Rule IDs.** Each rule is a MUST/SHOULD statement with a stable ID (`MDL-SKIN-014`), so implementations can cite it in comments and tests.

### 2. Engine behaviour, with evidence

Every claim about what the game does carries:
- the engine build it was read on (e.g. 89.8193.37);
- its evidence: function name and address, an engine-compiled golden file, or an in-game test;
- a status: **confirmed**, **inferred** or **untested**.

Unverified behaviour goes in a clearly marked "observed / unknown" section, never in the normative text.

### 3. Machine-readable data

- **Binary layout:** a Kaitai Struct `.ksy`, which generates readers for about a dozen languages.
- **Tables (YAML or JSON):**
  - controller IDs per node type, with column counts;
  - the emitter IDs of the game's compiler and of nwnmdlcomp;
  - ASCII keywords and their aliases;
  - render hint values;
  - node type flags;
  - classification values.

  Implementations should generate their tables from these, not copy them by hand.

### 4. Conformance suite

This is the most valuable part.

- **Probe models:**
  - small ASCII models written for the suite, licensed CC0;
  - each probe isolates one behaviour, e.g. one per controller kind, a material-hinted tangent mesh, a skinned body part, a supermodel with repeated node names.
- **Engine goldens:** the game's own compile of each probe. On Linux:
  1. Put the probe in the user folder's `development/`.
  2. Run `nwmain-linux compilemodel <resref>` on any X display (Xvfb works).
  3. The binary appears in `modelcompiler/<resref>.mdl` within about 5 seconds.

  Skinned meshes need a creature using the model on screen, so those need a small test module.
- **Expected results as JSON:** a decoded, tool-neutral view of each golden (nodes, controllers with keys and handles, skin bone names). Implementations then compare data rather than bytes, and the suite needs no reference decompiler.
- **Stock-model tests by name:** for behaviour seen in the game's own models. A runner extracts them from the user's install.
- **Runner and CI:**
  - a small runner script that any implementation can plug into through a command-line contract (`decompile <in> <out>`, `compile <in> <out>`);
  - CI that regenerates the goldens after each game patch and reports what changed.

### 5. Versioning and process

- Tag the spec per engine build, with a changelog of behaviour that changed between builds.
- A pull request that changes normative text needs evidence: a golden file, or an engine citation with the build.
- Licensing: text CC-BY 4.0; tables, probes and goldens CC0 (goldens are the engine's output from CC0 inputs). **No Beamdog game assets in the repository.** Stock models are referenced by name only.

## Licences

- Text (`spec/`, `engine/`, the Markdown files): [CC-BY 4.0](LICENSE-TEXT).
- Tables, probes, goldens, expected files, the `.ksy` and the runner: [CC0 1.0](LICENSE-DATA). The goldens are the engine's output from CC0 inputs.
- **No Beamdog game assets are in this repository.** Stock models are named, never copied; the stock tests extract them from your own install.

## Related

- [nwn.wiki](https://nwn.wiki) — the community wiki; its MDL pages describe the keywords for builders. This repository links to it rather than duplicating it.
- xoreos-docs `templates/NWN1MDL.bt` — the 010 Editor template most implementations started from.
