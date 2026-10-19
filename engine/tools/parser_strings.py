#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""List the C strings each model parser in nwmain-linux refers to.

For every function in tables/keywords.yaml `parsers` (or the names given),
disassembles it with objdump and prints the strings its rip-relative `lea`
instructions point at, in order. This is how the keyword lists were read.

  parser_strings.py /path/to/nwmain-linux ['Class::Function(char const*)' ...]

Needs binutils (nm, objdump). Nothing from the binary is written anywhere.
"""
import re
import subprocess
import sys

DEFAULT = ['Model::InternalParseField(char const*)', 'Animation::InternalParseField(char const*)',
           'MdlNode::InternalParseField(char const*)', 'MdlNodeTriMesh::InternalParseField(char const*)',
           'MdlNodeSkin::InternalParseField(char const*)', 'MdlNodeDanglyMesh::InternalParseField(char const*)',
           'MdlNodeAnimMesh::InternalParseField(char const*)', 'MdlNodeAABB::InternalParseField(char const*)',
           'MdlNodeReference::InternalParseField(char const*)', 'MdlNodeCamera::InternalParseField(char const*)',
           'MdlNodeLight::InternalParseField(char const*)', 'MdlNodeEmitter::InternalParseField(char const*)',
           'MaxTree::InternalParseField(char const*)', 'ParseNode(char const*, MaxTree*)',
           'SharedMaterial::ExtractRenderHint(char const*)']


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exe = sys.argv[1]
    names = sys.argv[2:] or DEFAULT
    syms = subprocess.run(['nm', '-C', '-S', exe], capture_output=True, text=True).stdout.splitlines()
    hdr = subprocess.run(['objdump', '-h', exe], capture_output=True, text=True).stdout
    secs = [(m.group(1), int(m.group(3), 16), int(m.group(2), 16), int(m.group(4), 16))
            for m in re.finditer(r'^\s*\d+\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)', hdr, re.M)]
    data = open(exe, 'rb').read()

    def cstr(va):
        for name, vma, size, off in secs:
            if vma <= va < vma + size and name.startswith('.rodata'):
                o = off + va - vma
                s = data[o:data.index(b'\0', o)]
                if 0 < len(s) < 80 and all(32 <= c < 127 for c in s):
                    return s.decode()
        return None

    for want in names:
        for line in syms:
            parts = line.split(None, 3)
            if len(parts) == 4 and parts[3] == want:
                start, size = int(parts[0], 16), int(parts[1], 16)
                dis = subprocess.run(['objdump', '-d', '--no-show-raw-insn', '--start-address=%#x' % start,
                                      '--stop-address=%#x' % (start + size), exe],
                                     capture_output=True, text=True).stdout
                found = [cstr(int(m.group(1), 16)) for m in
                         re.finditer(r'lea\s+0x[0-9a-f]+\(%rip\),%\w+\s+#\s+([0-9a-f]+)', dis)]
                print('%s @ %#x' % (want, start))
                print('  ' + ' '.join(s for s in found if s))
                break
        else:
            print('%s: not found' % want)


if __name__ == '__main__':
    main()
