#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Make engine goldens: the game's own compile of each probe.

For each probe it copies the probe (and the files its manifest entry lists
under "with") into the game's user folder development/, runs
`nwmain-linux compilemodel <resref>` on an X display, and copies
modelcompiler/<resref>.mdl to conformance/goldens/. Everything it put in
development/ is removed afterwards, whatever happens: development/ outranks
haks and override, so a leftover probe would shadow real content.

Linux only (the game's compilemodel needs an X display; a private Xvfb is
started unless --display is given). Standard library only.

  make_goldens.py [--nwn-root DIR] [--user-dir DIR] [--display :N] [--out DIR] [probe ...]

With no probe names, every probe in the manifest with "golden": true.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PROBES = os.path.join(CONF, 'probes')
GOLDENS = os.path.join(CONF, 'goldens')


def default_root():
    for c in (os.environ.get('NWN_ROOT'),
              os.path.expanduser('~/.local/share/Steam/steamapps/common/Neverwinter Nights')):
        if c and os.path.isdir(c):
            return c
    return None


def default_user():
    for c in (os.environ.get('NWN_USER'), os.path.expanduser('~/.local/share/Neverwinter Nights')):
        if c and os.path.isdir(c):
            return c
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--nwn-root', default=default_root())
    ap.add_argument('--user-dir', default=default_user())
    ap.add_argument('--display', help='use this X display instead of starting Xvfb :99')
    ap.add_argument('--timeout', type=int, default=150)
    ap.add_argument('--out', default=GOLDENS, help='where to write the compiled models (default: goldens/)')
    ap.add_argument('probes', nargs='*')
    a = ap.parse_args()
    if not a.nwn_root or not a.user_dir:
        sys.exit('game install or user folder not found (--nwn-root, --user-dir)')
    exe_dir = os.path.join(a.nwn_root, 'bin', 'linux-x86')
    exe = os.path.join(exe_dir, 'nwmain-linux')
    dev = os.path.join(a.user_dir, 'development')
    out_dir = os.path.join(a.user_dir, 'modelcompiler')
    with open(os.path.join(CONF, 'manifest.json')) as f:
        manifest = {p['name']: p for p in json.load(f)['probes']}
    names = a.probes or [n for n, p in manifest.items() if p.get('golden')]

    # Every file to place, checked for collisions before anything is copied.
    place = []
    for n in names:
        p = manifest[n]
        for fn in [n + '.mdl'] + p.get('with', []):
            if fn not in place:
                place.append(fn)
    os.makedirs(dev, exist_ok=True)
    clash = [fn for fn in place if os.path.exists(os.path.join(dev, fn))]
    if clash:
        sys.exit('development/ already holds %s; not touching it' % ', '.join(clash))

    placed, xvfb, failed = [], None, []
    backup = tempfile.mkdtemp(prefix='mdlspec-mc-')
    try:
        for fn in place:
            shutil.copyfile(os.path.join(PROBES, fn), os.path.join(dev, fn))
            placed.append(fn)
        display = a.display
        if not display:
            if os.path.exists('/tmp/.X99-lock'):
                sys.exit('display :99 is in use; pass --display')
            xvfb = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1920x1400x24'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            display = ':99'
        env = dict(os.environ, DISPLAY=display)
        for n in names:
            target = os.path.join(out_dir, n + '.mdl')
            saved = None
            if os.path.exists(target):  # keep whatever was there before
                saved = os.path.join(backup, n + '.mdl')
                shutil.move(target, saved)
            try:
                r = subprocess.run([exe, 'compilemodel', n], cwd=exe_dir, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=a.timeout)
                log = r.stdout.decode('utf-8', 'replace')
            except subprocess.TimeoutExpired as e:
                log = (e.stdout or b'').decode('utf-8', 'replace') + '\n[timeout]'
            ok = 'Successfully compiled model' in log and os.path.exists(target)
            if ok:
                shutil.copyfile(target, os.path.join(a.out, n + '.mdl'))
                os.remove(target)
                print('%-18s ok (%d bytes)' % (n, os.path.getsize(os.path.join(a.out, n + '.mdl'))))
            else:
                failed.append(n)
                tail = '\n'.join(l for l in log.splitlines() if l.strip())[-1500:]
                print('%-18s FAILED\n%s' % (n, tail))
            if saved:
                if os.path.exists(target):
                    os.remove(target)
                shutil.move(saved, target)
    finally:
        for fn in placed:
            try:
                os.remove(os.path.join(dev, fn))
            except FileNotFoundError:
                pass
        if xvfb:
            xvfb.terminate()
            try:
                xvfb.wait(10)
            except subprocess.TimeoutExpired:
                xvfb.kill()
        shutil.rmtree(backup, ignore_errors=True)
        left = [fn for fn in place if os.path.exists(os.path.join(dev, fn))]
        print('development/ clean' if not left else 'LEFT IN development/: %s' % left)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
