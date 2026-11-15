"""Every parameter substituted into a query that may hold a custom query is reserved.

A custom query declares a variable as ``{NAME:default}``. If TestGen also substitutes ``NAME``,
the declaration shadows the value TestGen fills in, so declaring one is refused — which only
works while the reserved set knows every such name. The set cannot be derived at run time: the
dictionaries are built per test, partly by flavor services. It is declared instead, and this
reads the builders back to keep it honest.

Only the builders whose query can contain a user's custom query are in scope. A DB-upgrade
template or a score rollup shares the ``{NAME}`` syntax but never carries one.
"""

import ast
from pathlib import Path

import pytest

from testgen.common.query_variables import RESERVED_PARAMETER_NAMES

pytestmark = pytest.mark.unit

SOURCE_ROOT = Path(__file__).parents[3] / "testgen"

# Module, relative to the package root, to the builder functions it defines. A new one belongs
# here; the alternative is a parameter nobody reserved.
PARAMETER_BUILDERS = {
    "commands/queries/execute_tests_query.py": ("_get_params", "_freshness_exclusion_params"),
    "common/source_data_service.py": ("_build_query_standard", "_build_query_custom"),
    "common/database/flavor/flavor_service.py": ("value_hash_params",),
    "common/custom_test_validation.py": ("validate_custom_query", "render_metric_validation_query"),
}


def _substituted_names(path: str, function: str) -> set[str]:
    """The upper-case string keys the function uses as parameter names.

    Taken from the syntax tree rather than by matching text, so a comparison against an
    upper-case literal is not mistaken for a dictionary key.
    """
    tree = ast.parse((SOURCE_ROOT / path).read_text())
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function
        ),
        None,
    )
    assert target is not None, f"{function} is gone from {path}"

    names = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Dict):
            keys = node.keys
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            keys = [node.slice]
        else:
            continue
        names.update(
            key.value
            for key in keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.isupper()
        )
    return names


@pytest.mark.parametrize(
    ("path", "function"),
    [(path, function) for path, functions in PARAMETER_BUILDERS.items() for function in functions],
    ids=lambda value: value.rsplit("/", 1)[-1],
)
def test_every_substituted_parameter_is_reserved(path, function):
    substituted = _substituted_names(path, function)
    assert substituted, f"{function} builds no parameters; the test is reading the wrong thing"

    unreserved = sorted(substituted - RESERVED_PARAMETER_NAMES)
    assert not unreserved, (
        f"{function} substitutes {unreserved}, which a custom query could declare as a variable "
        "and shadow. Add them to RESERVED_PARAMETER_NAMES."
    )
