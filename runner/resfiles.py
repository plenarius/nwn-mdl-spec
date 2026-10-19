# SPDX-License-Identifier: CC0-1.0
"""Read resources out of the user's NWN:EE install (standard library only):
KEY/BIF (the base game) and ERF/HAK. Used by the stock-model tests, which
name stock models and never ship them."""
import os
import struct

RES_MDL = 2002


class KeyArchive:
    def __init__(self, root, key='nwn_base.key'):
        self.root = root
        path = os.path.join(root, 'data', key)
        with open(path, 'rb') as f:
            d = f.read()
        if d[:8] not in (b'KEY V1  ', b'KEY V1.1'):
            raise ValueError('%s: not a KEY V1 file' % path)
        nbif, nkey, off_files, off_keys = struct.unpack_from('<4I', d, 8)
        self.bifs = []
        for i in range(nbif):
            size, name_off, name_len, _drives = struct.unpack_from('<IIHH', d, off_files + 12 * i)
            name = d[name_off:name_off + name_len].split(b'\0', 1)[0].decode('latin-1').replace('\\', '/')
            self.bifs.append(name)
        self.entries = {}
        for i in range(nkey):
            o = off_keys + 22 * i
            resref = d[o:o + 16].split(b'\0', 1)[0].decode('latin-1').lower()
            rtype, resid = struct.unpack_from('<HI', d, o + 16)
            self.entries[(resref, rtype)] = resid
        self._bif_cache = {}

    def _bif(self, i):
        if i not in self._bif_cache:
            p = os.path.join(self.root, self.bifs[i])
            if not os.path.exists(p):
                p = os.path.join(self.root, 'data', os.path.basename(self.bifs[i]))
            with open(p, 'rb') as f:
                d = f.read()
            if d[:8] != b'BIFFV1  ':
                raise ValueError('%s: unsupported BIF version %r' % (p, d[:8]))
            nvar, _nfix, off_var = struct.unpack_from('<3I', d, 8)
            table = {}
            for j in range(nvar):
                rid, off, size, _t = struct.unpack_from('<4I', d, off_var + 16 * j)
                table[rid & 0xFFFFF] = (off, size)
            self._bif_cache = {i: (d, table)}  # keep one BIF in memory
        return self._bif_cache[i]

    def names(self, rtype=RES_MDL):
        return sorted(r for (r, t) in self.entries if t == rtype)

    def get(self, resref, rtype=RES_MDL):
        resid = self.entries.get((resref.lower(), rtype))
        if resid is None:
            return None
        d, table = self._bif(resid >> 20)
        off, size = table[resid & 0xFFFFF]
        return d[off:off + size]


class Erf:
    """ERF/HAK/MOD V1.0."""

    def __init__(self, path):
        with open(path, 'rb') as f:
            self.d = d = f.read()
        if d[4:8] != b'V1.0':
            raise ValueError('%s: unsupported ERF version %r' % (path, d[4:8]))
        nentries, = struct.unpack_from('<I', d, 16)
        off_keys, off_res = struct.unpack_from('<II', d, 24)
        self.entries = {}
        for i in range(nentries):
            o = off_keys + 24 * i
            resref = d[o:o + 16].split(b'\0', 1)[0].decode('latin-1').lower()
            resid, rtype = struct.unpack_from('<IH', d, o + 16)
            off, size = struct.unpack_from('<II', d, off_res + 8 * resid)
            self.entries[(resref, rtype)] = (off, size)

    def get(self, resref, rtype=RES_MDL):
        e = self.entries.get((resref.lower(), rtype))
        return None if e is None else self.d[e[0]:e[0] + e[1]]


def default_root():
    for c in (os.environ.get('NWN_ROOT'),
              os.path.expanduser('~/.local/share/Steam/steamapps/common/Neverwinter Nights'),
              os.path.expanduser('~/Library/Application Support/Steam/steamapps/common/Neverwinter Nights'),
              'C:/Program Files (x86)/Steam/steamapps/common/Neverwinter Nights'):
        if c and os.path.exists(os.path.join(c, 'data', 'nwn_base.key')):
            return c
    return None
