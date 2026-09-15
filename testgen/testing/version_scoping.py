"""Where the version-resolution rule is rendered into hand-written SQL.

Static discovery, so a query added later cannot quietly escape the tests that execute these.
"""

import ast
from pathlib import Path

RENDERER = "resolved_for_sql"


def interpolating_callables(source_root: Path) -> set[str]:
    """``<module path>::<function>`` for every function under *source_root* rendering the rule.

    The root is passed rather than derived: in the enterprise repo the submodule directory
    shadows the package, leaving ``testgen.__file__`` unset.
    """
    found = set()
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name == RENDERER:
                continue
            if RENDERER in ast.unparse(node):
                found.add(f"{path.relative_to(source_root)}::{node.name}")
    return found
