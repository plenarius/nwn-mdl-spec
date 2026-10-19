# Engine behaviour

What the game's code does with models, finding by finding, written without
reference to any one tool. The spec's rules cite these.

- **Build:** NWN:EE 89.8193.37-17, Linux `nwmain-linux` (unstripped x86-64),
  git commit 26c6e573, sha256
  `6d19c39bc646af5ddbc333ff31797a4acd9019506bcb45ef1b93b1bd5925e700`.
- **Addresses** are objdump/nm addresses (file virtual addresses). Ghidra
  loads this PIE at 0x100000, so its addresses are 0x100000 higher
  (`MdlNodeTriMesh::ProcessVerts` is 0x454dd0 here, 0x554dd0 in Ghidra).
- **Status:** **confirmed** (read in code and checked, or shown by a golden
  or in game), **inferred** (follows from code or data, not shown),
  **untested**.
- **Numbering:** E1–E37 keep the numbers of cleanmodels'
  `NWMAIN_FINDINGS.md`, where they were first written (2026-10-11 to
  2026-10-19); E38 onwards were found while building this suite
  (2026-10-19).

| File | What |
|---|---|
| [behaviour.md](behaviour.md) | The findings |
| [method.md](method.md) | How the code was read and how goldens and in-game checks were made, so others can repeat them |

Some findings cite files that are not in this repository: third-party
models compiled in game, Beamdog's HD body parts, the game's own models.
They are named so the observation can be repeated on a machine with the
game; they are never copied here.
