"""Resolve what a profiling run may compute approximately on its target.

Each FlavorService declares its approximate functions; this module confirms a declaration against
the target with the flavor's probe query. A probe that fails on a reachable target means the
function is absent and the measure is computed exactly; one that fails because the target could
not be reached raises, so a run is never computed exactly for want of a connection.
"""

from typing import NamedTuple

from testgen.common.database.database_service import probe_target_capability
from testgen.common.database.flavor.flavor_service import FlavorService


class ProfilingCapabilities(NamedTuple):
    approx_percentile: bool = False


def resolve_profiling_capabilities(flavor_service: FlavorService) -> ProfilingCapabilities:
    """Resolve a run's capabilities: a declared capability holds only if its probe, when the
    flavor provides one, also succeeds against the target. A declaration without a probe is
    trusted as declared.

    Raises whatever the probe raised when the target is unreachable.
    """
    return ProfilingCapabilities(
        approx_percentile=flavor_service.supports_approx_percentile
        and (
            flavor_service.approx_percentile_probe is None
            or probe_target_capability(
                flavor_service.approx_percentile_probe, "approximate percentile", flavor_service.test_query
            )
        ),
    )
