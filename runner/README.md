# Runner

`mdlconf.py` runs an implementation through the suite. Python 3.8 or later,
standard library only (CC0).

## The contract

Your implementation provides one command with two verbs:

```sh
COMMAND compile   <in.mdl> <out.mdl>
COMMAND decompile <in.mdl> <out.mdl>
```

- `compile` reads an ASCII model and writes a binary one.
- `decompile` reads a binary model and writes an ASCII one.
- Exit 0 on success. Anything printed is kept in the report as the log.
- Companion files (a probe's `.mtr` material, a supermodel) are put in the
  same folder as `<in.mdl>`; look for them there.
- `<out.mdl>` does not exist beforehand; its folder does.
- Each call runs in a fresh temporary folder, which is also the working
  directory.
- For `roundtrip` only: `MDLCONF_RESOURCE_DIRS` lists folders (separated as
  in `PATH`) holding the model's supermodels, skeletons and materials, the
  original's own folder first. An implementation that can search folders
  should search these; one that can't will see node numbers and tangents
  differ wherever they depend on them.

A small wrapper script is usually enough: see [adapters/](adapters/).

## Commands

```sh
python3 runner/mdlconf.py run   --impl NAME --cmd COMMAND [--test compile|decompile] [--only PROBE ...] [--json OUT] [-v]
python3 runner/mdlconf.py stock --impl NAME --cmd COMMAND [--root NWN_ROOT] [--json OUT] [-v]
python3 runner/mdlconf.py expect [--second conformance/goldens/run2]
python3 runner/mdlconf.py check-goldens DIR
python3 runner/mdlconf.py roundtrip --impl NAME --cmd COMMAND [--resource-dir DIR ...] [--workers N] [--max-memory GB] [--model-timeout S] [--partial FILE] [--own-dir-map ORIG=CONV] [--approved FILE] [--json OUT] [-v] PATH ...
python3 runner/mdlconf.py approve --results ROUNDTRIP.json --approved FILE [--json OUT] [-v]
python3 runner/mdlconf.py view FILE
```

- `run`: every probe with a golden, compiled and decompiled. Prints one line
  per test (PASS/FAIL/ERROR/PENDING) with the MUST failures under it (and
  the SHOULD notes with `-v`); `--json` writes everything. A compile's face
  records must hold the golden's vertex indices (`faces.v`): after tangent
  generation clones a vertex, the face records keep the original and only
  the index list names the clone (MDL-MESH-043, MDL-BIN-049). A decompile
  may leave a normal-mapped mesh's tangents out when its compile makes them
  again: the run compiles the ASCII with the same implementation, and when
  every drawn corner gets exactly the golden's tangent and handedness, the
  "missing" notes move to `accepted` (shown with `-v`).
- `stock`: the stock models of `conformance/stock.yaml`, extracted from the
  install (`NWN_ROOT`, or the usual Steam folders), decompiled and compared.
- `expect`: regenerates `conformance/expected/` from the goldens (after a
  game patch, or a new probe). With `--second`, a second compile of the same
  probes, the fields that differ are listed as volatile.
- `check-goldens DIR`: compares goldens made anew (e.g. after a patch) with
  the expected files and lists what changed: the changelog material for a
  new engine build.
- `roundtrip PATH ...`: for a collection of binary models (a hak's
  folders, say), whether an implementation can keep them as ASCII and
  compile them back. Each binary under PATH is decompiled and compiled
  back, and both results are compared with the original under the suite's
  rules, the original standing in for the golden. The compiled model is then
  decompiled and compiled once more, and the second binary must equal the
  first byte for byte (status `unstable` otherwise). ASCII models are passed
  over. The output lists each model that did not pass, then the causes:
  failures grouped by path and message with node names and numbers taken
  out, with how many models each affects and an example. Exit status 1
  unless all passed. The original is whatever compiled it: a difference can
  be the implementation's or a defect the original already had.
  Models are taken in batches of 256. Each worker may use `--max-memory`
  GB (default 4; the implementation it runs is not limited): a model that
  needs more is an `error`, not a crash. If a worker dies anyway, only its
  batch is lost, reported as errors. Progress goes to stderr.
  `--own-dir-map ORIG=CONV` is for checking a tree converted in place
  against copies of its originals kept under ORIG: a model's own folder
  (searched first for its supermodels and materials, by the implementation
  through `MDLCONF_RESOURCE_DIRS` and by the facts below) is then the same
  place under CONV, where the converted siblings are, not the copies'
  folder. The implementation's `decompile` of the copy is then expected to
  hand back the converted file.
  `--model-timeout S` makes a model that takes longer than S seconds (all
  four calls and the comparison) an `error`; a batch in which no model
  finishes for that long plus 300 s (780 s without the option) is stopped
  and its unfinished models reported as errors. `--partial FILE` appends
  each result to FILE as a JSON line as it finishes; a run given the same
  file skips the models already in it, so a stopped run resumes.
  The JSON keeps, per result, whether the second compile was byte-identical
  (`stable`, checked whatever the findings; when it is not,
  `unstable_fields` counts the fields that differ, and
  `unstable_adjacency_only` is the number of faces whose adjacency differs
  when nothing else in the bytes does, 0 otherwise, and `unstable_explained`
  the kinds of difference, `{kind: count}`, when every difference is of a
  known kind: `adjacency`, `signed_zero` (a float field 0.0 in one, -0.0 in
  the other), `bounds_ulp` (the model's bounding box by 1 ulp) or
  `dead_vertices` (vertices only faces the compile dropped used,
  `mdlconf.explain_unstable`) and `facts`: for each mesh with
  a MUST finding in the compile, how its drawn triangles pair with the
  original's and which corner attributes differ (`mdlconf.mesh_facts`); for
  each node name cut to 31 characters whether the cut name is unique; for an
  aabb node whose planes differ, whether they are at ties
  (`nodefacts.aabb_facts`); and, when the compile has a node number, tree or
  count finding, `compile model.nodes` (`nodefacts.model_facts`): whether
  the numbers follow MDL-NODE-010/020 from the ASCII's declaration order
  against the supermodel the implementation finds (the original's folder,
  then the `--resource-dir` folders, then the base game; an ASCII
  supermodel numbered by the same rules; `supermodel_chain`, that
  supermodel and what each ASCII one names down to the first binary, each
  `binary` or `ascii`), whether any declaration order
  gives the original's numbers and tree, whether the animations follow
  MDL-NODE-040 in both, the tree resorted by MDL-NODE-012, and the header
  counts; and, when the original has merged render lists (MDL-BIN-053) and
  a mesh has a render, triangles, vertex_count, face_count or shadow finding, `compile
  model.render_lists` (`mdlconf.render_list_facts`): every triangle the
  original and the compile draw and every shadow face they cast, in world
  space, paired one to one, with what differs per pair (drawing state,
  animation, corner attributes) and what is left unpaired. A decompile
  whose ASCII leaves out tangents the compile makes again exactly has those
  notes in `accepted`.
- `--approved FILE`: differences a project has agreed to live with
  ([approvals/](approvals/), checked by [approvals.py](approvals.py)). A
  MUST finding is approved only when its entry's condition holds on the
  mesh or node it is about, and all of a mesh's findings are approved or
  none. Approved findings are moved to `approved` with the entry's id and
  counted per entry, never dropped. A model whose MUST findings are all
  approved and whose second compile is stable is `pass-approved`, and so is
  one whose second compile differs only in kinds of difference the file
  approves (`unstable_explained`; a `stability binary2` finding per kind,
  counted apart as `stability-approved`). Without the flag nothing changes.
- `approve`: re-scores a `roundtrip --json` file under an approvals file
  without running anything. Results made before the runner recorded facts
  approve nothing.
- `view FILE`: the JSON view of a binary or ASCII model.

### Approvals files

```json
{"format": "mdlconf-approvals/1", "name": "...", "description": "...",
 "approvals": [{"id": "...", "check": "vertex-layout", "rules": ["MDL-MESH-010"],
                "description": "...", "condition": "..."}]}
```

`check` names one of the conditions [approvals.py](approvals.py)
implements (`vertex-layout`, `dropped-zero-area-faces`, `nan-tangent-fill`,
`tangents-baked`, `water-texanim-169`, `name-cut-31`, `renumbered`,
`supermodel-count`, `anim-header-count`, `tree-sorted`, `aabb-plane-tie`,
`unstable-adjacency-only`, `signed-zero`, `bounds-ulp`,
`dead-face-vertices`, `merged-render-lists`, `emitter-texture-junk`,
`aabb-stale-tree`, `stale-supermodel`, whose entry also lists the names
in `supermodels`); `condition` says in
words what it checks. Leaving an entry out of the file leaves its findings
failed, together with every other finding on the same mesh.
[approvals/layonara.json](approvals/layonara.json) is Layonara's.

## Files

| File | What |
|---|---|
| `mdlconf.py` | the runner and the comparison |
| `approvals.py`, `approvals/` | approved differences for `roundtrip --approved` and `approve` |
| `nodefacts.py` | node numbers and order as the game's compiler makes them (libstdc++'s `std::sort`, MDL-NODE-010/012/020/040) and aabb plane ties, for the approvals |
| `mdlview.py` | the two readers: binary (spec/binary.md) and ASCII as the engine reads it (spec/ascii.md) |
| `miniyaml.py` | a reader for the YAML subset the tables use |
| `resfiles.py` | KEY/BIF and ERF readers for the stock tests |
| `adapters/cleanmodels.sh` | cleanmodels (`CLEANMODELS` = its binary if not on PATH) |
| `adapters/moonglow.sh`, `adapters/moonglow/` | Moonglow's `mg-mdl`, through a small Rust program built outside both repositories: `adapters/moonglow/build.sh <moonglow-toolset checkout>` |
| `selfcheck.py` | the repository's own checks (tables, rule references, expected files, `.ksy`), run by CI |

The readers exist so the suite can compare data rather than bytes; they
are not reference implementations, and they read only what the comparison
needs.
