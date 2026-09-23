from unittest.mock import patch

import pytest

import testgen.common.database.profiling_capabilities as pc
from testgen.common.database.database_service import get_flavor_service
from testgen.common.database.profiling_capabilities import ProfilingCapabilities, resolve_profiling_capabilities

pytestmark = pytest.mark.unit


def test_a_declared_flavor_with_a_passing_probe_computes_approximately():
    service = get_flavor_service("mssql")
    with patch.object(pc, "probe_target_capability", return_value=True) as probe:
        capabilities = resolve_profiling_capabilities(service)
    assert capabilities == ProfilingCapabilities(approx_percentile=True)
    probe.assert_called_once_with(service.approx_percentile_probe, "approximate percentile", service.test_query)


def test_a_declared_flavor_with_a_failing_probe_computes_exactly():
    # SQL Server's function is version-gated: a failing probe means this instance lacks it.
    with patch.object(pc, "probe_target_capability", return_value=False):
        capabilities = resolve_profiling_capabilities(get_flavor_service("mssql"))
    assert capabilities == ProfilingCapabilities(approx_percentile=False)


def test_an_exact_only_flavor_never_probes():
    with patch.object(pc, "probe_target_capability") as probe:
        capabilities = resolve_profiling_capabilities(get_flavor_service("postgresql"))
    assert capabilities == ProfilingCapabilities(approx_percentile=False)
    probe.assert_not_called()


def test_a_declaration_without_a_probe_is_trusted():
    with patch.object(pc, "probe_target_capability") as probe:
        capabilities = resolve_profiling_capabilities(get_flavor_service("bigquery"))
    assert capabilities == ProfilingCapabilities(approx_percentile=True)
    probe.assert_not_called()


def test_an_unreachable_target_raises_rather_than_reading_as_an_absent_function():
    """Silently reading a connection failure as an absent function would compute a whole run
    exactly, and a resumed run that pinned the earlier answer would start over."""
    outage = RuntimeError("could not connect to server")
    with patch("testgen.common.database.database_service.fetch_dict_from_db", side_effect=outage):
        with pytest.raises(RuntimeError, match="could not connect"):
            resolve_profiling_capabilities(get_flavor_service("mssql"))


def test_an_absent_function_on_a_reachable_target_computes_exactly():
    def fetch(query, _params, use_target_db=False):
        # Both the probe and the connectivity retest ask the target, never the app database.
        assert use_target_db is True
        if "APPROX" in query.upper():
            raise RuntimeError("'APPROX_PERCENTILE_CONT' is not a recognized built-in function name.")
        return [{"1": 1}]

    with patch("testgen.common.database.database_service.fetch_dict_from_db", side_effect=fetch):
        capabilities = resolve_profiling_capabilities(get_flavor_service("mssql"))
    assert capabilities == ProfilingCapabilities(approx_percentile=False)
