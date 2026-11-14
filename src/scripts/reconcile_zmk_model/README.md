# Reconciling with upstream

Our copy is pinned to one upstream commit, recorded in `revision.txt`. Pinning makes a
refresh a deliberate, reviewable act rather than whatever upstream happened to look like
on the day someone ran a script.

## Check whether we have drifted

    ./reconcile.sh check

Fetches the pinned revision and compares it against `proto/`. Silence means our copy is
byte-identical to what we claim. Any difference is printed and exits non-zero, which
means somebody hand-edited our copy - the one thing NOTICE forbids.

## See what upstream has changed since we pinned

    ./reconcile.sh upstream

Lists commits on upstream `main` after our pinned revision. Read this before moving the
pin: these definitions describe a wire contract, so a change here can alter how every
keyboard's keymap decodes.

## Move to a new revision

    ./reconcile.sh update <commit-sha>

Fetches that revision, replaces `proto/`, rewrites `revision.txt`, and regenerates the
Python bindings in `zmk_studio_client/_pb/`. Review the diff as you would any contract change, then
commit protos, revision and regenerated bindings together so they never disagree.

Regeneration needs `grpcio-tools`, a development dependency only - nothing imports it at
runtime.

## Why vendor at all

ZMK publishes these as a Zephyr module for firmware builds, not as a Python package.
Vendoring keeps the library self-contained and lets it decode a keyboard whose firmware was
built against a known revision, rather than assuming the keyboard speaks whatever upstream
ships today.
