#!/usr/bin/env bash
# Keep the vendored copy honest against upstream. See README.md beside this file.
set -euo pipefail
# Anchored at the repo root by SEARCHING for it, not by counting ../ hops from
# this file. A hop count is a path encoded in two places: move the script and it
# breaks silently, resolving to some other directory that may well exist. This
# walks up to the directory holding pyproject.toml instead, so the script can be
# moved anywhere in the tree and still be correct.
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

REPO=zmkfirmware/zmk-studio-messages
FILES=(meta core behaviors keymap studio)
VENDOR=src/third_party/zmk_studio_messages
PROTO="$VENDOR/proto"
PKG=src/zmk_studio_client
PINNED="$(tr -d '[:space:]' < "$VENDOR/revision.txt")"

fetch_to() {  # <sha> <dir>
  mkdir -p "$2"
  for f in "${FILES[@]}"; do
    gh api "repos/$REPO/contents/proto/zmk/$f.proto?ref=$1" --jq .content | base64 -d > "$2/$f.proto"
  done
}

fetch_license_to() {  # <sha> <path>
  # MIT asks that copies carry the permission notice, not merely name the licence,
  # so upstream's LICENSE is vendored beside the protos and moves with the pin.
  gh api "repos/$REPO/contents/LICENSE?ref=$1" --jq .content | base64 -d > "$2"
}

apply_attribution() {
  # protoc embeds upstream's package, message and field names verbatim and writes no
  # copyright line, and these generated files - unlike third_party/ - are packaged and
  # distributed. Without this the wheel would ship ZMK's definitions under our licence
  # alone. Regeneration overwrites the files, so this runs after every regeneration.
  for f in "${FILES[@]}"; do
    target="$PKG/_pb/${f}_pb2.py"
    if ! grep -q 'SPDX-License-Identifier' "$target"; then
      awk 'NR==1{
             print
             print "# Generated from zmk-studio-messages:"
             print "#   Copyright (c) 2024 The ZMK Contributors"
             print "#   SPDX-License-Identifier: MIT"
             print "#   Full licence: https://github.com/zmkfirmware/zmk-studio-messages/blob/main/LICENSE"
             next
           }
           {print}' "$target" > "$target.tmp" && mv "$target.tmp" "$target"
    fi
    stub="$PKG/_pb/${f}_pb2.pyi"
    if [ -f "$stub" ] && ! grep -q 'SPDX-License-Identifier' "$stub"; then
      {
        echo "# Generated from zmk-studio-messages:"
        echo "#   Copyright (c) 2024 The ZMK Contributors"
        echo "#   SPDX-License-Identifier: MIT"
        echo "#   Full licence: https://github.com/zmkfirmware/zmk-studio-messages/blob/main/LICENSE"
        cat "$stub"
      } > "$stub.tmp" && mv "$stub.tmp" "$stub"
    fi
  done
}

compile_bindings() {
  # Upstream's protos import siblings by bare name (`import "meta.proto";`).
  # Compiling them directly registers unqualified names (`core.proto`, `keymap.proto`,
  # ...) in protobuf's process-global default descriptor pool, which collides at
  # import time with any other library in the consumer's process that defines a file
  # of the same bare name, and emits bare `import core_pb2` lines that require
  # mutating `sys.path`.
  #
  # Stage into a namespaced tree and rewrite sibling imports on the staged copy,
  # leaving third_party/ untouched so `check` continues to verify an unmodified copy.
  local stage; stage="$(mktemp -d)"
  mkdir -p "$stage/zmk_studio_client/_pb"
  for f in "${FILES[@]}"; do
    sed -E 's|^import "([^/"]+\.proto)";$|import "zmk_studio_client/_pb/\1";|' \
      "$PROTO/$f.proto" > "$stage/zmk_studio_client/_pb/$f.proto"
  done
  python3 -m grpc_tools.protoc -I"$stage" --python_out=src --pyi_out=src \
    "$stage"/zmk_studio_client/_pb/*.proto
  rm -rf "$stage"
  apply_attribution
}

case "${1:-check}" in
  check)
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    fetch_to "$PINNED" "$tmp"
    fetch_license_to "$PINNED" "$tmp/LICENSE"
    drift=0
    diff -ru "$tmp" "$PROTO" --exclude=LICENSE >/dev/null || drift=1
    diff -u "$tmp/LICENSE" "$VENDOR/LICENSE" >/dev/null || drift=1
    if [ "$drift" = "0" ]; then
      echo "clean: $PROTO and $VENDOR/LICENSE match upstream $PINNED"
    else
      echo "DRIFT: our copy differs from upstream $PINNED" >&2
      diff -ru "$tmp" "$PROTO" --exclude=LICENSE || true
      diff -u "$tmp/LICENSE" "$VENDOR/LICENSE" || true
      exit 1
    fi
    for f in "${FILES[@]}"; do
      for ext in py pyi; do
        grep -q 'SPDX-License-Identifier' "$PKG/_pb/${f}_pb2.${ext}" || {
          echo "DRIFT: $PKG/_pb/${f}_pb2.${ext} carries no upstream attribution" >&2
          echo "       run: $0 attribute" >&2
          exit 1
        }
      done
      grep -q "zmk_studio_client/_pb/${f}.proto" "$PKG/_pb/${f}_pb2.py" || {
        echo "DRIFT: $PKG/_pb/${f}_pb2.py registers an unqualified descriptor name" >&2
        echo "       run: $0 generate" >&2
        exit 1
      }
    done
    ;;
  attribute)
    apply_attribution
    echo "attribution present on all generated bindings"
    ;;
  generate)
    compile_bindings
    echo "regenerated $PKG/_pb/*_pb2.py from vendored protos"
    ;;
  upstream)
    echo "pinned at $PINNED"
    ahead=$(gh api "repos/$REPO/compare/$PINNED...main" --jq '.ahead_by')
    if [ "$ahead" = "0" ]; then
      echo "up to date: upstream main has nothing newer"
    else
      echo "$ahead commit(s) on main since the pin:"
      gh api "repos/$REPO/compare/$PINNED...main" \
        --jq '.commits[] | "  \(.sha[0:8])  \(.commit.committer.date)  \(.commit.message | split("\n")[0])"'
      echo
      echo "diff of proto/zmk between the pin and main:"
      gh api "repos/$REPO/compare/$PINNED...main" \
        --jq '.files[] | select(.filename | startswith("proto/zmk/")) | "  \(.status)  \(.filename)  +\(.additions)/-\(.deletions)"'
    fi
    ;;
  update)
    sha="${2:?usage: reconcile.sh update <commit-sha>}"
    fetch_to "$sha" "$PROTO"
    fetch_license_to "$sha" "$VENDOR/LICENSE"
    echo "$sha" > "$VENDOR/revision.txt"
    # Consumers that record what they read need to say which definitions decoded it,
    # so this constant moves with the pin. It lives in the package because revision.txt
    # is not shipped.
    echo "STUDIO_MESSAGES_REVISION = \"$sha\"" > "$PKG/_revision.py"
    compile_bindings
    echo "updated to $sha and regenerated bindings - review the diff before committing"
    ;;
  *)
    echo "usage: reconcile.sh [check|upstream|generate|attribute|update <sha>]" >&2; exit 2 ;;
esac
