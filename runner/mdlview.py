# SPDX-License-Identifier: CC0-1.0
"""Decode NWN:EE MDL files into the suite's tool-neutral JSON view.

Two readers, standard library only:

  read_binary(data)  a compiled (binary) model, following spec/binary.md
  read_ascii(text)   an ASCII model, following spec/ascii.md, enough to
                     compare an implementation's decompile with a golden

Both return the same shape (see conformance/README.md, "The JSON view").
Neither is a reference implementation of anything else: they exist so the
suite can compare data instead of bytes.
"""
import math
import os
import struct

from miniyaml import load as _load_yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = os.path.join(os.path.dirname(HERE), 'tables')

# Node content flags (tables/node_flags.yaml).
F_HEADER, F_LIGHT, F_EMITTER, F_CAMERA, F_REFERENCE = 0x1, 0x2, 0x4, 0x8, 0x10
F_MESH, F_SKIN, F_ANIM, F_DANGLY, F_AABB = 0x20, 0x40, 0x80, 0x100, 0x200

NODE_TYPES = {  # flags -> ASCII node type word
    0x001: 'dummy', 0x003: 'light', 0x005: 'emitter', 0x009: 'camera',
    0x011: 'reference', 0x021: 'trimesh', 0x061: 'skin', 0x0a1: 'animmesh',
    0x121: 'danglymesh', 0x221: 'aabb',
}
TYPE_FLAGS = {v: k for k, v in NODE_TYPES.items()}

CLASSIFICATION = {0: 'none', 1: 'effect', 2: 'tile', 4: 'character', 8: 'door'}


# ---------------------------------------------------------------- numbers

