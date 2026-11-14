"""Which modules can reach which, enforced by reading the import graph.

**What this file can and cannot promise, in a library.**

In the tool this code came from, these tests carried the headline guarantee: the
capture command could not modify the keyboard it was capturing, because `cli.py`'s
import closure provably never reached a write. That claim does not survive the move
and should not pretend to. A library ships both doors - `WritableKeyboard` has to
exist for anyone to write anything - and "the capture command cannot write" is a
statement about a command. Commands live in the application.

What a library *can* prove is narrower and still worth having:

    reads      must not reach `writes`       - or the proof types prove nothing
    __init__   must not reach either         - or `import zmk_studio_client` is a write
    writes     must not reach a transport    - it builds requests; it does not own a port

The first two are what make `ReadRequest` evidence rather than decoration. An
application that wants the stronger guarantee writes it against its own commands,
and the one route it has to close is importing `zmk_studio_client.writable`, which
is a single greppable line by construction.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = HERE / "src" / "zmk_studio_client"

#: The floors that know how to reach hardware.
TRANSPORTS = {"connection", "wire", "rpc", "_connect"}

#: The two modules that can change a keyboard.
#:
#:     writes      the requests that mutate
#:     writable    the object that sends them
#:
#: Both are named, not just the first. `writable` imports `writes` today, so reaching
#: it implies reaching both - but naming only the request module would let a future
#: WritableKeyboard that built its requests inline slip past a test that still
#: reported a clean closure.
WRITE_SURFACE = {"writes", "writable"}


def _imports_at(path: pathlib.Path) -> set[str]:
    """Sibling modules imported by one file, by any import syntax."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level:
            # Take the module path AND the imported names, because a submodule can
            # arrive either way: `from .writes import x` names it in the path,
            # `from . import writes` names it in the list. Taking only one of the two
            # is how a write slips past unseen. Names that are not modules resolve to
            # nothing and cost nothing.
            if node.module:
                found.update(node.module.split("."))
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("zmk_studio_client."):
                    found.add(alias.name.split(".")[1])
    return found


def _module_path(module: str) -> pathlib.Path | None:
    """Where `module` lives, or None.

    Resolving by search rather than by fixed location keeps the guarantee from
    quietly passing because a file moved - a walker that cannot find `writes`
    reports that nothing reaches it, which is the vacuous success this whole file
    exists to avoid. `test_the_write_module_is_seen_at_all` is the backstop.
    """
    for candidate in (PACKAGE / f"{module}.py", PACKAGE / module / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def _imports(module: str) -> set[str]:
    path = _module_path(module)
    return _imports_at(path) if path else set()


def closure(start: str) -> set[str]:
    """Every module in the package reachable from `start` by imports."""
    seen: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        for name in _imports(current) - seen:
            seen.add(name)
            pending.append(name)
    return seen


# --------------------------------------------------------------------------- #
# the read path cannot reach the write path
# --------------------------------------------------------------------------- #

def test_the_read_allowlist_cannot_reach_the_write_allowlist() -> None:
    """`reads` is what makes a ReadRequest evidence of anything.

    If it could reach `writes`, the two proof types would live on one path and
    holding one would stop saying which allowlist it passed.
    """
    reached = closure("reads")
    assert not (reached & WRITE_SURFACE), (
        f"reads reaches {sorted(reached & WRITE_SURFACE)}. Reached: {sorted(reached)}")


def test_importing_the_package_does_not_import_a_write() -> None:
    """`import zmk_studio_client` must not put a write on the surface.

    This is the one route a closure walk cannot see: the walker resolves a
    re-exported name to no file, so if `__init__` ever did
    `from .writes import save_changes`, a caller could reach a write primitive
    through a name that looks like a function and every closure above would still
    come back clean.

    It is also the honest design. A caller who wants to change a keyboard should
    have to name the module that does it.
    """
    imported = _imports("__init__")
    assert not (imported & WRITE_SURFACE), (
        f"zmk_studio_client/__init__.py imports {sorted(imported & WRITE_SURFACE)}; "
        f"that puts a write onto the package surface. Imported: {sorted(imported)}")


def test_the_read_only_keyboard_cannot_reach_the_write_path() -> None:
    """Everything `connect()` can reach, checked rather than assumed."""
    reached = closure("__init__")
    assert not (reached & WRITE_SURFACE), (
        f"the read-only surface reaches {sorted(reached & WRITE_SURFACE)}")


# --------------------------------------------------------------------------- #
# the request modules do not own a port
# --------------------------------------------------------------------------- #

def test_the_write_requests_cannot_open_a_connection_by_themselves() -> None:
    """`writes` builds requests; it does not own a port.

    Keeping transports out of it means `writable` has to reach for a connection
    explicitly, in code someone reviews, rather than inheriting one.
    """
    assert not (closure("writes") & TRANSPORTS), sorted(closure("writes"))


# --------------------------------------------------------------------------- #
# the walker itself - without these, every test above could pass vacuously
# --------------------------------------------------------------------------- #

def test_the_write_module_is_seen_at_all() -> None:
    """If `writes` parsed to nothing, 'nothing reaches it' would be meaningless."""
    assert "reads" in _imports("writes"), (
        "writes imports reads for the shared envelope builder; the walker not "
        "seeing that means it is not reading this module")


def test_the_writable_door_does_reach_both() -> None:
    """The positive half. Without it, every assertion above proves nothing.

    `writable` is the one module that must reach the write requests and a transport,
    because it is the door. If this fails, the walker is not seeing real imports.
    """
    reached = closure("writable")
    assert "writes" in reached, sorted(reached)
    assert reached & TRANSPORTS, sorted(reached)


def test_the_check_would_notice_a_transport_import() -> None:
    assert TRANSPORTS <= closure("__init__"), (
        "connect() must reach every transport floor; if it does not, the import "
        f"walker is not seeing real imports. Missing: "
        f"{sorted(TRANSPORTS - closure('__init__'))}")


@pytest.mark.parametrize("source,expected", [
    ("from . import writes", {"writes"}),
    ("from . import writable", {"writable"}),
    ("from .writes import save_changes", {"writes", "save_changes"}),
    ("from .writable import WritableKeyboard", {"writable", "WritableKeyboard"}),
    ("import zmk_studio_client.writes", {"writes"}),
    ("import json", set()),
    ("from __future__ import annotations", set()),
])
def test_the_walker_catches_every_import_syntax(tmp_path, source, expected) -> None:
    """The guarantee is only as good as the parser behind it.

    Each syntax a violation could be written in is checked here against a file
    written for the purpose.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(source + "\n")
    assert _imports_at(probe) == expected
