#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Decode every golden with ksy/nwn_mdl.ksy and compare with the runner's view.

A small interpreter for the Kaitai Struct features nwn_mdl.ksy uses (seq,
types, instances with pos/value/if, repeat: expr, u1/u2/u4/s2/s4/f4,
str/strz, contents, size). It is not Kaitai: it exists so the .ksy is
checked without kaitai-struct-compiler. Expressions are translated to
Python and evaluated with no builtins.

  check_ksy.py [golden.mdl ...]     (default: conformance/goldens/*.mdl)
  check_ksy.py --generated DIR [golden.mdl ...]
      the same check with the parser kaitai-struct-compiler generated into
      DIR (`kaitai-struct-compiler -t python --outdir DIR nwn_mdl.ksy`)
"""
import glob
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'runner'))
import miniyaml  # noqa: E402
import mdlview  # noqa: E402

PRIM = {'u1': '<B', 'u2': '<H', 'u4': '<I', 's2': '<h', 's4': '<i', 'f4': '<f'}
_EXPR_OK = re.compile(r'^[\w\s\.\+\-\*&|()<>=!\[\]]*$')


class Obj:
    def __init__(self, parent, root):
        self._parent = parent
        self._root = root if root is not None else self


def expr(src, obj):
    if isinstance(src, int):
        return src
    s = str(src)
    if not _EXPR_OK.match(s):
        raise ValueError('expression outside the supported subset: %r' % s)
    py = re.sub(r'\bnot\b', ' not ', s)
    env = {'_root': obj._root, '_parent': obj._parent}
    for k, v in vars(obj).items():
        env[k] = v
    return eval(py, {'__builtins__': {}}, env)  # noqa: S307 - restricted subset


class Reader:
    def __init__(self, ksy, data):
        self.types = ksy['types']
        self.data = data
        self.budget = 2_000_000

    def read_field(self, spec, obj, pos):
        """Returns (value, new pos)."""
        self.budget -= 1
        if self.budget < 0:
            raise RuntimeError('budget exhausted (cycle?)')
        n = 1
        rep = spec.get('repeat')
        if rep == 'expr':
            n = expr(spec['repeat-expr'], obj)
        elif rep is not None:
            raise ValueError('unsupported repeat %r' % rep)
        out = []
        for _ in range(n):
            v, pos = self.read_one(spec, obj, pos)
            out.append(v)
        return (out if rep else out[0]), pos

    def read_one(self, spec, obj, pos):
        if 'contents' in spec:
            want = bytes(spec['contents'])
            got = self.data[pos:pos + len(want)]
            if got != want:
                raise ValueError('contents mismatch at %#x' % pos)
            return got, pos + len(want)
        t = spec.get('type')
        if t in PRIM:
            fmt = PRIM[t]
            size = struct.calcsize(fmt)
            if pos + size > len(self.data) or pos < 0:
                raise ValueError('read past the end at %#x' % pos)
            return struct.unpack_from(fmt, self.data, pos)[0], pos + size
        if t == 'str':
            size = expr(spec['size'], obj)
            raw = self.data[pos:pos + size]
            if 'terminator' in spec:
                raw = raw.split(bytes([spec['terminator']]), 1)[0]
            return raw.decode('latin-1'), pos + size
        if t == 'strz':
            end = self.data.index(b'\0', pos)
            return self.data[pos:end].decode('latin-1'), end + 1
        if t is None and 'size' in spec:
            size = expr(spec['size'], obj)
            return self.data[pos:pos + size], pos + size
        if t in self.types:
            return self.read_type(t, obj, pos)
        raise ValueError('unsupported type %r' % t)

    def read_type(self, name, parent, pos):
        tdef = self.types[name]
        obj = Obj(parent, parent._root if parent is not None else None)
        obj._type = name
        start = pos
        for f in tdef.get('seq', []) or []:
            if 'if' in f and not expr(f['if'], obj):
                setattr(obj, f['id'], None)
                continue
            v, pos = self.read_field(f, obj, pos)
            setattr(obj, f['id'], v)
        obj._size = pos - start
        for iname, inst in (tdef.get('instances') or {}).items():
            if 'if' in inst and not expr(inst['if'], obj):
                setattr(obj, iname, None)
                continue
            if 'value' in inst:
                setattr(obj, iname, expr(inst['value'], obj))
                continue
            p = expr(inst['pos'], obj)
            v, _ = self.read_field(inst, obj, p)
            setattr(obj, iname, v)
        return obj, pos

    def read_root(self, ksy):
        root = Obj(None, None)
        pos = 0
        for f in ksy.get('seq', []):
            v, pos = self.read_field(f, root, pos)
            setattr(root, f['id'], v)
        for iname, inst in (ksy.get('instances') or {}).items():
            v, _ = self.read_field(inst, root, expr(inst['pos'], root))
            setattr(root, iname, v)
        return root


def opt(obj, name):
    """A conditional field: generated Kaitai parsers leave it unset when its
    `if` is false, where the interpreter sets None."""
    return getattr(obj, name, None)


def walk(node, out):
    out.append(node)
    for ref in opt(node, 'child_list') or []:
        walk(ref.node, out)


def near(a, b):
    a, b = mdlview.fval(a) if hasattr(mdlview, 'fval') else a, b
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    return a == b or (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-6 * max(1, abs(a), abs(b))


def check(path, ksy, generated=None):
    data = open(path, 'rb').read()
    root = generated.from_bytes(data) if generated else Reader(ksy, data).read_root(ksy)
    view = mdlview.read_binary(data)
    problems = []

    def eq(what, a, b):
        if a != b:
            problems.append('%s: ksy %r, view %r' % (what, a, b))

    m = root.model
    eq('model name', m.geometry.name, view['model']['name'])
    eq('classification', m.classification, view['model']['classification'])
    eq('node_count', m.geometry.node_count, view['model']['node_count'])
    eq('supermodel', m.supermodel_name, view['model']['supermodel'])
    nodes = []
    walk(m.geometry.root_node, nodes)
    eq('nodes', [n.name for n in nodes], [n['name'] for n in view['nodes']])
    for kn, vn in zip(nodes, view['nodes']):
        p = 'node %s' % kn.name
        eq(p + ' flags', kn.flags, vn['flags'])
        eq(p + ' number', kn.part_number, vn['number'])
        eq(p + ' controllers', [(c.type, c.rows, c.column_byte) for c in kn.controller_list],
           [(c['id'], len(c['keys']), c['colbyte']) for c in vn['controllers']])
        if opt(kn, 'mesh') is not None:
            me, vm = kn.mesh, vn['mesh']
            eq(p + ' vertex_count', me.vertex_count, vm['vertex_count'])
            eq(p + ' faces', [list(f.vertices) for f in me.face_list], [f['v'] for f in vm['faces']])
            eq(p + ' render_hint', me.render_hint, vm['renderhint'])
            eq(p + ' textures', [me.texture0, me.texture1, me.texture2, me.texture3], vm['textures'])
            if opt(me, 'positions') is not None:
                eq(p + ' positions', [mdlview.nums([v.x, v.y, v.z]) for v in me.positions],
                   vm['vertices'].get('position', []))
            # The view leaves out a stream in the tangent slot that is not
            # tangents (1.69 water's bump-map stream, MDL-BIN-048); the .ksy
            # describes the slot, not what it holds.
            if opt(me, 'tangents') is not None and 'tangent' in vm['vertices']:
                eq(p + ' tangents', [mdlview.nums([v.x, v.y, v.z]) for v in me.tangents], vm['vertices']['tangent'])
            if opt(me, 'index_list0') is not None:
                eq(p + ' index list', list(me.index_list0), vm['index_lists'][0] if vm['index_lists'] else [])
            if hasattr(me, '_size'):  # the interpreter's; generated parsers have none
                eq(p + ' header bytes', me._size, 512)
        if opt(kn, 'light') is not None:
            eq(p + ' light priority', kn.light.light_priority, vn['light']['lightpriority'])
            eq(p + ' flare textures', [t.value for t in kn.light.flare_texture_list], vn['light']['texturenames'])
            if hasattr(kn.light, '_size'):
                eq(p + ' light header bytes', kn.light._size, 92)
        if opt(kn, 'emitter') is not None:
            eq(p + ' emitter', [kn.emitter.update, kn.emitter.render, kn.emitter.blend, kn.emitter.flags],
               [vn['emitter'][k] for k in ('update', 'render', 'blend', 'flags')])
            if hasattr(kn.emitter, '_size'):
                eq(p + ' emitter header bytes', kn.emitter._size, 216)
        if opt(kn, 'reference') is not None:
            eq(p + ' refmodel', kn.reference.ref_model, vn['reference']['refmodel'])
        if opt(kn, 'dangly') is not None:
            eq(p + ' constraints', mdlview.nums(kn.dangly.constraint_list), vn['dangly']['constraints'])
        if opt(kn, 'aabb') is not None:
            entries = []

            def tree(e):
                entries.append({'min': mdlview.nums([e.bmin.x, e.bmin.y, e.bmin.z]),
                                'max': mdlview.nums([e.bmax.x, e.bmax.y, e.bmax.z]), 'face': e.face, 'plane': e.plane})
                if e.left is not None:
                    tree(e.left)
                if e.right is not None:
                    tree(e.right)
            tree(kn.aabb.root)
            eq(p + ' aabb', entries, vn['aabb'])
    anims = [a.body for a in m.animation_list]
    eq('animations', [a.geometry.name for a in anims], [a['name'] for a in view['animations']])
    for ka, va in zip(anims, view['animations']):
        eq('anim %s events' % ka.geometry.name, [[mdlview.num(e.time), e.name] for e in ka.event_list], va['events'])
        an = []
        walk(ka.geometry.root_node, an)
        eq('anim %s nodes' % ka.geometry.name, [n.name for n in an], [n['name'] for n in va['nodes']])
        for kn, vn in zip(an, va['nodes']):
            eq('anim node %s controllers' % kn.name, [(c.type, c.rows, c.column_byte) for c in kn.controller_list],
               [(c['id'], len(c['keys']), c['colbyte']) for c in vn['controllers']])
            if opt(kn, 'anim') is not None and opt(kn.anim, 'vertex_sets') is not None:
                nv, sets = kn.mesh.vertex_count, kn.anim.vertex_set_count
                setmajor = [mdlview.nums([kn.anim.vertex_sets[v * sets + s].x, kn.anim.vertex_sets[v * sets + s].y,
                                          kn.anim.vertex_sets[v * sets + s].z]) for s in range(sets) for v in range(nv)]
                eq('anim node %s vertex sets' % kn.name, setmajor, vn['animmesh'].get('animverts'))
    return problems


def main():
    args = sys.argv[1:]
    generated = None
    if args[:1] == ['--generated']:
        # A parser kaitai-struct-compiler generated from nwn_mdl.ksy
        # (`-t python --outdir DIR`); needs the kaitaistruct runtime.
        sys.path.insert(0, args[1])
        from nwn_mdl import NwnMdl
        generated, args = NwnMdl, args[2:]
    ksy = miniyaml.load(os.path.join(HERE, 'nwn_mdl.ksy'))
    files = args or sorted(glob.glob(os.path.join(ROOT, 'conformance', 'goldens', '*.mdl')))
    bad = 0
    for f in files:
        try:
            problems = check(f, ksy, generated)
        except Exception as e:  # noqa: BLE001 - report and go on
            problems = ['decode failed: %s' % e]
        name = os.path.basename(f)
        if problems:
            bad += 1
            print('%-20s FAIL' % name)
            for p in problems[:8]:
                print('    ' + p)
        else:
            print('%-20s ok' % name)
    print('%d of %d files decode identically with nwn_mdl.ksy (%s)' % (
        len(files) - bad, len(files), 'kaitai-struct-compiler parser' if generated else 'interpreter'))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
