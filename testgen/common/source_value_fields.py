"""The fields of a test definition and of a contract's metadata document that can carry values from the source data."""

import hashlib
import hmac
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from testgen.common.contract_document import PROFILED_VALUES
from testgen.common.odcs.quality_rules import CONVERSION_PROPERTIES

# Threshold- and tolerance-shaped columns on TestDefinition that hold values
# derived from source-data profiling. The storage layer does not distinguish
# user-set from calibrated for these fields (a `threshold_value` can be a
# regex the user typed OR a numeric threshold calibrated by profiling), so
# under source-data protection they are dropped uniformly.
CALIBRATION_SHAPED_PARAM_COLUMNS: frozenset[str] = frozenset({
    "baseline_ct",
    "baseline_unique_ct",
    "baseline_value",
    "baseline_value_ct",
    "threshold_value",
    "baseline_sum",
    "baseline_avg",
    "baseline_sd",
    "lower_tolerance",
    "upper_tolerance",
})

# Document fields that can carry values from the source data: a column's value bounds, profiled
# value bounds, examples and allowed values, and a quality rule's thresholds, arguments,
# implementation and recorded baselines. A value a person typed cannot be told apart from one taken from the data, so
# under source-data protection each is hidden uniformly. A rule's query is shown, as a test's
# custom query is.
SOURCE_VALUE_TYPE_OPTIONS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"})
SOURCE_VALUE_RULE_FIELDS = frozenset({
    "mustBe",
    "mustNotBe",
    "mustBeGreaterThan",
    "mustBeGreaterOrEqualTo",
    "mustBeLessThan",
    "mustBeLessOrEqualTo",
    "mustBeBetween",
    "mustNotBeBetween",
    "arguments",
    "implementation",
})
SOURCE_VALUE_PROPERTY_FIELDS = frozenset({"examples", "enum"})


@dataclass(frozen=True)
class HiddenSlot:
    container: dict
    key: str
    path: str


def hidden_slots(node: Any, path: str = "$", in_quality: bool = False) -> Iterator[HiddenSlot]:
    """Each field of a metadata document node that can carry source-data values: ``examples``,
    ``enum``, the value bounds of ``logicalTypeOptions`` and ``profiledValues``, and quality-rule
    thresholds, arguments, implementations and ``testgen`` baseline properties."""
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from hidden_slots(item, f"{path}[{index}]", in_quality)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        child = f"{path}.{key}"
        if key in SOURCE_VALUE_PROPERTY_FIELDS or (in_quality and key in SOURCE_VALUE_RULE_FIELDS):
            yield HiddenSlot(node, key, child)
            continue
        if key == "logicalTypeOptions" and isinstance(value, dict):
            yield from _bound_slots(value, child)
        elif key == "customProperties" and isinstance(value, list):
            for index, entry in enumerate(value):
                if (
                    isinstance(entry, dict) and entry.get("property") == PROFILED_VALUES
                    and isinstance(entry.get("value"), dict)
                ):
                    yield from _bound_slots(entry["value"], f"{child}[{index}].value")
                elif (
                    in_quality and isinstance(entry, dict) and entry.get("vendor") == "testgen"
                    and entry.get("property") in CONVERSION_PROPERTIES and "value" in entry
                ):
                    yield HiddenSlot(entry, "value", f"{child}[{index}].value")
        yield from hidden_slots(value, child, in_quality=key == "quality")


def _bound_slots(options: dict, path: str) -> Iterator[HiddenSlot]:
    for option in options:
        if option in SOURCE_VALUE_TYPE_OPTIONS:
            yield HiddenSlot(options, option, f"{path}.{option}")


def value_digest(key: bytes, salt: str, value: Any) -> str:
    """A keyed digest of ``value`` with ``salt``: equal for equal values under one key and salt."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hmac.new(key, salt.encode() + b"\0" + canonical, hashlib.sha256).hexdigest()[:16]
