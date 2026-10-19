# Controllers (`MDL-CTRL`)

Controllers carry every animatable value: a node's position, orientation
and scale, a mesh's alpha and self-illumination, a light's colour and
radius, and almost every emitter parameter. A geometry node stores its
static values as one-key controllers; an animation node stores keyed ones.

## Storage

**MDL-CTRL-001** A node's controllers are two arrays (node +84 and +96): 12-byte
keys and a pool of floats. A key is:

| Offset | Type | Field |
|---|---|---|
| 0 | u4 | controller id (MDL-CTRL-002) |
| 4 | u2 | rows: the number of keys |
| 6 | u2 | time index: float index of the first key time |
| 8 | u2 | data index: float index of the first value |
| 10 | u1 | column byte: low nibble the number of value columns, 0x10 set for bezier keys |
| 11 | u1 | padding: uninitialised |

The key times are `data[time index .. time index + rows)`; the values are
`data[data index ..]`, `rows × stride` floats row by row, where stride is the
column count (three times it for bezier keys, MDL-CTRL-020). *Confirmed:
every golden; `NewController` layout in `bezier_notes.md` (12 bytes, read by
`NewController::Control` 0x498f20).*

**MDL-CTRL-002** A controller id means different things on different node
classes; a reader MUST name it by (node class, id), trying emitter (flag
0x4), light (0x2), mesh (0x20), then base. The ids, widths and ASCII
keywords are in [tables/controllers.yaml](../tables/controllers.yaml): base
position 8, orientation 20, scale 36; mesh selfillumcolor 100, alpha 128;
light color 76, radius 88, shadowradius 96, verticaldisplacement 100,
multiplier 140; and the 39 emitter controllers. *Confirmed: zspec_dummy,
zspec_trimesh, zspec_light, zspec_emitter, zspec_anim, zspec_animfx,
cmbez01, zspec_bezier2 (every id in the table was written by the game's
compiler for its keyword).*

**MDL-CTRL-003** An orientation value is a quaternion stored x, y, z, w.
*Confirmed: zspec_dummy (`orientation 0 0 1 1.5707963` → 0, 0, 0.7071,
0.7071), zspec_orient.*

## How the engine reads them

**MDL-CTRL-010** On a geometry node every controller has one key, at time 0.
*Confirmed: every golden.*

**MDL-CTRL-011** The binary loader copies the key array and the float pool
unchanged, except that it maps each id to an offset in its runtime node
(by ranges of ids per node class). It has no notion of which compiler wrote
the file. *Confirmed: loader 0x4c01b0 (`FUN_005c01b0` in Ghidra), E36.*

So a binary from nwnmdlcomp, whose emitter ids for the three-stop values
differ (MDL-CTRL-050), is read with the game's ids. Light id 144 occurs in
1,408 lights of 665 base-game models, all compiled by an older EE build,
always with value 1; this build's compiler writes it for no keyword, and
what reads it is unknown ([unknown.md](unknown.md)).

**MDL-CTRL-012** `detonate` keys are times only, with no values. The game's
compiler writes column byte 0 for `detonatekey` rows and 0xff for a bare
static `detonate` line on an emitter: the byte is the number of floats
`AddGenericControllerSingle` (0x4486f0) read, and sscanf returns -1 when there
are none. Old BioWare files also carry column byte 1. A reader MUST accept
any column byte for detonate (0xff is not a bezier flag here) and read its
keys as times; a compiler SHOULD write 0 for keyed and 0xff for static
detonate. *Confirmed: zspec_animfx (0), zspec_deton (0xff); stock
`vwp_flash_blured` carries both; stock counts (E64).*

