#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# nwn-mdl-spec adapter for cleanmodels (https://github.com/plenarius/cleanmodels).
#   cleanmodels.sh compile|decompile <in.mdl> <out.mdl>
# Set CLEANMODELS to the binary if it is not on PATH. cleanmodels searches
# the input's own folder for materials and supermodels, which is where the
# runner puts a probe's companion files.
set -e
CM=${CLEANMODELS:-cleanmodels}
case "$1" in
  compile)   exec "$CM" compile --quiet --color never "$2" "$3" ;;
  decompile) exec "$CM" decompile --quiet --color never "$2" "$3" ;;
  *) echo "usage: $0 compile|decompile <in> <out>" >&2; exit 2 ;;
esac
