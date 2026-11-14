#!/usr/bin/env bash
# Regenerate the bindings for this library's own model - the types it hands back.
#
# Not to be confused with reconcile_zmk_model/, which pulls ZMK's definitions from
# upstream. These two scripts exist separately because the files do: keyboard.proto
# is ours to change, and the vendored protos are someone else's contract that we
# only ever track.
set -euo pipefail
# Anchored by searching for the repo root rather than counting ../ hops, so this
# stays correct wherever the script is moved to.
root() {
  local dir; dir="$(cd "$(dirname "$0")" && pwd)"
  while [ "$dir" != "/" ]; do
    [ -f "$dir/pyproject.toml" ] && { echo "$dir"; return; }
    dir="$(dirname "$dir")"
  done
  echo "cannot find the repository root (no pyproject.toml above $0)" >&2
  exit 1
}
cd "$(root)"

# -Isrc, not -Isrc/zmk_studio_client/proto, so the descriptor records this file as
# "zmk_studio_client/proto/keyboard.proto". That full path is what a consumer's own
# .proto writes in its import line, and it is what keeps the name unique in the
# global descriptor pool a process shares. A bare "keyboard.proto" would be one
# collision away from a confusing failure in somebody else's program.
python3 -m grpc_tools.protoc -Isrc \
  --python_out=src --pyi_out=src src/zmk_studio_client/proto/keyboard.proto
echo "regenerated src/zmk_studio_client/proto/keyboard_pb2.py{,i} - review the diff"
