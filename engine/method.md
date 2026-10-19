# How the evidence was gathered

So anyone with the game can repeat it.

## Reading the code

- The binary is the Linux client `nwmain-linux` (unstripped, so functions
  have their C++ names). Build and checksum are in [README.md](README.md).
- `nm -C` and `objdump -d -C` give addresses and disassembly. Addresses in
  this repository are objdump's.
- [tools/parser_strings.py](tools/parser_strings.py) lists the strings each
  parser function refers to (the keyword lists in
  [tables/keywords.yaml](../tables/keywords.yaml)). A string that is
  compared with `strcasecmp` is matched case-insensitively; a compare done
  with `repe cmpsb` against a string (MDL-ASCII-010) is case-sensitive and a
  prefix compare.
- Ghidra 12.1.4, headless, decompiled the larger functions (`analyzeHeadless
  … -postScript DecompAddrs.java Name=<ghidra address> …`, on a copy of the
  project; Ghidra loads the binary at 0x100000, so its addresses are 0x100000
  higher). The first Ghidra analysis wrongly marked `memcpy`, `free` and
  `operator new` as non-returning, which truncates every function that calls
  them; re-analyse with the "Non-Returning Functions - Discovered" analyser
  off, or clear those marks before decompiling.

## Engine goldens

`conformance/tools/make_goldens.py` automates this:

1. Copy the probe (and any material or supermodel it needs) into the game's
   user folder `development/` (`~/.local/share/Neverwinter Nights/development/`
   on Linux). That folder outranks every other resource location but the
   vaults (E29), so the probe is what the game loads; check first that no
   file of the same name is already there, and remove everything afterwards.
2. Start a private X display (`Xvfb :99 -screen 0 1920x1400x24`); never use
   the desktop's display.
3. From the game's `bin/linux-x86`, run `DISPLAY=:99 ./nwmain-linux
   compilemodel <resref>`. The log says "Successfully compiled model" and the
   binary appears in the user folder's `modelcompiler/<resref>.mdl` within a
   few seconds; the process then exits.
4. Copy the binary out, remove the probe from `development/`, stop Xvfb.

Every probe was compiled twice (`goldens/` and `goldens/run2/`). The fields
that differ between the two are uninitialised memory or runtime values
(E55); `mdlconf.py expect --second` lists them per probe as `volatile`, and
the runner never compares them.

A crash leaves a report in the user folder's `crashreport/` with a
backtrace (E54 came from one).

## Skinned meshes

`compilemodel` refuses a model whose skin is not bound yet, and a skin is
bound only when a creature using the model is drawn (E20). The skin
findings (E20–E28) were read in code and checked on models compiled with
the console `compilemodel` while a creature using them was on screen, in a
small test module; those models were third-party and Beamdog's, so they
are not in this repository. Goldens for the suite's own skin probe need the
same kind of rig.

## In-game checks

The in-game results cited (E22's torn neck, Moonglow's animation binding
test) come from small test modules with the models in a hak, viewed in the
client. They are described where cited.

## The corpus survey

`conformance/tools/scan_stock.py` reads `data/nwn_base.key` and its BIF files
with the Python standard library (`runner/resfiles.py`) and counts controller
ids, column bytes and emitter grids per producer (E64). It copies nothing.
