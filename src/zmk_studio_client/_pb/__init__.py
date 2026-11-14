"""Protobuf bindings generated from the vendored ZMK Studio message definitions.

Source of truth is ../../third_party/zmk_studio_messages/proto, pinned to the revision
in that directory's revision.txt. These files are generated - do not edit them; run
src/scripts/reconcile_zmk_model/reconcile.sh instead.

reconcile.sh stages the vendored protos under zmk_studio_client/_pb/ before invoking
protoc so their descriptors register under qualified paths in the default descriptor
pool and import siblings via `from zmk_studio_client._pb import ...` without touching
`sys.path`.
"""
