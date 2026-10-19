# Contributing

This repository describes what the game does. Every statement about the
engine needs evidence, and the text keeps what is known apart from what is
guessed.

## Evidence

A claim about the engine carries:

- **the build** it was read on (today 89.8193.37-17, Linux `nwmain-linux`,
  commit 26c6e573, sha256 `6d19c39b…5925e700`);
- **its evidence**, one or more of:
  - a function and address. Use objdump/nm addresses (file virtual
    addresses). Ghidra loads the binary at 0x100000, so its addresses are
    0x100000 higher: `ProcessVerts` is 0x454dd0 in objdump, 0x554dd0 in
    Ghidra. Say which function, and what in it;
  - a golden: a probe in `conformance/probes/` and the game's compile of it
    in `conformance/goldens/`;
  - an in-game result: what was loaded, how, and what was seen;
  - data in the game's own files, named by resref (never copied here);
- **a status**:
  - **confirmed**: read in the code and checked, or shown by a golden or an
    in-game result;
  - **inferred**: follows from the code or the data, not shown directly;
  - **untested**: written down so it is not lost, not checked at all.

Only confirmed behaviour goes into normative text (MUST, SHOULD). Inferred
and untested behaviour goes into [spec/unknown.md](spec/unknown.md) or is
marked as such in [engine/behaviour.md](engine/behaviour.md), and is never
promoted without new evidence.

## Rule IDs

Each normative rule has an ID `MDL-<AREA>-<NNN>`:

| Area | File |
|---|---|
| `BIN` | [spec/binary.md](spec/binary.md) |
| `CTRL` | [spec/controllers.md](spec/controllers.md) |
| `ASCII` | [spec/ascii.md](spec/ascii.md) |
| `MESH` | [spec/mesh.md](spec/mesh.md) |
| `NODE` | [spec/nodes.md](spec/nodes.md) |
| `SKIN` | [spec/skin.md](spec/skin.md) |

IDs are stable: never renumber or reuse one. A rule that turns out wrong is
marked withdrawn, with the reason, and a new ID replaces it. Implementations
may cite IDs in comments and tests.

Engine findings are numbered `E1`, `E2`, … in
[engine/behaviour.md](engine/behaviour.md). E1–E37 match the numbering of
cleanmodels' `NWMAIN_FINDINGS.md`, where they were first written; from E38
on the numbers are this repository's own (cleanmodels' findings 38 and later
are numbered separately).

## Pull requests

- A change to normative text needs evidence: a golden, or an engine citation
  with the build. Say which.
- A new behaviour should come with a probe: a small ASCII model that
  isolates it, its golden, and its expected JSON (see below).
- Tables change with the text that justifies them. Implementations generate
  their tables from `tables/`, so a table error spreads; check it twice.
- Write plainly. Short sentences, one claim each, the address or probe next
  to it.

## Probes and goldens

1. Write the probe in `conformance/probes/<resref>.mdl`. The resref is at most
   16 characters and starts with `zspec_` so it cannot collide with game
   content. Put a comment at the top saying what it isolates and that it is
   CC0. Use texture names that do not exist (`zspec_t0`) unless the probe is
   about a material.
2. Add it to `conformance/manifest.json` (with any companion files under
   `with`).
3. Make its golden, twice (the second run finds the uninitialised fields):

   ```sh
   python3 conformance/tools/make_goldens.py <resref>
   python3 conformance/tools/make_goldens.py --out conformance/goldens/run2 <resref>
   python3 runner/mdlconf.py expect --second conformance/goldens/run2
   ```

   `make_goldens.py` puts the probe in the game's `development/` folder, runs
   `nwmain-linux compilemodel` on a private Xvfb display, copies the result
   and removes everything it put in `development/` (that folder outranks
   haks and override). It refuses to run if a file of the same name is
   already there.
4. Check the golden decodes with the `.ksy`: `python3 ksy/check_ksy.py`
   (CI also checks it with the parser kaitai-struct-compiler generates; see
   [ksy/README.md](ksy/README.md)).
5. Cite the probe from the rule it supports.

Skinned meshes cannot be compiled this way: `compilemodel` refuses a model
whose skin has not been bound, which needs a creature using the model on
screen. Those probes stay pending until there is an in-game rig.

## Assets

- No Beamdog game assets: no stock models, textures or BIF/KEY content.
  Refer to stock models by name; the stock tests extract them from the
  user's install.
- No third-party models, and nothing whose licence you cannot give as CC0.
- Your own probes are CC0; the engine's compile of them may be committed.

## Licences

By contributing you agree that text you add is licensed CC-BY 4.0 and
tables, probes, goldens, code and data CC0 1.0 (see the README).
