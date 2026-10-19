# SPDX-License-Identifier: CC0-1.0
"""A reader for the YAML subset the tables use (standard library only).

The tables are plain YAML, readable by any YAML library. This reader only
handles what they use, so the runner needs nothing outside the standard
library:

  # comment
  key: scalar
  key:
    - {flow: mapping, list: [a, b]}
    - scalar
  key:
    subkey: scalar

Scalars: integers (decimal or 0x hex), floats, true/false/null, 'single' or
"double" quoted strings, and bare words. Anything else is an error.
"""
import re


class YamlError(ValueError):
    pass


def _scalar(tok):
    tok = tok.strip()
    if tok == '':
        return None
    if tok[0] in '"\'':
        if len(tok) < 2 or tok[-1] != tok[0]:
            raise YamlError('unterminated string: %r' % tok)
        return tok[1:-1]
    low = tok.lower()
    if low in ('true', 'false'):
        return low == 'true'
    if low in ('null', '~'):
        return None
    if re.fullmatch(r'[-+]?0x[0-9a-fA-F]+', tok):
        return int(tok, 16)
    if re.fullmatch(r'[-+]?\d+', tok):
        return int(tok)
    if re.fullmatch(r'[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?', tok):
        return float(tok)
    return tok


def _split_top(s):
    """Split a flow body on commas outside brackets and quotes."""
    out, depth, cur, q = [], 0, '', None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in '"\'':
            q = ch
            cur += ch
        elif ch in '[{':
            depth += 1
            cur += ch
        elif ch in ']}':
            depth -= 1
            cur += ch
        elif ch == ',' and depth == 0:
            out.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _flow(s):
    s = s.strip()
    if s.startswith('{'):
        if not s.endswith('}'):
            raise YamlError('bad flow mapping: %r' % s)
        d = {}
        for part in _split_top(s[1:-1]):
            if ':' not in part:
                raise YamlError('bad flow mapping entry: %r' % part)
            k, v = part.split(':', 1)
            d[k.strip()] = _flow(v)
        return d
    if s.startswith('['):
        if not s.endswith(']'):
            raise YamlError('bad flow list: %r' % s)
        return [_flow(p) for p in _split_top(s[1:-1])]
    return _scalar(s)


def _strip_comment(line):
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch
        elif ch == '#' and (i == 0 or line[i - 1] in ' \t'):
            return line[:i].rstrip()
    return line.rstrip()


def loads(text):
    lines = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip(' ')), line.strip()))
    pos = 0

    def block(indent):
        nonlocal pos
        if pos < len(lines) and lines[pos][1].startswith('- '):
            seq = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith('- '):
                seq.append(_flow(lines[pos][1][2:]))
                pos += 1
            return seq
        mapping = {}
        while pos < len(lines) and lines[pos][0] == indent:
            ind, body = lines[pos]
            if ':' not in body:
                raise YamlError('expected key: value, got %r' % body)
            k, v = body.split(':', 1)
            pos += 1
            if v.strip():
                mapping[k.strip()] = _flow(v)
            elif pos < len(lines) and lines[pos][0] > indent:
                mapping[k.strip()] = block(lines[pos][0])
            else:
                mapping[k.strip()] = None
        return mapping

    result = block(lines[0][0] if lines else 0)
    if pos != len(lines):
        raise YamlError('unexpected indentation at %r' % (lines[pos][1],))
    return result


def load(path):
    with open(path, encoding='utf-8') as f:
        return loads(f.read())
