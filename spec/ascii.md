# The ASCII format (`MDL-ASCII`)

How the engine reads an ASCII model (it loads them at runtime as well as
compiling them, so this is also what players see). A reader that wants to
treat a file as the game does follows these rules; a writer that wants the
game to read its output as meant stays inside them.

The keyword lists, with the parser and address each comes from, are in
[tables/keywords.yaml](../tables/keywords.yaml).

## Lines and words

**MDL-ASCII-001** The engine reads a model line by line. Leading spaces and
tabs are skipped. Words are separated by spaces or tabs; a trailing `\r`
(CRLF line ends) is whitespace. *Confirmed: zspec_crlf (identical to
zspec_dummy but for the name), zspec_numfmt (tabs).*

**MDL-ASCII-002** A line whose first word the current parser does not know is
ignored, wherever it is. There is no error for unknown keywords, so a
misspelt keyword is silently lost. *Confirmed: zspec_setfill, zspec_light
(lamp_b), zspec_emitter; every parser chains to the base node parser,
which ignores what it does not know.*

**MDL-ASCII-003** There is no comment syntax as such: a line starting with
`#` is an unknown line (MDL-ASCII-002), and words after the values a keyword
reads are not looked at (`position 1 2 3 # note`). Inside a counted list a
`#` line is not skipped: it is read as a row (MDL-ASCII-050). *Confirmed:
zspec_numfmt (comment line in a node, comment after values). The list case
is read in code (0x44e570, `Parse<SkinVertexWeight>` 0x44fd00), not probed.*

## Case

**MDL-ASCII-010** Keywords are matched case-insensitively (`strcasecmp`),
**except** these structural words, which are matched case-sensitively as
prefixes of the line: `node`, `endnode`, `parent`, `endlist`, `event`,
`animlength`, and the `done…`/`end…` lines that close a geometry or
animation block. A writer MUST write them in lower case. *Confirmed:
zspec_numbers (`PARENT` is not read); the compares are `repe cmpsb`
sequences at 0x447963 (`node`), in `ParseNode` 0x447540 (`endnode`),
`MdlNode::InternalParseField` 0x448bb0 (`parent`), `Parse<AurGenericKey>`
0x44e570 (`endlist`), `Animation::InternalParseField` 0x447a40 (`event`,
`animlength`).*

**MDL-ASCII-011** Inside `beginmodelgeom` and `newanim`, any line starting
with `done` or `end` (case-sensitive) ends the block (`ImportMaxTree`,
0x447ef0): `endmodelgeom`, `doneanim`, `donemodel`. A stray line starting
with `end` between nodes ends the geometry there. Inside a node only
`endnode` ends it. *Read in code (`Animation::InternalParseField` loop and
`ImportMaxTree`); the normal case is confirmed by every golden.*

## The top level

**MDL-ASCII-020** At the top level the engine knows `filedependancy`,
`setsupermodel`, `setanimationscale`, `classification`, `newmodel`,
`newanim`, `beginmodelgeom`, `donemodel` and `ignorefog`, matched as
case-insensitive prefixes of the line (0x446330). `filedependency` (the
other spelling) is not among them; both are ignored anyway. *Read in code;
confirmed for classification and ignorefog by zspec_cls_*.*

**MDL-ASCII-021** `classification` takes one word, compared
case-insensitively: `tile` 2, `character` 4, `effect` or `effects` 1, `door`
8; any other word (`gui`, `item`, `other`, `tiles`, …) leaves the byte at 0.
A compiler MUST NOT accept other plurals. *Confirmed: zspec_cls_tile,
zspec_cls_tiles, zspec_cls_effs, zspec_cls_gui, zspec_cls_item,
zspec_cls_door, zspec_dummy; `classification(char*)` 0x446440.*

**MDL-ASCII-022** `ignorefog <int>`: a non-zero value writes fog byte 0, zero
or absent writes 1. *Confirmed: zspec_cls_door (1 → 0), zspec_cls_gui (0 →
1).*

