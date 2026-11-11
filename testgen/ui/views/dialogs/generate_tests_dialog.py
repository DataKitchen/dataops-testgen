from functools import cache

from sqlalchemy import text

from testgen.commands.test_generation import resolve_generation_profile_run
from testgen.common.audit.test_definitions import record_status_changed
from testgen.common.database.database_service import get_flavor_service
from testgen.common.enums import MANAGED_TEST_TYPES, SuiteType
from testgen.common.generation_set_service import GENERATION_SET_DESCRIPTIONS, order_generation_sets
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.sampling_requirements import sampled_profile_gaps
from testgen.ui.services.database_service import fetch_all_from_db, fetch_one_from_db
from testgen.utils.plugins import discover


@cache
def _generation_set_descriptions() -> dict[str, str]:
    """Each generation set's description, from core and from the installed plugins."""
    descriptions = dict(GENERATION_SET_DESCRIPTIONS)
    for plugin in discover():
        descriptions.update(plugin.load().get_generation_set_descriptions())
    return descriptions


def generation_set_options(names: list[str]) -> list[dict[str, str | None]]:
    """The generation set picker's options: each of ``names``, in ``order_generation_sets`` order, with its
    description, from core or from the plugin that declares it, or None when neither does."""
    descriptions = _generation_set_descriptions()
    return [
        {"value": name, "label": name, "help": descriptions.get(name)} for name in order_generation_sets(names)
    ]


@with_database_session
def get_test_suite_refresh_warning(test_suite_id: str) -> dict | None:
    """Counts backing the Generate Tests refresh warning, or None when there is nothing to warn about.

    ``unlocked_counts_by_type`` lets the dialog compute, per selection, how many tests a
    de-selected generation set would delete. Managed test types are left out, since every
    generation reconciles them whatever is locked.
    """
    managed = ", ".join(f"'{test_type}'" for test_type in sorted(MANAGED_TEST_TYPES))
    unmanaged = f"td.test_type NOT IN ({managed})"
    totals = fetch_one_from_db(
        f"""
        SELECT
            COUNT(*) AS test_ct,
            SUM(CASE WHEN COALESCE(td.lock_refresh, 'N') = 'N' THEN 1 ELSE 0 END) AS unlocked_test_ct,
            SUM(CASE WHEN COALESCE(td.lock_refresh, 'N') = 'N' AND td.last_manual_update IS NOT NULL THEN 1 ELSE 0 END) AS unlocked_edits_ct
        FROM test_definitions td
        WHERE td.test_suite_id = :test_suite_id
            AND td.version_id = {SuiteVersion.resolved_for_sql("td.test_suite_id")}
            AND td.last_auto_gen_date IS NOT NULL
            AND {unmanaged};
        """,
        {"test_suite_id": test_suite_id},
    )

    if not totals or not totals.test_ct:
        return None

    per_type = fetch_all_from_db(
        f"""
        SELECT td.test_type, COUNT(*) AS test_ct
        FROM test_definitions td
        WHERE td.test_suite_id = :test_suite_id
            AND td.version_id = {SuiteVersion.resolved_for_sql("td.test_suite_id")}
            AND td.last_auto_gen_date IS NOT NULL
            AND {unmanaged}
            AND COALESCE(td.lock_refresh, 'N') = 'N'
        GROUP BY td.test_type;
        """,
        {"test_suite_id": test_suite_id},
    )

    return {
        "test_ct": totals.test_ct,
        "unlocked_test_ct": totals.unlocked_test_ct or 0,
        "unlocked_edits_ct": totals.unlocked_edits_ct or 0,
        "unlocked_counts_by_type": {row.test_type: row.test_ct for row in per_type},
    }


@with_database_session
def get_sampled_unavailable_test_types(table_group_id: str) -> dict[str, str]:
    """Test type code to short name of each test type not generated on a sampled column, when the profiling
    run that test generation uses for the table group sampled any column. Empty otherwise.
    """
    profile_run_id = resolve_generation_profile_run(TableGroup.get(table_group_id))
    if profile_run_id is None or not ProfileResult.run_sampled(profile_run_id):
        return {}
    return sampled_profile_gaps().test_types


@with_database_session
def get_value_hash_warning(table_group_id: str) -> str | None:
    """Warning that generation will skip the value hash test types, or None when it will not.

    Returns None when the connection type does not compute value hashes, when there is no readable
    profiling run (generation then creates no tests at all), or when that run computed value hashes.
    """
    table_group = TableGroup.get(table_group_id)
    connection = Connection.get(table_group.connection_id)
    if not get_flavor_service(connection.sql_flavor).supports_value_hash:
        return None

    profile_run_id = resolve_generation_profile_run(table_group)
    if profile_run_id is None or ProfileResult.has_value_hashes(profile_run_id):
        return None

    if table_group.profile_table_comparison:
        warning = (
            "The profiling run that test generation uses for this table group did not compute value hashes, "
            "so the hash tests and Match Epoch Sum will not be generated. "
            "Run profiling again to generate them."
        )
    else:
        warning = (
            "This table group is not profiled for table comparison, "
            "so the hash tests and Match Epoch Sum will not be generated. "
            "To generate them, edit the table group, select Profile for table comparison, and run profiling again."
        )
    if delay_days := table_group.profiling_delay_days:
        day_noun = "day" if delay_days == 1 else "days"
        warning += (
            f" Test generation uses the new profiling run once it is {delay_days} {day_noun} old, "
            "the table group's minimum profiling age."
        )
    return warning


@with_database_session
def lock_edited_tests(test_suite_id: str) -> None:
    """Lock the suite's edited, unlocked auto-generated tests. A contract's lock lands on its draft,
    which is opened when there is none, so a frozen version is never written."""
    if TestSuite.get(test_suite_id).suite_type == SuiteType.CONTRACT:
        TestDefinition.resolve_write_target(test_suite_id)
    locked = get_current_session().execute(
        text(f"""
        UPDATE test_definitions
            SET lock_refresh = 'Y'
        WHERE test_suite_id = :test_suite_id
            AND version_id = {SuiteVersion.resolved_for_sql("test_definitions.test_suite_id")}
            AND last_manual_update IS NOT NULL
            AND lock_refresh = 'N'
        RETURNING id;
        """),
        {"test_suite_id": test_suite_id},
    ).scalars().all()
    record_status_changed("lock_refresh", True, locked)