**MDL-CTRL-014** The engine applies a controller by its column count, not
by its keyword's width. `NewController::Control` (0x498f20) takes the low
nibble of the column byte: 1, 3 or 4 values are read per key (three times
that with the bezier bit, MDL-CTRL-020) and written as that many
consecutive floats from the runtime field the id maps to (MDL-CTRL-011),
blended with what is there (1: one `movss` store; 3: a vector; 4: a
quaternion slerp). The field's other floats keep their values. Any other
count (0, 2, 5-15) makes the engine skip the controller: nothing is read or
written. Column byte 0xff, which the game's compiler writes for a controller
line with no values (sscanf's -1, MDL-CTRL-012), is such a count, not a
bezier byte. Before geometry controllers are applied, once at time 0 by
`Gob::Reset` (0x499bd0), the runtime fields hold their constructors' values:
position (0, 0, 0), orientation the identity, scale 1 (`Part::Part`,
0x43c800); selfillumcolor (0, 0, 0) and alpha 1 (`PartTriMesh::PartTriMesh`,
0x43cb50); light colour (0, 0, 0) and multiplier 1 (`PartLight::PartLight`,
0x43d1d0); the emitter colours (0, 0, 0) (`PartEmitter::PartEmitter`,
0x4abfe0). So a one-column position holding 1.5 places the node at
(1.5, 0, 0). The runtime orientation is held w first, so a short
orientation controller fills w, x, … rather than the file's x, y, …
(MDL-CTRL-022).

A reader MUST read a controller's values with its column count (the stride
of MDL-CTRL-001) and MUST NOT read its keyword's full width from the pool:
what follows belongs to nothing, or to another controller. A decompiler MUST
give the components a controller does not hold the runtime initial values
above, or write only the values it holds (`position 1.5`, which the game's
compiler turns back into the same one-column controller, MDL-CTRL-030). It
SHOULD drop, with a warning, a controller whose count the engine skips,
other than detonate (MDL-CTRL-012), and SHOULD warn about a 4-column
controller on a 3-wide field, which writes past it. *Confirmed: code
(`NewController::Control` 0x498f20, the store at 0x498fa8; the constructors
above; `Gob::Reset` 0x499bd0); zspec_numbers (`n_junk`: one column, 1.5;
the floats after it in the pool are not the controller's). Base game: two
such controllers in 32,832 models, both in animations: a light colour with 4
columns (`ttf02_m31_03`) and a position with column byte 0xff and no values
(`ttf02_s12_01`). The effect on screen is not observed.*

**MDL-CTRL-013** `lightningsubdiv` and `opacity` are not controllers: the
emitter parser has no such keywords, static or keyed, and the game's
compiler writes nothing for them. A compiler MUST NOT write a controller for
them (id 220, used by older tools for lightningsubdiv, is never written by
the game). *Confirmed: zspec_emitter, zspec_animfx; E37.*

## Bezier keys

**MDL-CTRL-020** A bezier controller has 0x10 set in its column byte and
three values per key, each as wide as the controller: the value, then the
in handle, then the out handle. The game's compiler writes `0x10 | columns`
(0x11 for a scalar, 0x13 for position and colours). *Confirmed: cmbez01,
zspec_bezier2; E33.*

**MDL-CTRL-021** nwnmdlcomp writes the full row width instead (0x19 for a
3-column controller). The game skips such a controller: its low nibble, 9,
is none of 1, 3 and 4 (MDL-CTRL-014), so a bezier controller compiled by
nwnmdlcomp animates nothing in game. A reader MAY recover the keys the
author wrote by taking the value width from the controller table, and
SHOULD then warn that the binary's controller has no effect in game.
*Source: nwnmdlcomp `NmcController.cpp:413-416` via Moonglow notes B.8; the
skip from code (`NewController::Control` 0x498f20); no nwnmdlcomp binary with
bezier keys exists in the base game (E64).*

**MDL-CTRL-022** The engine has no working `orientationbezierkey`: it reads
at most 10 floats a row, does not convert the axis-angle, and gives the
controller 3 columns (0x13), so the rotation is evaluated as a vector. A
compiler MAY write what the engine writes, or compile the rows as linear
orientation keys (time and the first axis-angle), and SHOULD warn either
way. A decompiler MAY drop a bezier orientation controller with a warning.
*Confirmed: cmbez01 (`0 0 0 1 0 0 0 1 0.1 0 0 1 0.2` → 0x13, value 0 0 1,
in 0 0 0, out 1 0.1 0); E34. The on-screen effect is not observed.*

**MDL-CTRL-023** A bezier key list on a geometry node is stored with its
handles (0x11 for `alphabezierkey` with one key). The engine evaluates a
geometry node's controllers at time 0, where both the linear and the bezier
paths return the first value, so the handles have no effect. A compiler MUST
write the controller (with the first key's value); it MAY keep the handles.
A decompiler MAY write it as a plain value. *Confirmed: zspec_bezier2
(geometry `alphabezierkey`); E36.*

## From ASCII

**MDL-CTRL-030** A controller keyword with a single value (`position 1 2 3`,
`alpha 0.5`) makes a one-key controller at time 0 whose column count is the
number of floats read from the line (MDL-ASCII-040). Four floats for
`orientation` are an axis and an angle, converted as in MDL-ASCII-032.
*Confirmed: every golden; zspec_numbers (`position 1.5abc 2 3` reads one
float and is written with one column).*

**MDL-CTRL-031** A key list (`positionkey`, `alphakey`, …, MDL-ASCII-050)
reads up to 10 floats per row: the time, then the values. The column count
is the number of values in the first row. A row of exactly five floats is
converted from axis-angle to a quaternion, whatever the keyword (so an
`orientationkey` row `t x y z angle` gives 4 columns). *Confirmed:
zspec_anim, zspec_animfx; `Parse(char const*, AurGenericKey&)` 0x446ae0,
`AddGenericController` 0x4488d0.*

**MDL-CTRL-032** A bezier key list (`<keyword>bezierkey`) reads up to 10
floats per row; the column count is `(floats in the first row − 1) / 3`
and every float after the time is stored. *Confirmed: cmbez01,
zspec_bezier2; `AddBezierController` 0x448a30.*

**MDL-CTRL-033** The game's compiler writes a controller only for a keyword
the ASCII gives: a geometry node with no `orientation` line has no
orientation controller, not an identity one. A compiler SHOULD do the same;
writing a controller with the default value is equivalent in game (the
node's transform starts at identity). *Confirmed: every golden; equivalence
inferred from `CreateInstanceTreeR` 0x43c6b0 (a part starts at identity,
behaviour.md, "Skin binding: further notes").*

**MDL-CTRL-034** The controllers of a node are written in the order their
keywords appear in the ASCII. Order has no effect the suite could find;
it is not checked. *Observed: zspec_emitter.*

**MDL-CTRL-035** In an animation, a node's single value (`position 0 0 1.5`
in a `newanim` block) makes a one-key controller at time 0, like on a
geometry node. *Confirmed: zspec_anim (animation `idle`).*

## Evaluation (informative)

`NewController::Control` (0x498f20) dispatches on the column count: 1 →
`GetFloatValue` (0x498480), 3 → the vector path (0x498180), 4 →
`GetQuaternionValue` (0x498640, always slerp). Other counts are ignored.
The float and vector paths test 0x10 and use `InterpolateBezier` (float
0x5b9140, vector 0x5b8fd0). For a vector the curve is P0 = v0, P1 = v0 +
out0, P2 = v1 + in1, P3 = v1. For a scalar the arguments do not match that
form (see [unknown.md](unknown.md)). *Confirmed in code (E35); not observed
on screen.*

## nwnmdlcomp's emitter ids

**MDL-CTRL-050** nwnmdlcomp numbers the three-stop emitter values
differently: alphaMid 464, colorMid 468, percentStart/Mid/End 480-482,
sizeMid 484, sizeMid_y 488 (the game: 448, 452, 464-466, 468, 472). The game
reads such a file with its own ids (MDL-CTRL-011). A decompiler MAY
recognise nwnmdlcomp's numbering (an id in 480-488, or a 468 with three
columns, can only be nwnmdlcomp's) and name the controllers as the author
meant; it SHOULD then say so. No emitter in the base game uses any of these
ids, from either compiler. *Source for the ids: nwnmdlcomp
`NwnMdlNodes.h:168-174` (via Moonglow notes B.8, cleanmodels
`controllers.go`); status inferred: no nwnmdlcomp binary was made for this
suite. Base-game count: E64.*
