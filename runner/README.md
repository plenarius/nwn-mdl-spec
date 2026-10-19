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

A small wrapper script is usually enough: see [adapters/](adapters/).

## Commands

```sh
python3 runner/mdlconf.py run   --impl NAME --cmd COMMAND [--test compile|decompile] [--only PROBE ...] [--json OUT] [-v]
python3 runner/mdlconf.py stock --impl NAME --cmd COMMAND [--root NWN_ROOT] [--json OUT] [-v]
python3 runner/mdlconf.py expect [--second conformance/goldens/run2]
python3 runner/mdlconf.py check-goldens DIR
python3 runner/mdlconf.py view FILE
```

- `run`: every probe with a golden, compiled and decompiled. Prints one line
  per test (PASS/FAIL/ERROR/PENDING) with the MUST failures under it (and
  the SHOULD notes with `-v`); `--json` writes everything.
- `stock`: the stock models of `conformance/stock.yaml`, extracted from the
  install (`NWN_ROOT`, or the usual Steam folders), decompiled and compared.
- `expect`: regenerates `conformance/expected/` from the goldens (after a
  game patch, or a new probe). With `--second`, a second compile of the same
  probes, the fields that differ are listed as volatile.
- `check-goldens DIR`: compares goldens made anew (e.g. after a patch) with
  the expected files and lists what changed: the changelog material for a
  new engine build.
- `view FILE`: the JSON view of a binary or ASCII model.

## Files

| File | What |
|---|---|
| `mdlconf.py` | the runner and the comparison |
| `mdlview.py` | the two readers: binary (spec/binary.md) and ASCII as the engine reads it (spec/ascii.md) |
| `miniyaml.py` | a reader for the YAML subset the tables use |
| `resfiles.py` | KEY/BIF and ERF readers for the stock tests |
| `adapters/cleanmodels.sh` | cleanmodels (`CLEANMODELS` = its binary if not on PATH) |
| `adapters/moonglow.sh`, `adapters/moonglow/` | Moonglow's `mg-mdl`, through a small Rust program built outside both repositories: `adapters/moonglow/build.sh <moonglow-toolset checkout>` |
| `selfcheck.py` | the repository's own checks (tables, rule references, expected files, `.ksy`), run by CI |

The readers exist so the suite can compare data rather than bytes; they
are not reference implementations, and they read only what the comparison
needs.
