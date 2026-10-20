"""JSON Merge Patch (RFC 7386)."""

import copy
from typing import Any


def apply_merge_patch(target: Any, patch: Any) -> Any:
    """``target`` with ``patch`` applied, as a new value; ``target`` is not mutated.

    An object in ``patch`` merges into the object at the same place, a ``None`` member removes
    that member, and any other value, an array included, replaces what is there.
    """
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = apply_merge_patch(result.get(key), value)
    return result
