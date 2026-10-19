#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Survey the binary models in the user's install (nothing is copied).

Counts, per producer (told by the geometry header's function pointers),
the controller ids seen on each node class with their column bytes, and
lists the models that use ids of interest. Used for the corpus facts in
engine/behaviour.md (E64).

  scan_stock.py [--root NWN_ROOT] [--ids 144,220,464,...]
"""
import argparse
import collections
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'runner'))
import resfiles  # noqa: E402

PRODUCERS = {(0x0040BBC0, 0x0040BBD0): 'bioware', (0x0046AB0C, 0x0046AB1C): 'nwnmdlcomp',
             (0x4, 0x0): 'ee'}


def classes(flags):
    if flags & 0x4:
        return 'emitter'
    if flags & 0x2:
        return 'light'
    if flags & 0x20:
        return 'mesh'
    return 'base'


def scan(d, stats, hits, ids, name):
    if len(d) < 244 or d[:4] != b'\0\0\0\0':
        return
    fp = struct.unpack_from('<II', d, 12)
    prod = PRODUCERS.get(fp, 'other')
    stats['producer'][prod] += 1
    seen = set()

    def node(off, depth, anim):
        if off in seen or depth > 300 or off + 112 > len(d):
            return
        seen.add(off)
        flags = struct.unpack_from('<I', d, off + 108)[0]
        kp, kc = struct.unpack_from('<II', d, off + 84)
        cls = classes(flags)
        for i in range(min(kc, 512)):
            k = 12 + kp + 12 * i
            if k + 12 > len(d):
                break
            cid, = struct.unpack_from('<I', d, k)
            col = d[k + 10]
            stats['ctrl'][(prod, cls, cid, col)] += 1
            if cid in ids and cls in ('emitter', 'light'):
                hits[(cls, cid)].append(name)
            if col & 0x10 and col != 0xFF:
                hits[('bezier', col)].append(name)
        cp, cc = struct.unpack_from('<II', d, off + 72)
        for i in range(min(cc, 4096)):
            p = 12 + cp + 4 * i
            if p + 4 > len(d):
                break
            node(12 + struct.unpack_from('<I', d, p)[0], depth + 1, anim)

    node(12 + struct.unpack_from('<I', d, 12 + 72)[0], 0, False)
    ap, ac = struct.unpack_from('<II', d, 12 + 120)
    for i in range(min(ac, 4096)):
        p = 12 + ap + 4 * i
        if p + 4 > len(d):
            break
        a = 12 + struct.unpack_from('<I', d, p)[0]
        if a + 112 <= len(d):
            node(12 + struct.unpack_from('<I', d, a + 72)[0], 0, True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=resfiles.default_root())
    ap.add_argument('--ids', default='144,220,464,468,480,481,482,484,488')
    a = ap.parse_args()
    ids = {int(x) for x in a.ids.split(',')}
    key = resfiles.KeyArchive(a.root)
    stats = {'producer': collections.Counter(), 'ctrl': collections.Counter()}
    hits = collections.defaultdict(list)
    names = key.names()
    for n in names:
        scan(key.get(n), stats, hits, ids, n)
    print('models: %d (%s)' % (len(names), ', '.join('%s %d' % kv for kv in stats['producer'].most_common())))
    print('controller ids on emitters and lights, by producer (id: column bytes and counts):')
    by = collections.defaultdict(collections.Counter)
    for (prod, cls, cid, col), c in stats['ctrl'].items():
        if cls in ('emitter', 'light'):
            by[(cls, cid)][(prod, col)] += c
    for (cls, cid) in sorted(by):
        print('  %-7s %4d  %s' % (cls, cid, ', '.join('%s col %#x x%d' % (p, col, c) for (p, col), c in sorted(by[(cls, cid)].items()))))
    for k in sorted(hits, key=str):
        models = sorted(set(hits[k]))
        print('%s: %d model(s): %s' % (k, len(models), ' '.join(models[:12]) + (' ...' if len(models) > 12 else '')))


if __name__ == '__main__':
    main()
