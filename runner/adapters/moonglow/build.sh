#!/bin/sh
# Build the Moonglow adapter outside both repositories.
#   build.sh <moonglow-toolset checkout> [build dir, default /tmp/mdlspec-mgconf]
set -e
MG=$(cd "$1" && pwd)
OUT=${2:-/tmp/mdlspec-mgconf}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT/src"
cp "$HERE/src/main.rs" "$OUT/src/main.rs"
sed "s|@MOONGLOW@|$MG|" "$HERE/Cargo.toml.in" > "$OUT/Cargo.toml"
cd "$OUT" && cargo build --release -q
echo "$OUT/target/release/mgconf"