**MDL-ASCII-023** `setsupermodel <model> <supermodel>`: `NULL` means none,
and the game's compiler then writes the string `NULL` in the header.
*Confirmed: every golden without a supermodel; zspec_kid.*

## Nodes

**MDL-ASCII-030** A node is `node <type> <name>` up to a line starting with
`endnode`. The type word is compared case-insensitively against `camera`,
`emitter`, `light`, `trimesh`, `animmesh`, `danglymesh`, `reference`,
`aabb`, `skin`; any other word (`dummy`, `patch`, `pwk`, …) makes a plain
node, written with flags 0x1. *Confirmed: zspec_nodetypes (`camera` →
0x9, `patch` → 0x1, `DUMMY`, `TriMesh`); `ParseNode` 0x447540.*

**MDL-ASCII-031** `parent <name>` attaches the node under the named node.
`parent NULL` (any case) makes it the root. A node whose `parent` line is
missing or not read (`PARENT`, MDL-ASCII-010) is in no tree: the game's
compiler leaves it out of the file, though it still used a part number
(MDL-NODE-010). A compiler MUST do the same or refuse the model; it SHOULD
warn. *Confirmed: zspec_numbers (`n_caps`: number 5 used, node absent).*

**MDL-ASCII-032** `orientation x y z angle` is converted to a quaternion:
the axis is normalised by `Vector::Normalize` (E18), which turns a **zero
axis into (1, 0, 0)**; then xyz = axis × sin(angle/2), w = cos(angle/2). The
angle is used as given (radians, not wrapped). So `orientation 0 0 0 0` is
the identity but `orientation 0 0 0 1` is a rotation of 1 radian about +X,
and a non-unit axis is normalised first. A compiler MUST convert this way.
*Confirmed: zspec_orient (all six cases), zspec_dummy.*

The same conversion applies to five-float key rows (MDL-CTRL-031).

**MDL-ASCII-033** A node's keywords are those of its type's parser and the
parsers it chains to ([tables/keywords.yaml](../tables/keywords.yaml),
`chains`): a skin reads skin, trimesh and base keywords. A keyword of
another node type is an unknown line there. *Read in code; confirmed for
the light and emitter header fields by zspec_light and zspec_emitter.*

## Numbers and values

**MDL-ASCII-040** Floats are read with C `sscanf("%f")`: an optional sign,
digits with an optional point and exponent (`1e1`, `-2.5E-1`, `+3`, `.5`,
`1.`, `007`), and also hexadecimal floats (`0x1p1`), `inf` and `nan`.
Several values are read with `"%f %f %f"`: reading stops at the first word
that does not start with a number, and also right after a number followed
by other characters (`1.5abc 2 3` reads 1.5 only; `0,5 1 1` reads 0;
`1.#INF` reads 1). The values not read keep what they had. *Confirmed:
zspec_numfmt (well-formed), zspec_numbers (malformed); `Parse(char const*,
float&)` 0x446770 and the vector parser 0x4466a0.*

A writer MUST write plain decimal numbers. The malformed forms are
documented so readers can match the engine; the suite checks them as
SHOULD (a reader MAY reject or warn instead).

**MDL-ASCII-041** Integers are read with `sscanf("%d")` (`2.9` reads 2,
`+2` reads 2); if that fails, the words `TRUE` and `FALSE` (any case) give 1
and 0; anything else leaves the field as it was (`render yes` keeps 1). A
negative integer is stored as its two's complement (`tilefade -1` →
0xffffffff). *Confirmed: zspec_numbers, zspec_numfmt; `Parse(char const*,
int&)` 0x446790.*

**MDL-ASCII-042** `rotatetexture` and the emitter flags (`p2p`, `bounce`, …)
are booleans: only the words `true`, `false`, `1` and `0` (any case) change
them. *Read in code: `Parse(char const*, bool&)` 0x446900; the values 0 and
1 are confirmed by zspec_trimesh and zspec_emitter.*

**MDL-ASCII-043** A colour or vector keyword (`diffuse`, `ambient`,
`specular`) reads three floats; a fourth is ignored. *Confirmed:
zspec_numbers (`diffuse 0.5 0.25 0.125 1`).*

