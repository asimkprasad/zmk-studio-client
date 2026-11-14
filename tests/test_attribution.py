"""The vendored definitions' licence has to travel with the code that carries them.

MIT asks copies to include the permission notice, not merely to name the licence.
third_party/ is covered by its own NOTICE and LICENSE, but the generated bindings in
zmk_studio_client/_pb/ embed upstream's package, message and field names verbatim - and unlike
third_party/, they are packaged into the wheel. Without a header in each file, the
distributed artifact would carry ZMK's definitions under our licence alone.

protoc overwrites these files, so the headers are re-applied by
src/scripts/reconcile_zmk_model/reconcile.sh rather than maintained by hand. These tests are what
notices if that stops happening.
"""
from __future__ import annotations

import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
VENDOR = HERE / "src" / "third_party" / "zmk_studio_messages"

#: The bindings generated from the vendored protos, all of them under _pb/.
#:
#: Our own schema is generated to proto/ instead, and the split is not filing: a
#: reader has to be able to tell at a glance which generated code carries somebody
#: else's definitions and which carries ours, because only the first needs the
#: notice below travelling with it.
UPSTREAM_DERIVED = ["behaviors", "core", "keymap", "meta", "studio"]

#: Ours. Generated the same way, attributed the opposite way.
OURS = "keyboard"


def test_the_permission_notice_is_vendored_not_just_referenced() -> None:
    licence = (VENDOR / "LICENSE").read_text()
    assert "Copyright (c) 2024 The ZMK Contributors" in licence
    # The clause MIT actually requires a copy to carry.
    assert "Permission is hereby granted, free of charge" in licence
    assert "WITHOUT WARRANTY OF ANY KIND" in licence


def test_the_notice_points_at_the_licence_beside_it() -> None:
    assert "LICENSE" in (VENDOR / "NOTICE").read_text()


@pytest.mark.parametrize("ext", ["py", "pyi"])
@pytest.mark.parametrize("stem", UPSTREAM_DERIVED)
def test_each_generated_binding_names_its_upstream(stem: str, ext: str) -> None:
    header = (HERE / "src" / "zmk_studio_client" / "_pb" / f"{stem}_pb2.{ext}").read_text()[:600]
    assert "The ZMK Contributors" in header, f"{stem}_pb2.{ext} lost its attribution"
    assert "SPDX-License-Identifier: MIT" in header
    # A repo-relative path would resolve to nothing inside an installed wheel, which
    # is the one place this header has to stand on its own.
    assert "https://github.com/zmkfirmware/zmk-studio-messages" in header
    assert "third_party" not in header


@pytest.mark.parametrize("stem", UPSTREAM_DERIVED)
def test_the_coding_declaration_still_comes_first(stem: str) -> None:
    """PEP 263 requires the magic comment on line 1 or 2, so the header goes after it."""
    first = (HERE / "src" / "zmk_studio_client" / "_pb" / f"{stem}_pb2.py").read_text().splitlines()[0]
    assert "coding" in first


def test_every_vendored_proto_is_covered_by_the_notice() -> None:
    """A proto added to the vendored set without attribution would slip past above."""
    vendored = {p.stem for p in (VENDOR / "proto").glob("*.proto")}
    assert vendored == set(UPSTREAM_DERIVED), (
        f"vendored protos {sorted(vendored)} do not match the attributed bindings "
        f"{sorted(UPSTREAM_DERIVED)}"
    )


# --------------------------------------------------------------------------- #
# our own schema, which must not acquire upstream's notice by cut and paste
# --------------------------------------------------------------------------- #

def test_our_own_schema_is_not_attributed_to_zmk() -> None:
    """keyboard.proto is this library's API, written here.

    It borrows upstream's field semantics - it describes the same keyboard - but
    none of its text, and claiming otherwise in a licence header would be a false
    statement about provenance in the one place people look for provenance.
    """
    source = (HERE / "src" / "zmk_studio_client" / "proto" / f"{OURS}.proto").read_text()
    assert "Asim Krishna Prasad" in source
    assert "SPDX-License-Identifier: MIT" in source
    assert "The ZMK Contributors" not in source


def test_the_generated_bindings_for_our_schema_live_apart_from_upstreams() -> None:
    """_pb/ is theirs, proto/ is ours. Nothing generated may sit in both."""
    pb = {path.stem.removesuffix("_pb2")
          for path in (HERE / "src" / "zmk_studio_client" / "_pb").glob("*_pb2.py")}
    ours = {path.stem.removesuffix("_pb2")
            for path in (HERE / "src" / "zmk_studio_client" / "proto").glob("*_pb2.py")}
    assert pb == set(UPSTREAM_DERIVED), f"unattributed bindings under _pb/: {sorted(pb)}"
    assert ours == {OURS}, f"unexpected generated code under proto/: {sorted(ours)}"


def test_the_schema_ships_with_the_wheel() -> None:
    """A consumer in another language generates from the .proto, so it has to be in
    the distribution - otherwise the schema is only readable by cloning a private
    repository, which is no schema at all."""
    config = (HERE / "pyproject.toml").read_text()
    assert 'zmk_studio_client = ["proto/*.proto"]' in config


@pytest.mark.parametrize("stem", UPSTREAM_DERIVED)
def test_vendored_bindings_namespace_their_descriptor_paths(stem: str) -> None:
    """Bare names like `keymap.proto` in the global descriptor pool collide at import
    time with any other library in the consumer's process that defines one."""
    import importlib

    mod = importlib.import_module(f"zmk_studio_client._pb.{stem}_pb2")
    assert mod.DESCRIPTOR.name == f"zmk_studio_client/_pb/{stem}.proto"


def test_importing_pb_does_not_leak_top_level_modules_or_mutate_sys_path() -> None:
    """`_pb` is an internal package; it must not pollute top-level `sys.modules` or
    leave its own directory on `sys.path`."""
    import sys

    for stem in UPSTREAM_DERIVED:
        assert f"{stem}_pb2" not in sys.modules
    assert not any(entry.endswith("_pb") for entry in sys.path)
