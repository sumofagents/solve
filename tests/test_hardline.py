import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CORE_MODULES = [
    ROOT / "src" / "solve" / "loop.py",
    ROOT / "src" / "solve" / "lean" / "atoms.py",
    ROOT / "src" / "solve" / "lean" / "codegen.py",
    ROOT / "src" / "solve" / "lean" / "triviality.py",
    ROOT / "src" / "solve" / "lean" / "novelty.py",
    ROOT / "src" / "solve" / "lean" / "term_inspect.py",
    ROOT / "src" / "solve" / "lean" / "value.py",
    ROOT / "src" / "solve" / "promote.py",
    ROOT / "src" / "solve" / "lean" / "promote_codegen.py",
    ROOT / "src" / "solve" / "lean" / "usage.py",
    ROOT / "src" / "solve" / "lean" / "downstream.py",
    ROOT / "src" / "solve" / "verify" / "candidates.py",
    ROOT / "src" / "solve" / "grammar" / "and_intro.py",
]


def connector_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("solve.connectors"):
            offenders.append(node.module)
        if isinstance(node, ast.Import):
            offenders.extend(alias.name for alias in node.names if alias.name.startswith("solve.connectors"))
    return offenders


def test_core_modules_do_not_import_language_connectors():
    for path in CORE_MODULES:
        assert connector_imports(path) == [], str(path)
