"""Resolve what a profiling run computes on its target: which measures approximately, and which
general types' values it hashes.

Each FlavorService declares its approximate functions and whether it hashes values; this module
confirms a declaration against the target with the flavor's probe query. A probe that fails on a
reachable target means the capability is absent: the measure is computed exactly, or the values go
unhashed. One that fails because the target could not be reached raises, so a run never loses a
capability for want of a connection.
"""

from typing import NamedTuple

from testgen.common.database.database_service import probe_target_capability
from testgen.common.database.flavor.flavor_service import FlavorService


class ProfilingCapabilities(NamedTuple):
    approx_percentile: bool = False
    hashed_types: frozenset[str] = frozenset()


def resolve_profiling_capabilities(flavor_service: FlavorService, *, table_comparison: bool) -> ProfilingCapabilities:
    """Resolve a run's capabilities: a declared capability holds only if its probe, when the
    flavor provides one, also succeeds against the target. A declaration without a probe is
    trusted as declared.

    Args:
        flavor_service: The target's flavor service.
        table_comparison: Whether the table group is profiled for table comparison; values are hashed only then.

    Returns:
        The capabilities. ``hashed_types`` holds the general types whose values the run hashes: none
        unless the run profiles for table comparison on a flavor that hashes values; otherwise
        numbers and dates, and text where the flavor's text hash probe, if it has one, succeeds.

    Raises whatever the probe raised when the target is unreachable.
    """
    hashed_types: frozenset[str] = frozenset()
    if table_comparison and flavor_service.supports_value_hash:
        hashed_types = frozenset({"N", "D"})
        if flavor_service.text_hash_probe is None or probe_target_capability(
            flavor_service.text_hash_probe, "UTF-8 text hash", flavor_service.test_query
        ):
            hashed_types |= {"A"}
    return ProfilingCapabilities(
        approx_percentile=flavor_service.supports_approx_percentile
        and (
            flavor_service.approx_percentile_probe is None
            or probe_target_capability(
                flavor_service.approx_percentile_probe, "approximate percentile", flavor_service.test_query
            )
        ),
        hashed_types=hashed_types,
    )