def f32(x):
    """Round a Python float to float32."""
    try:
        return struct.unpack('<f', struct.pack('<f', x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def num(x):
    """A float32 as the shortest decimal that reads back to the same float32
    (so the JSON stays readable); NaN and infinities as strings."""
    if isinstance(x, int):
        return x
    if math.isnan(x):
        return 'nan'
    if math.isinf(x):
        return 'inf' if x > 0 else '-inf'
    for p in range(1, 10):
        s = '%.*g' % (p, x)
        if f32(float(s)) == x:
            v = float(s)
            return int(v) if v.is_integer() and abs(v) < 1e15 else v
    return x


def nums(xs):
    return [num(x) for x in xs]


def fval(x):
    """Undo num() for 'nan'/'inf' strings."""
    if isinstance(x, str):
        return {'nan': math.nan, 'inf': math.inf, '-inf': -math.inf}.get(x, 0.0)
    return x


# ---------------------------------------------------------------- tables

_CTRL = None


def controller_table():
    """(by_id, by_name): by_id[(applies, id)] and by_name[(applies, lower name)]."""
    global _CTRL
    if _CTRL is None:
        t = _load_yaml(os.path.join(TABLES, 'controllers.yaml'))
        by_id, by_name = {}, {}
        for c in t['controllers']:
            by_id[(c['applies'], c['id'])] = c
            by_name[(c['applies'], c['name'].lower())] = c
            for alias in c.get('aliases', []) or []:
                by_name[(c['applies'], alias.lower())] = c
        _CTRL = (by_id, by_name)
    return _CTRL


def node_classes(flags):
    """Controller classes a node of these flags has, most specific first."""
    out = []
    if flags & F_EMITTER:
        out.append('emitter')
    if flags & F_LIGHT:
        out.append('light')
    if flags & F_MESH:
        out.append('mesh')
    out.append('base')
    return out


def controller_def(flags, cid):
    by_id, _ = controller_table()
    for cls in node_classes(flags):
        if (cls, cid) in by_id:
            return by_id[(cls, cid)]
    return None


def controller_by_name(flags, name):
    _, by_name = controller_table()
    for cls in node_classes(flags):
        c = by_name.get((cls, name.lower()))
        if c:
            return c
    return None


# ---------------------------------------------------------------- binary

class _Bin:
    def __init__(self, data):
        self.d = data
        self.warnings = []
        if len(data) < 12:
            raise ValueError('file shorter than the 12-byte file header')
        zero, self.raw_off, self.raw_size = struct.unpack_from('<III', data, 0)
        if zero != 0:
            raise ValueError('not a binary model (the first four bytes are not zero)')
        self.M = 12
        self.R = 12 + self.raw_off

    def ok(self, off, n):
        return 0 <= off and off + n <= len(self.d)

    def u8(self, off):
        return self.d[off] if self.ok(off, 1) else 0

    def u16(self, off):
        return struct.unpack_from('<H', self.d, off)[0] if self.ok(off, 2) else 0

    def i16(self, off):
        return struct.unpack_from('<h', self.d, off)[0] if self.ok(off, 2) else 0

    def u32(self, off):
        return struct.unpack_from('<I', self.d, off)[0] if self.ok(off, 4) else 0

    def i32(self, off):
        return struct.unpack_from('<i', self.d, off)[0] if self.ok(off, 4) else 0

    def f(self, off):
        return struct.unpack_from('<f', self.d, off)[0] if self.ok(off, 4) else 0.0

    def fs(self, off, n):
        if not self.ok(off, 4 * n):
            self.warnings.append('float array at %#x past the end' % off)
            return [0.0] * n
        return list(struct.unpack_from('<%df' % n, self.d, off))

    def s(self, off, n):
        if not self.ok(off, n):
            return ''
        b = self.d[off:off + n]
        return b.split(b'\0', 1)[0].decode('latin-1')

    def array(self, off):
        """(model offset, count) of a 12-byte array definition."""
        return self.u32(off), self.u32(off + 4)

    def mptr(self, p):
        return self.M + p

    def rptr(self, p):
        return None if p == 0xFFFFFFFF else self.R + p


def _controllers(b, flags, keys_def, data_def):
    kptr, kcount = keys_def
    dptr, dcount = data_def
    data = b.fs(b.mptr(dptr), dcount) if dcount else []
    out = []
    for i in range(kcount):
        k = b.mptr(kptr) + 12 * i
        cid, rows, tix, dix, colbyte = b.u32(k), b.u16(k + 4), b.u16(k + 6), b.u16(k + 8), b.u8(k + 10)
        cdef = controller_def(flags, cid)
        bezier = bool(colbyte & 0x10) and colbyte != 0xFF
        cols = colbyte & 0x0F
        if cdef is not None and cdef['columns'] > 0 and bezier:
            # The game's compiler writes 0x10 | value columns; nwnmdlcomp
            # writes the row width (0x19). The value width is the table's.
            cols = cdef['columns'] if cdef['name'] != 'orientation' else cols
        stride = cols * 3 if bezier else cols
        if colbyte == 0xFF:  # some writers put -1 for "no values"
            stride, cols = 0, 0
        c = {'id': cid, 'name': cdef['name'] if cdef else 'ctrl%d' % cid,
             'columns': cols, 'bezier': bezier, 'colbyte': colbyte, 'keys': []}
        for r in range(rows):
            t = data[tix + r] if tix + r < len(data) else 0.0
            vals = data[dix + r * stride: dix + (r + 1) * stride]
            key = {'t': num(t)}
            if bezier:
                key['v'] = nums(vals[:cols])
                key['in'] = nums(vals[cols:2 * cols])
                key['out'] = nums(vals[2 * cols:3 * cols])
            else:
                key['v'] = nums(vals)
            c['keys'].append(key)
        out.append(c)
    return out


def _mesh(b, base, nd, flags):
    m = {}
    face_ptr, face_count = b.array(base + 8)
    m['bmin'] = nums(b.fs(base + 20, 3))
    m['bmax'] = nums(b.fs(base + 32, 3))
    m['radius'] = num(b.f(base + 44))
    m['average'] = nums(b.fs(base + 48, 3))
    m['diffuse'] = nums(b.fs(base + 60, 3))
    m['ambient'] = nums(b.fs(base + 72, 3))
    m['specular'] = nums(b.fs(base + 84, 3))
    m['shininess'] = num(b.f(base + 96))
    m['shadow'] = b.u32(base + 100)
    m['beaming'] = b.u32(base + 104)
    m['render'] = b.u32(base + 108)
    m['transparencyhint'] = b.u32(base + 112)
    m['renderhint'] = b.u32(base + 116)
    m['textures'] = [b.s(base + 120 + 64 * i, 64) for i in range(4)]
    m['tilefade'] = b.u32(base + 376)
    vi_ptr, vi_count = b.array(base + 380)
    m['vertex_indices_count'] = vi_count
    lo_ptr, lo_count = b.array(base + 392)
    m['leftover_faces_count'] = lo_count
    vic_ptr, vic_count = b.array(base + 404)
    vio_ptr, vio_count = b.array(base + 416)
    m['index_lists'] = []
    for i in range(min(vic_count, vio_count, 16)):
        n = b.u32(b.mptr(vic_ptr) + 4 * i)
        off = b.rptr(b.u32(b.mptr(vio_ptr) + 4 * i))
        idx = [b.u16(off + 2 * j) for j in range(n)] if off is not None and b.ok(off, 2 * n) else []
        m['index_lists'].append(idx)
    m['triangle_mode'] = b.u8(base + 436)
    vptr = b.u32(base + 444)
    nv = b.u16(base + 448)
    ntex = b.u16(base + 450)
    m['vertex_count'] = nv
    m['texture_count'] = ntex
    v = {}

    def stream(name, ptr, width):
        off = b.rptr(ptr)
        if off is None or nv == 0:
            return
        if not b.ok(off, 4 * width * nv):
            b.warnings.append('%s stream of node %s past the end' % (name, nd['name']))
            return
        flat = b.fs(off, width * nv)
        v[name] = [nums(flat[i * width:(i + 1) * width]) for i in range(nv)]

    stream('position', vptr, 3)
    for i in range(4):
        stream('uv%d' % i, b.u32(base + 452 + 4 * i), 2)
    stream('normal', b.u32(base + 468), 3)
    coff = b.rptr(b.u32(base + 472))
    if coff is not None and nv and b.ok(coff, 4 * nv):
        v['color'] = [list(b.d[coff + 4 * i: coff + 4 * i + 4]) for i in range(nv)]
    # +476..+496: six EE "texture animation" slots; slot 3 holds tangents and
    # slot 5 handedness (one float per vertex). Water meshes in 1.69 models
    # use the same slots for a bump-map stream.
    stream('tangent', b.u32(base + 488), 3)
    hoff = b.rptr(b.u32(base + 496))
    if hoff is not None and nv and b.ok(hoff, 4 * nv):
        v['handedness'] = nums(b.fs(hoff, nv))
    # The same slots hold a 1.69 water bump-map stream (MDL-BIN-048): read
    # them as tangents only with a normal-mapped hint or when every vector
    # is unit length, as the engine's compiler writes tangents.
    if 'tangent' in v and m['renderhint'] not in (2, 3):
        def unit(t):
            x, y, z = (fval(c) for c in t)
            l2 = x * x + y * y + z * z
            return 0.98 < l2 < 1.02
        if not all(unit(t) for t in v['tangent']):
            v['bumpmap_slot3'] = v.pop('tangent')
            if 'handedness' in v:
                v['bumpmap_slot5'] = v.pop('handedness')
    other_slots = [s for s in (0, 1, 2, 4) if b.rptr(b.u32(base + 476 + 4 * s)) is not None]
    if other_slots:
        m['texanim_slots_used'] = other_slots
    m['vertices'] = v
    m['lightmapped'] = b.u8(base + 500)
    m['rotatetexture'] = b.u8(base + 501)
    faces = []
    fbase = b.mptr(face_ptr)
    for i in range(face_count):
        o = fbase + 32 * i
        if not b.ok(o, 32):
            b.warnings.append('face list of node %s past the end' % nd['name'])
            break
        faces.append({
            'v': [b.u16(o + 26), b.u16(o + 28), b.u16(o + 30)],
            'material': b.u32(o + 16),
            'normal': nums(b.fs(o, 3)),
            'distance': num(b.f(o + 12)),
            'adjacent': [b.i16(o + 20), b.i16(o + 22), b.i16(o + 24)],
        })
    m['face_count'] = face_count
    m['faces'] = faces
    return m


def _skin(b, base, nv, node_names):
    s = {}
    wptr, bptr = b.rptr(b.u32(base + 12)), b.rptr(b.u32(base + 16))
    map_ptr, map_count = b.u32(base + 20), b.u32(base + 24)
    s['bone_map_count'] = map_count
    s['bone_map'] = [b.i16(b.mptr(map_ptr) + 2 * i) for i in range(map_count)] if map_count < 4096 else []
    qptr, qcount = b.array(base + 28)
    tptr, tcount = b.array(base + 40)
    s['qbone_ref_inv'] = [nums(b.fs(b.mptr(qptr) + 16 * i, 4)) for i in range(min(qcount, 4096))]
    s['tbone_ref_inv'] = [nums(b.fs(b.mptr(tptr) + 12 * i, 3)) for i in range(min(tcount, 4096))]
    s['bone_nodes'] = [b.i16(base + 64 + 2 * i) for i in range(64)]
    weights = []
    if wptr is not None and bptr is not None and b.ok(wptr, 16 * nv) and b.ok(bptr, 8 * nv):
        for i in range(nv):
            w = b.fs(wptr + 16 * i, 4)
            r = [b.i16(bptr + 8 * i + 2 * j) for j in range(4)]
            infl = []
            for j in range(4):
                # The renderer skips a slot whose weight is not > 0 or whose
                # bone maps to no tree position (E25), so such a slot is no
                # influence at all.
                if w[j] > 0 and 0 <= r[j] < 64:
                    node = s['bone_nodes'][r[j]]
                    if 0 <= node < len(node_names):
                        infl.append([node_names[node], num(w[j])])
            weights.append(infl)
    s['weights'] = weights
    return s


def _node(b, off, parent, out, depth, seen, anim):
    if off in seen or depth > 512 or not b.ok(off, 112):
        b.warnings.append('bad node pointer %#x' % off)
        return
    seen.add(off)
    flags = b.u32(off + 108)
    nd = {
        'name': b.s(off + 32, 32),
        'parent': parent,
        'type': NODE_TYPES.get(flags, 'flags%#x' % flags),
        'flags': flags,
        'number': b.i32(off + 28),
        'inheritcolor': b.u32(off + 24),
    }
    children_def = b.array(off + 72)
    keys_def, data_def = b.array(off + 84), b.array(off + 96)
    nd['controllers'] = _controllers(b, flags, keys_def, data_def)
    p = off + 112
    if flags & F_LIGHT:
        lt = {'flareradius': num(b.f(p))}
        sp, sc = b.array(p + 16)
        pp, pc = b.array(p + 28)
        cp, cc = b.array(p + 40)
        tp, tc = b.array(p + 52)
        lt['flaresizes'] = nums(b.fs(b.mptr(sp), sc)) if sc < 1024 else []
        lt['flarepositions'] = nums(b.fs(b.mptr(pp), pc)) if pc < 1024 else []
        lt['flarecolorshifts'] = [nums(b.fs(b.mptr(cp) + 12 * i, 3)) for i in range(min(cc, 1024))]
        lt['texturenames'] = [b.s(b.mptr(b.u32(b.mptr(tp) + 4 * i)), 64) for i in range(min(tc, 1024))]
        for i, k in enumerate(('lightpriority', 'ambientonly', 'ndynamictype', 'affectdynamic',
                               'shadow', 'generateflare', 'fadinglight')):
            lt[k] = b.u32(p + 64 + 4 * i)
        nd['light'] = lt
        p += 92
    if flags & F_EMITTER:
        em = {'deadspace': num(b.f(p)), 'blastradius': num(b.f(p + 4)), 'blastlength': num(b.f(p + 8)),
              'xgrid': b.u32(p + 12), 'ygrid': b.u32(p + 16), 'spawntype': b.u32(p + 20),
              'update': b.s(p + 24, 32), 'render': b.s(p + 56, 32), 'blend': b.s(p + 88, 32),
              'texture': b.s(p + 120, 64), 'chunkname': b.s(p + 184, 16),
              'twosidedtex': b.u32(p + 200), 'loop': b.u32(p + 204),
              'renderorder': b.u16(p + 208), 'flags': b.u32(p + 212)}
        nd['emitter'] = em
        p += 216
    if flags & F_REFERENCE:
        nd['reference'] = {'refmodel': b.s(p, 64), 'reattachable': b.u32(p + 64)}
        p += 68
    if flags & F_MESH:
        nd['mesh'] = _mesh(b, p, nd, flags)
        p += 512
    if flags & F_SKIN:
        nd['_skin_at'] = p
        p += 0  # size settled by the bone list read lazily; nothing follows it
    if flags & F_ANIM:
        if flags & F_SKIN:
            b.warnings.append('skin and anim flags together on %s' % nd['name'])
        nv = nd.get('mesh', {}).get('vertex_count', 0)
        am = {'sampleperiod': num(b.f(p))}
        vsp, tsp = b.u32(p + 40), b.u32(p + 44)
        vsc, tsc = b.u32(p + 48), b.u32(p + 52)
        am['vertex_sets'] = vsc
        am['texture_sets'] = tsc
        # Stored vertex-major (vertex * sets + set); the view uses the ASCII
        # order, set-major (set * vertices + vertex).
        if nv and vsc and vsc * nv < 1 << 20:
            flat = b.fs(b.mptr(vsp), 3 * nv * vsc)
            am['animverts'] = [nums(flat[3 * (v * vsc + s):3 * (v * vsc + s) + 3])
                               for s in range(vsc) for v in range(nv)]
        if nv and tsc and tsc * nv < 1 << 20:
            flat = b.fs(b.mptr(tsp), 2 * nv * tsc)
            am['animtverts'] = [nums(flat[2 * (v * tsc + s):2 * (v * tsc + s) + 2])
                                for s in range(tsc) for v in range(nv)]
        nd['animmesh'] = am
        p += 56
    if flags & F_DANGLY:
        cp, cc = b.array(p)
        nd['dangly'] = {'constraints': nums(b.fs(b.mptr(cp), cc)) if cc < 1 << 20 else [],
                        'displacement': num(b.f(p + 12)), 'tightness': num(b.f(p + 16)),
                        'period': num(b.f(p + 20))}
        p += 24
    if flags & F_AABB:
        root = b.u32(p)
        entries, stack, seen_a = [], [root] if root else [], set()
        while stack:
            a = stack.pop()
            if a in seen_a or not b.ok(b.mptr(a), 40):
                continue
            seen_a.add(a)
            o = b.mptr(a)
            left, right = b.u32(o + 24), b.u32(o + 28)
            entries.append({'min': nums(b.fs(o, 3)), 'max': nums(b.fs(o + 12, 3)),
                            'face': b.i32(o + 32), 'plane': b.u32(o + 36)})
            if right:
                stack.append(right)
            if left:
                stack.append(left)
        nd['aabb'] = entries
        p += 4
    out.append(nd)
    cptr, ccount = children_def
    for i in range(min(ccount, 4096)):
        _node(b, b.mptr(b.u32(b.mptr(cptr) + 4 * i)), nd['name'], out, depth + 1, seen, anim)


def read_binary(data):
    b = _Bin(data)
    M = b.M
    model = {
        'name': b.s(M + 8, 64),
        'node_count': b.u32(M + 76),
        'geometry_type': b.u8(M + 108),
        'classification': b.u8(M + 114),
        'fog': b.u8(M + 115),
        'bmin': nums(b.fs(M + 136, 3)),
        'bmax': nums(b.fs(M + 148, 3)),
        'radius': num(b.f(M + 160)),
        'animationscale': num(b.f(M + 164)),
        'supermodel': b.s(M + 168, 64),
    }
    nodes = []
    root = b.u32(M + 72)
    _node(b, b.mptr(root), None, nodes, 0, set(), False)
    names = [n['name'] for n in nodes]
    for n in nodes:
        if '_skin_at' in n:
            n['skin'] = _skin(b, n.pop('_skin_at'), n.get('mesh', {}).get('vertex_count', 0), names)
    anims = []
    aptr, acount = b.array(M + 120)
    for i in range(min(acount, 4096)):
        o = b.mptr(b.u32(b.mptr(aptr) + 4 * i))
        if not b.ok(o, 196):
            b.warnings.append('bad animation pointer')
            continue
        an = {'name': b.s(o + 8, 64), 'node_count': b.u32(o + 76), 'geometry_type': b.u8(o + 108),
              'length': num(b.f(o + 112)), 'transtime': num(b.f(o + 116)),
              'animroot': b.s(o + 120, 64)}
        ep, ec = b.array(o + 184)
        an['events'] = [[num(b.f(b.mptr(ep) + 36 * j)), b.s(b.mptr(ep) + 36 * j + 4, 32)]
                        for j in range(min(ec, 4096))]
        an_nodes = []
        _node(b, b.mptr(b.u32(o + 72)), None, an_nodes, 0, set(), True)
        for n in an_nodes:
            n.pop('_skin_at', None)
        an['nodes'] = an_nodes
        anims.append(an)
    view = {'format': 'mdl-view/1', 'source': 'binary', 'model': model, 'nodes': nodes, 'animations': anims}
    if b.warnings:
        view['warnings'] = b.warnings
    return view


# ---------------------------------------------------------------- ASCII
#
# The ASCII reader follows the engine's own reading (spec/ascii.md): the
# structural words node, endnode, parent, endlist and event are matched
# case-sensitively, everything else case-insensitively; numbers are read the
# way sscanf reads them; a value that does not parse leaves the field as it
# was. It reads what the comparison needs, not every keyword.

import re as _re

_FLOAT_RE = _re.compile(r'[+-]?(?:0[xX](?:[0-9a-fA-F]+\.?[0-9a-fA-F]*|\.[0-9a-fA-F]+)(?:[pP][+-]?\d+)?'
                        r'|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
                        r'|[iI][nN][fF](?:[iI][nN][iI][tT][yY])?|[nN][aA][nN])')
_INT_RE = _re.compile(r'[+-]?\d+')


def _one_float(tok):
    m = _FLOAT_RE.match(tok)
    if not m:
        return None, False
    t = m.group(0)
    try:
        if 'x' in t or 'X' in t:
            sign = -1.0 if t.startswith('-') else 1.0
            body = t.lstrip('+-')
            if 'p' not in body and 'P' not in body:
                body += 'p0'
            v = sign * float.fromhex(body)
        else:
            v = float(t)
    except (ValueError, OverflowError):
        return None, False
    return f32(v), m.end() == len(tok)


def c_floats(text, limit=10):
    """Floats as sscanf("%f %f ...") reads them: stop at the first token that
    is not a number, and after a number followed by other characters."""
    out = []
    for tok in text.split():
        if len(out) >= limit:
            break
        v, whole = _one_float(tok)
        if v is None:
            break
        out.append(v)
        if not whole:
            break
    return out


def c_ints(text, limit):
    out = []
    for tok in text.split():
        if len(out) >= limit:
            break
        m = _INT_RE.match(tok)
        if not m:
            break
        out.append(int(m.group(0)))
        if m.end() != len(tok):
            break
    return out


def c_int(text):
    """Parse(char const*, int&): %d, else the words TRUE/FALSE (any case),
    else None (the field keeps its value)."""
    v = c_ints(text, 1)
    if v:
        return v[0]
    w = text.split()[0].upper() if text.split() else ''
    return {'TRUE': 1, 'FALSE': 0}.get(w)


def c_bool(text):
    w = text.split()[0].lower() if text.split() else ''
    return {'true': 1, 'false': 0, '1': 1, '0': 0}.get(w)


def c_word(text):
    t = text.split()
    return t[0] if t else ''


def axis_angle_to_quat(x, y, z, a):
    """xyzw, as the engine converts `orientation x y z angle` and 5-float
    orientation key rows: the axis goes through Vector::Normalize, which
    turns a zero axis into (1, 0, 0) (spec MDL-ASCII-032)."""
    ln = math.sqrt(x * x + y * y + z * z)
    if ln == 0:
        x, y, z, ln = 1.0, 0.0, 0.0, 1.0
    s, c = math.sin(a / 2), math.cos(a / 2)
    return [f32(x / ln * s), f32(y / ln * s), f32(z / ln * s), f32(c)]


EMITTER_FLAG_BITS = {'p2p': 0x1, 'p2p_sel': 0x2, 'affectedbywind': 0x4, 'm_istinted': 0x8,
                     'bounce': 0x10, 'random': 0x20, 'inherit': 0x40, 'inheritvel': 0x80,
                     'inherit_local': 0x100, 'splat': 0x200, 'inherit_part': 0x400}
MESH_LISTS = ('verts', 'tverts', 'tverts1', 'tverts2', 'tverts3', 'normals', 'tangents', 'colors', 'faces')


class _Lines:
    def __init__(self, text):
        self.lines = text.split('\n')
        self.i = 0

    def next(self):
        """The next line with leading whitespace removed, or None."""
        if self.i >= len(self.lines):
            return None
        ln = self.lines[self.i]
        self.i += 1
        return ln.lstrip(' \t\r\v\f')

    def raw(self):
        if self.i >= len(self.lines):
            return None
        ln = self.lines[self.i]
        self.i += 1
        return ln

    def rows(self, rest):
        """A list's rows (MDL-ASCII-050): with a count, that many lines,
        skipping only truly empty ones; without, up to `endlist`."""
        count = c_ints(rest, 1)
        rows = []
        if count:
            while len(rows) < count[0]:
                ln = self.raw()
                if ln is None:
                    break
                if ln == '' or ln[0] in '\r\0':
                    continue
                rows.append(ln)
            return rows
        while True:
            ln = self.raw()
            if ln is None:
                break
            if ln == '' or ln[0] in '\r\0':
                continue
            if ln.lstrip(' \t').startswith('endlist'):
                break
            rows.append(ln)
        return rows


def _new_node(ntype, name):
    flags = TYPE_FLAGS.get(ntype.lower(), F_HEADER)
    nd = {'name': name, 'parent': None, 'type': NODE_TYPES[flags], 'flags': flags, 'controllers': [],
          '_parent_set': False}
    if flags & F_MESH:
        nd['mesh'] = {'textures': ['', '', '', ''], '_lists': {}}
    if flags & F_SKIN:
        nd['skin'] = {}
    if flags & F_LIGHT:
        nd['light'] = {}
    if flags & F_EMITTER:
        nd['emitter'] = {}
    if flags & F_REFERENCE:
        nd['reference'] = {}
    if flags & F_DANGLY:
        nd['dangly'] = {}
    if flags & F_ANIM:
        nd['animmesh'] = {}
    return nd


def _set_ctrl(nd, cdef, keys, cols, bezier):
    c = {'id': cdef['id'], 'name': cdef['name'], 'columns': cols, 'bezier': bezier, 'keys': keys}
    nd['controllers'] = [x for x in nd['controllers'] if x['id'] != cdef['id']] + [c]


def _key_rows(nd, cdef, rows, bezier):
    """AddGenericController / AddBezierController (MDL-CTRL-030..032)."""
    parsed = []
    for r in rows:
        fl = c_floats(r, 10)
        if not fl:
            fl = [0.0]
        if len(fl) == 5 and not bezier:
            fl = [fl[0]] + axis_angle_to_quat(*fl[1:5])
        parsed.append(fl)
    if not parsed:
        _set_ctrl(nd, cdef, [], cdef['columns'], bezier)
        return
    n0 = len(parsed[0])
    if bezier:
        cols = (n0 - 1) // 3
        keys = [{'t': num(fl[0]), 'v': nums(fl[1:1 + cols]), 'in': nums(fl[1 + cols:1 + 2 * cols]),
                 'out': nums(fl[1 + 2 * cols:1 + 3 * cols])} for fl in parsed]
    else:
        cols = n0 - 1
        keys = [{'t': num(fl[0]), 'v': nums(fl[1:1 + cols])} for fl in parsed]
    _set_ctrl(nd, cdef, keys, cols, bezier)


def _aabb_tree(first_rest, lines):
    """Parse(char const*, AABB*&): one entry per line (min3 max3 face),
    preorder, an entry with face -1 followed by its two children."""
    entries = []

    def entry(text):
        fl = c_floats(text, 6)
        ints = c_ints(' '.join(text.split()[6:]), 1)
        face = ints[0] if ints else 0
        fl += [0.0] * (6 - len(fl))
        entries.append({'min': nums(fl[0:3]), 'max': nums(fl[3:6]), 'face': face})
        if face == -1 and len(entries) < 1 << 16:
            for _ in range(2):
                ln = lines.next()
                if ln is None:
                    return
                entry(ln)
    if c_floats(first_rest):
        entry(first_rest)
    else:
        ln = lines.next()
        if ln is not None:
            entry(ln)
    return entries


def _node_field(nd, line, lines):
    if line.startswith('parent'):
        name = c_word(line[6:])
        nd['_parent_set'] = True
        nd['parent'] = None if name.upper() == 'NULL' or not name else name
        return
    t = line.split(None, 1)
    if not t:
        return
    k, rest = t[0].lower(), (t[1] if len(t) > 1 else '')
    flags = nd['flags']
    mesh = nd.get('mesh')
    # controllers: static value, key list, bezier key list
    for suffix, bezier, is_list in (('bezierkey', True, True), ('key', False, True), ('', False, False)):
        if suffix and not k.endswith(suffix):
            continue
        cdef = controller_by_name(flags, k[:len(k) - len(suffix)] if suffix else k)
        if cdef is None:
            continue
        if is_list:
            _key_rows(nd, cdef, lines.rows(rest), bezier)
        else:
            fl = c_floats(rest, 10)
            if cdef['name'] == 'orientation' and len(fl) == 4:
                fl = axis_angle_to_quat(*fl)
            _set_ctrl(nd, cdef, [{'t': 0, 'v': nums(fl)}], len(fl), False)
        return
    if mesh is not None:
        if k in MESH_LISTS:
            mesh['_lists'][k] = lines.rows(rest)
            return
        if k in ('diffuse', 'ambient', 'specular'):
            fl = c_floats(rest, 3)
            old = mesh.get(k, [1, 1, 1] if k != 'specular' else [0, 0, 0])
            mesh[k] = nums(fl + [fval for fval in old[len(fl):]])
            return
        if k == 'shininess':
            fl = c_floats(rest, 1)
            if fl:
                mesh[k] = num(fl[0])
            return
        if k in ('shadow', 'beaming', 'render', 'transparencyhint', 'tilefade'):
            v = c_int(rest)
            if v is not None:
                mesh[k] = v & 0xFFFFFFFF
            return
        if k == 'rotatetexture':
            v = c_bool(rest)
            if v is not None:
                mesh[k] = v
            return
        if k in ('bitmap', 'texture0', 'texture1', 'texture2', 'materialname'):
            slot = {'bitmap': 0, 'texture0': 0, 'texture1': 1, 'texture2': 2, 'materialname': 3}[k]
            mesh['textures'][slot] = c_word(rest)[:63]
            return
        if k == 'renderhint':
            mesh['renderhint'] = {'normalandspecmapped': 2, 'normaltangents': 3, 'none': 1}.get(
                c_word(rest).lower(), 0)
            return
        if k == 'weights' and 'skin' in nd:
            ws = []
            for r in lines.rows(rest):
                tok, infl = r.split(), []
                for j in range(0, len(tok) - 1, 2):
                    fl = c_floats(tok[j + 1], 1)
                    if fl:
                        infl.append([tok[j], num(fl[0])])
                ws.append(infl)
            nd['skin']['_weights'] = ws
            return
        if k == 'constraints' and 'dangly' in nd:
            nd['dangly']['constraints'] = [num((c_floats(r, 1) or [0.0])[0]) for r in lines.rows(rest)]
            return
        if k in ('displacement', 'tightness', 'period') and 'dangly' in nd:
            fl = c_floats(rest, 1)
            if fl:
                nd['dangly'][k] = num(fl[0])
            return
        if k in ('animverts', 'animtverts', 'sampleperiod') and 'animmesh' in nd:
            if k == 'sampleperiod':
                fl = c_floats(rest, 1)
                if fl:
                    nd['animmesh'][k] = num(fl[0])
            else:
                w = 3 if k == 'animverts' else 2
                nd['animmesh'][k] = [nums((c_floats(r, 3) + [0.0, 0.0, 0.0])[:w]) for r in lines.rows(rest)]
            return
        if k == 'aabb' and flags & F_AABB:
            nd['aabb'] = _aabb_tree(rest, lines)
            return
    if 'light' in nd:
        lt = nd['light']
        if k in ('ambientonly', 'shadow', 'isdynamic', 'ndynamictype', 'affectdynamic', 'lightpriority',
                 'generateflare', 'fadinglight'):
            v = c_int(rest)
            if v is not None:
                lt['ndynamictype' if k == 'isdynamic' else k] = v
            return
        if k == 'flareradius':
            fl = c_floats(rest, 1)
            if fl:
                lt[k] = num(fl[0])
            return
        if k in ('texturenames', 'flaresizes', 'flarepositions', 'flarecolorshifts'):
            rows = lines.rows(rest)
            if k == 'texturenames':
                lt[k] = [c_word(r) for r in rows]
            elif k == 'flarecolorshifts':
                lt[k] = [nums((c_floats(r, 3) + [0.0] * 3)[:3]) for r in rows]
            else:
                lt[k] = [num((c_floats(r, 1) or [0.0])[0]) for r in rows]
            return
    if 'emitter' in nd:
        em = nd['emitter']
        if k in ('update', 'render', 'blend', 'texture', 'chunkname'):
            em[k] = c_word(rest)
        elif k in ('deadspace', 'blastradius', 'blastlength'):
            fl = c_floats(rest, 1)
            if fl:
                em[k] = num(fl[0])
        elif k in ('xgrid', 'ygrid', 'spawntype', 'twosidedtex', 'loop', 'renderorder'):
            v = c_int(rest)
            if v is not None:
                em[k] = v & (0xFFFF if k == 'renderorder' else 0xFFFFFFFF)
        elif k in EMITTER_FLAG_BITS:
            v = c_bool(rest)
            if v is not None:
                em['flags'] = (em.get('flags', 0) | EMITTER_FLAG_BITS[k]) if v else \
                    (em.get('flags', 0) & ~EMITTER_FLAG_BITS[k])
        return
    if 'reference' in nd:
        if k == 'refmodel':
            nd['reference']['refmodel'] = c_word(rest)
        elif k == 'reattachable':
            v = c_int(rest)
            if v is not None:
                nd['reference']['reattachable'] = v
        return
    if k == 'inheritcolor':
        v = c_int(rest)
        if v is not None:
            nd['inheritcolor'] = v


def _finish_mesh(nd):
    mesh = nd['mesh']
    L = mesh.pop('_lists')

    def vecs(name, w):
        return [(c_floats(r, w) + [0.0] * w)[:w] for r in L.get(name, [])]
    verts = vecs('verts', 3)
    tv = [vecs('tverts', 2), vecs('tverts1', 2), vecs('tverts2', 2), vecs('tverts3', 2)]
    norms = vecs('normals', 3) if 'normals' in L else []
    tans = vecs('tangents', 4) if 'tangents' in L else []
    cols = vecs('colors', 3) if 'colors' in L else []
    faces = [(c_ints(r, 8) + [0] * 8)[:8] for r in L.get('faces', [])]
    v = {'position': []}
    out_faces = []
    weights = nd.get('skin', {}).pop('_weights', None)
    corner_w = []
    for f in faces:
        idx = []
        for k in range(3):
            vi, ti = f[k], f[4 + k]
            v['position'].append(nums(verts[vi]) if 0 <= vi < len(verts) else [0, 0, 0])
            for s in range(4):
                if tv[s]:
                    v.setdefault('uv%d' % s, []).append(nums(tv[s][ti]) if 0 <= ti < len(tv[s]) else [0, 0])
            if norms:
                v.setdefault('normal', []).append(nums(norms[vi]) if 0 <= vi < len(norms) else [0, 0, 0])
            if tans:
                t = tans[vi] if 0 <= vi < len(tans) else [0, 0, 0, 1]
                v.setdefault('tangent', []).append(nums(t[:3]))
                v.setdefault('handedness', []).append(num(t[3]))
            if cols:
                c = cols[vi] if 0 <= vi < len(cols) else [0, 0, 0]
                v.setdefault('color', []).append([int(x * 255 + 0.5) & 0xff for x in c] + [255])
            if weights is not None:
                corner_w.append(weights[vi] if 0 <= vi < len(weights) else [])
            idx.append(len(v['position']) - 1)
        out_faces.append({'v': idx, 'material': f[7], 'smoothgroup': f[3]})
    mesh['vertices'] = v
    mesh['faces'] = out_faces
    mesh['face_count'] = len(out_faces)
    mesh['vertex_count'] = len(v['position'])
    if weights is not None:
        nd['skin']['weights'] = corner_w


def _read_tree(lines, nodes_out, anim):
    """Lines of beginmodelgeom or newanim up to a line starting with 'done'
    or 'end' (ImportMaxTree; MDL-ASCII-011)."""
    nodes = []
    while True:
        ln = lines.next()
        if ln is None:
            break
        if ln.startswith('done') or ln.startswith('end'):
            break
        if ln.startswith('node'):
            t = ln[4:].split()
            nd = _new_node(t[0] if t else 'dummy', t[1] if len(t) > 1 else '')
            while True:
                fl = lines.next()
                if fl is None or fl.startswith('endnode'):
                    break
                _node_field(nd, fl, lines)
            if 'mesh' in nd:
                _finish_mesh(nd)
            nodes.append(nd)
            continue
        if anim is not None:
            t = ln.split(None, 1)
            k = t[0].lower() if t else ''
            rest = t[1] if len(t) > 1 else ''
            if ln.startswith('event'):
                fl = c_floats(ln[5:], 1)
                words = ln[5:].split()
                anim['events'].append([num(fl[0]) if fl else 0, words[1] if len(words) > 1 else ''])
            elif k in ('length', 'transtime'):
                fl = c_floats(rest, 1)
                if fl:
                    anim[k] = num(fl[0])
            elif k == 'animroot':
                anim['animroot'] = c_word(rest)
    # The tree: the root is the node whose parent is NULL (the last one, if
    # several); nodes whose parent keyword was not read are not in it.
    roots = [n for n in nodes if n['_parent_set'] and n['parent'] is None]
    if not roots:
        return
    root = roots[-1]
    kids = {}
    for n in nodes:
        if n['_parent_set'] and n['parent'] is not None:
            kids.setdefault(n['parent'].lower(), []).append(n)
    # MdlNode::ReorderChildren (0x458120, MDL-NODE-012): where a child mesh
    # has transparencyhint > 0, the children are sorted: other nodes first,
    # then meshes by ascending hint (signed). std::sort is stable only up to
    # 16 children; this reader always sorts stably.
    def hint(n):
        h = n.get('mesh', {}).get('transparencyhint', 0)
        return h - (1 << 32) if h >= 1 << 31 else h
    for lst in kids.values():
        if any('mesh' in c and hint(c) > 0 for c in lst):
            lst.sort(key=lambda c: (0, 0) if 'mesh' not in c else (1, hint(c)))
    seen = set()

    def walk(n, parent):
        if id(n) in seen:
            return
        seen.add(id(n))
        n['parent'] = parent
        nodes_out.append(n)
        for c in kids.get(n['name'].lower(), []):
            walk(c, n['name'])
    walk(root, None)
    for n in nodes_out:
        n.pop('_parent_set', None)


def read_ascii(text):
    """Read an ASCII model into the JSON view.

    Geometry-node values become one-key controllers at t = 0, as a compile
    stores them, and meshes one vertex per face corner (the ASCII has no GPU
    vertex list), so they compare with a decoded binary by face corner.
    """
    view = {'format': 'mdl-view/1', 'source': 'ascii',
            'model': {'name': '', 'classification': 0, 'fog': 1, 'animationscale': 1, 'supermodel': ''},
            'nodes': [], 'animations': []}
    model = view['model']
    lines = _Lines(text)
    try:
        _read_model(view, model, lines)
    finally:
        # A weight of 0, or on a name that is no node of the model, is no
        # influence (E26): the bind leaves it out.
        names = {n['name'].lower() for n in view['nodes']}
        for n in view['nodes']:
            if 'weights' in n.get('skin', {}):
                n['skin']['weights'] = [[[b, w] for b, w in c if fval(w) > 0 and b.lower() in names]
                                        for c in n['skin']['weights']]
    return view


def _read_model(view, model, lines):
    while True:
        ln = lines.next()
        if ln is None:
            break
        low = ln.lower()
        words = ln.split()
        if low.startswith('newmodel'):
            model['name'] = words[1] if len(words) > 1 else ''
        elif low.startswith('setsupermodel'):
            model['supermodel'] = words[2] if len(words) > 2 else ''
        elif low.startswith('setanimationscale'):
            fl = c_floats(ln[17:], 1)
            if fl:
                model['animationscale'] = num(fl[0])
        elif low.startswith('classification'):
            w = words[1].lower() if len(words) > 1 else ''
            model['classification'] = {'tile': 2, 'character': 4, 'effect': 1, 'effects': 1,
                                       'door': 8}.get(w, model['classification'])
        elif low.startswith('ignorefog'):
            v = c_int(ln[9:])
            if v is not None:
                model['fog'] = 0 if v else 1
        elif low.startswith('beginmodelgeom'):
            _read_tree(lines, view['nodes'], None)
        elif low.startswith('newanim'):
            anim = {'name': words[1] if len(words) > 1 else '', 'length': 0, 'transtime': 0,
                    'animroot': '', 'events': [], 'nodes': []}
            _read_tree(lines, anim['nodes'], anim)
            view['animations'].append(anim)


def read_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) >= 4 and data[:4] == b'\0\0\0\0':
        return read_binary(data)
    return read_ascii(data.decode('latin-1'))


if __name__ == '__main__':
    import json
    import sys
    for p in sys.argv[1:]:
        print(json.dumps(read_file(p), indent=1))