**MDL-ASCII-044** A name (texture, bitmap, material, parent, refModel) is
one word (`%s`). `bitmap` keeps at most 63 characters. `NULL` is not
special for textures: `bitmap NULL` stores the string `NULL`. *Confirmed:
zspec_aabb (`bitmap NULL` → `NULL`); `MdlNodeTriMesh::InternalParseField`
0x44ced0 (`strncpy(…, 0x3f)`).*

## Lists

**MDL-ASCII-050** A list keyword (`verts`, `tverts`, `faces`, `weights`,
`constraints`, key lists, …) is followed either by a count, in which case
exactly that many rows are read, skipping only lines that are truly empty
(first byte NUL, `\n` or `\r`; a line of spaces is a row), or by nothing,
in which case rows are read up to a line starting with `endlist`
(case-sensitive), with the same skipping. After a counted list, an
`endlist` line is an unknown line and harmless. *Confirmed: zspec_anim
(counted with an empty line inside and a trailing endlist; endlist form);
`Parse<AurGenericKey>` 0x44e570; E28 for weights.*

**MDL-ASCII-051** A key list whose count is followed by another word on the
same line is read as binary data (`AurResGetData`) instead of text rows. A
writer MUST NOT put anything after the count. *Read in code (0x44e570); not
probed.*

**MDL-ASCII-052** A face row is `v1 v2 v3 smoothgroup t1 t2 t3 material`,
eight integers (`sscanf("%d" × 8)`): three indices into `verts`, the
smoothing group bit mask, three indices into `tverts`, and the material
(surfacemat.2da row on walkmeshes). *Confirmed: every mesh golden;
`Parse(char const*, MaxFace_PostProcess&)` 0x446c50.*

**MDL-ASCII-053** `normals`, `tangents` and `colors` have one row per vertex
of `verts` (not per corner): `tangents` rows are x y z handedness.
*Confirmed: zspec_merge (normals), zspec_tanfile (tangents),
zspec_trimesh (colors).*

## Animations

**MDL-ASCII-060** `newanim <name> <model>` starts an animation, read like the
geometry (MDL-ASCII-011) with `length`, `transtime`, `animroot` and `event
<time> <name>` lines and nodes, up to `doneanim`. An animation node names
its parent like a geometry node. *Confirmed: zspec_anim, zspec_animfx.*

**MDL-ASCII-061** An `animmesh` node in an animation MUST repeat the mesh's
`verts` (and should repeat `tverts` and `faces`): the engine divides the
`animverts` count by the node's own vertex count and crashes (SIGFPE) when
that is 0. *Confirmed: an earlier version of zspec_animmesh without them
crashed `nwmain-linux compilemodel` in `MdlNodeAnimMesh::InternalPostProcess`
at 0x4578c9 (`idivl`); E54.*

## Words the engine does not read

**MDL-ASCII-070** These appear in ASCII models or are written by tools but no
engine parser reads them (they are unknown lines, MDL-ASCII-002):
`setfillumcolor`, `lightningsubdiv`, `opacity`, `ambient_only`,
`fading_light`, `negativelight`, `lensflares`, `texture3` to `texture14`,
`lightmapped`, `center`, `gizmo`, `multimaterial`, `walkmesh`,
`filedependency`, … ([tables/keywords.yaml](../tables/keywords.yaml),
`not_read`). A compiler MUST NOT give them a meaning: the game shows the
same ASCII without them. A compiler SHOULD warn when it sees one, and MAY
offer to rewrite it (for example `setfillumcolor` to `selfillumcolor`) as an
explicit repair. *Confirmed for setfillumcolor (zspec_setfill: no
self-illumination controller), lightningsubdiv, opacity (zspec_emitter,
zspec_animfx), ambient_only, fading_light, negativelight, lensflares
(zspec_light lamp_b: header fields unchanged); the rest by their absence
from the parsers' strings.*

`setfillumcolor` is in 2,387 of the game's own ASCII files (Moonglow notes
B.22c): on those meshes the game shows no self-illumination from it.
