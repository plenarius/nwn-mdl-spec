#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# nwn-mdl-spec adapter for cleanmodels (https://github.com/plenarius/cleanmodels).
#   cleanmodels.sh compile|decompile <in.mdl> <out.mdl>
# Set CLEANMODELS to the binary if it is not on PATH. cleanmodels searches
# the input's own folder for materials and supermodels, which is where the
# runner puts a probe's companion files. For `mdlconf.py roundtrip`, each
# folder in MDLCONF_RESOURCE_DIRS is passed as a --resource-dir.
set -e
CM=${CLEANMODELS:-cleanmodels}
verb=$1 in=$2 out=$3
set --
if [ -n "${MDLCONF_RESOURCE_DIRS:-}" ]; then
  old_ifs=$IFS; IFS=:
  for d in $MDLCONF_RESOURCE_DIRS; do set -- "$@" --resource-dir "$d"; done
  IFS=$old_ifs
fi
case "$verb" in
  compile)   exec "$CM" compile --quiet --color never "$@" "$in" "$out" ;;
  decompile) exec "$CM" decompile --quiet --color never "$@" "$in" "$out" ;;
  *) echo "usage: $0 compile|decompile <in> <out>" >&2; exit 2 ;;
esac
