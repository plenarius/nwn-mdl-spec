#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""The repository's own checks (standard library only; run by CI).

1. Every table loads with runner/miniyaml.py (and, when PyYAML is installed,
   gives the same data as a full YAML reader).
2. Every rule ID mentioned anywhere is defined exactly once in spec/.
3. The expected files are what `mdlconf.py expect --second
   conformance/goldens/run2` makes from the goldens.
4. Every golden compiled against itself passes (the comparison is sound).
5. Every golden decodes identically with ksy/nwn_mdl.ksy.
"""
import collections
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import miniyaml  # noqa: E402
import mdlconf  # noqa: E402
import mdlview  # noqa: E402


def check_tables():
    bad = []
    try:
        import yaml  # optional
    except ImportError:
        yaml = None
    for f in sorted(glob.glob(os.path.join(ROOT, 'tables', '*.yaml')) + [os.path.join(ROOT, 'conformance', 'stock.yaml'),
                                                                          os.path.join(ROOT, 'ksy', 'nwn_mdl.ksy')]):
        try:
            a = miniyaml.load(f)
        except Exception as e:  # noqa: BLE001
            bad.append('%s: %s' % (f, e))
            continue
        if yaml is not None and yaml.safe_load(open(f)) != a:
            bad.append('%s: miniyaml and PyYAML disagree' % f)
    return bad


def check_rules():
    defined = collections.Counter()
    for f in glob.glob(os.path.join(ROOT, 'spec', '*.md')):
        for r in re.findall(r'\*\*(MDL-[A-Z]+-\d{3})\*\*', open(f).read()):
            defined[r] += 1
    bad = ['%s defined %d times' % (r, n) for r, n in defined.items() if n > 1]
    for f in glob.glob(os.path.join(ROOT, '**', '*'), recursive=True):
        if os.path.isdir(f) or '/goldens/' in f or '/.git/' in f or not f.endswith(('.md', '.yaml', '.json', '.py', '.ksy')):
            continue
        for r in set(re.findall(r'MDL-[A-Z]+-\d{3}', open(f, errors='replace').read())):
            if r not in defined:
                bad.append('%s: %s is not defined' % (os.path.relpath(f, ROOT), r))
    return bad


def check_expected():
    bad = []
    tmp = tempfile.mkdtemp(prefix='mdlspec-self-')
    orig = os.path.join(ROOT, 'conformance', 'expected')
    for p in mdlconf.load_manifest():
        g = os.path.join(ROOT, 'conformance', 'goldens', p['name'] + '.mdl')
        if not os.path.exists(g):
            continue
        exp = json.load(open(os.path.join(orig, p['name'] + '.json')))
        data = open(g, 'rb').read()
        fresh = mdlconf.normalise(mdlview.read_binary(data))
        g2 = os.path.join(ROOT, 'conformance', 'goldens', 'run2', p['name'] + '.mdl')
        vol = set()
        if os.path.exists(g2):
            f1 = dict(mdlconf.flat(fresh))
            f2 = dict(mdlconf.flat(mdlconf.normalise(mdlview.read_binary(open(g2, 'rb').read()))))
            vol = {k for k in f1 if f1[k] != f2.get(k)}
        if sorted(vol) != exp['volatile']:
            bad.append('%s: volatile fields differ' % p['name'])
        for k in ('model', 'nodes', 'animations'):
            if json.loads(json.dumps(fresh[k])) != exp[k]:
                bad.append('%s: %s differs from the golden' % (p['name'], k))
        rep = mdlconf.compare(exp, mdlview.read_binary(data), 'compile')
        if rep.items:
            bad.append('%s: the golden does not pass against itself: %s' % (p['name'], rep.items[:2]))
    os.rmdir(tmp)
    return bad


def check_ksy():
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'ksy', 'check_ksy.py')], capture_output=True, text=True)
    return [] if r.returncode == 0 else [r.stdout.strip().splitlines()[-1]]


def main():
    failed = False
    for name, fn in (('tables', check_tables), ('rule references', check_rules),
                     ('expected files', check_expected), ('ksy', check_ksy)):
        bad = fn()
        print('%-16s %s' % (name, 'ok' if not bad else 'FAIL'))
        for b in bad[:20]:
            print('    ' + b)
        failed |= bool(bad)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
