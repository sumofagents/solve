import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_core_loop_does_not_import_language_connectors():
    tree = ast.parse((ROOT / "src" / "solve" / "loop.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("solve.connectors"):
            offenders.append(node.module)
        if isinstance(node, ast.Import):
            offenders.extend(alias.name for alias in node.names if alias.name.startswith("solve.connectors"))
    assert offenders == []
