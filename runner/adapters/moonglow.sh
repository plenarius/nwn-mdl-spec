#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# nwn-mdl-spec adapter for Moonglow Toolset's mg-mdl (https://github.com/jadzziaa/moonglow-toolset).
#   moonglow.sh compile|decompile <in.mdl> <out.mdl>
# MGCONF is the binary built by adapters/moonglow/build.sh (default
# /tmp/mdlspec-mgconf/target/release/mgconf).
MG=${MGCONF:-/tmp/mdlspec-mgconf/target/release/mgconf}
exec "$MG" "$@"
