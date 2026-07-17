"""Process-boundary contract for the veneer tree (FC-1).

A veneer reaches the engine only over the wire: nothing under
`hearth/veneers/` may import the engine's internals. Written over the whole
`hearth.veneers` package -- not `chat` specifically -- so any future surface
(the audio plumages) is covered the day it is added.
"""
from __future__ import annotations

import ast
import pathlib

FORBIDDEN = ("hearth.brain", "hearth.loop", "hearth.memory", "hearth.gateway")


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            # Only absolute imports name an engine module; a relative import
            # (level > 0) stays inside the veneers tree.
            if node.module and node.level == 0:
                yield node.module


def test_chat_reaches_engine_only_over_the_wire():
    import hearth.veneers

    root = pathlib.Path(hearth.veneers.__file__).parent
    offenders: list[tuple[str, str]] = []
    hearth_imports: set[str] = set()
    for py in sorted(root.rglob("*.py")):
        tree = ast.parse(py.read_text())
        for module in _imported_modules(tree):
            if any(module == f or module.startswith(f + ".") for f in FORBIDDEN):
                offenders.append((py.name, module))
            if module == "hearth" or module.startswith("hearth."):
                hearth_imports.add(module)

    assert offenders == [], f"veneers tree imports engine internals: {offenders}"

    # AC-9: the only `hearth` imports allowed are the shared config facility and
    # the veneers tree itself -- everything else must be stdlib or websockets.
    disallowed = {
        m
        for m in hearth_imports
        if m != "hearth.config" and not m.startswith("hearth.veneers")
    }
    assert disallowed == set(), f"unexpected hearth imports in veneers tree: {disallowed}"
