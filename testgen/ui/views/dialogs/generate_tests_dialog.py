from testgen.common.models import with_database_session
from testgen.ui.services.database_service import execute_db_query, fetch_all_from_db, fetch_one_from_db


@with_database_session
def get_test_suite_refresh_warning(test_suite_id: str) -> dict | None:
    """Counts backing the Generate Tests refresh warning, or None when there is nothing to warn about.

    ``unlocked_counts_by_type`` lets the dialog compute, per selection, how many tests a
    de-selected generation set would delete.
    """
    totals = fetch_one_from_db(
        """
        SELECT
            COUNT(*) AS test_ct,
            SUM(CASE WHEN COALESCE(td.lock_refresh, 'N') = 'N' THEN 1 ELSE 0 END) AS unlocked_test_ct,
            SUM(CASE WHEN COALESCE(td.lock_refresh, 'N') = 'N' AND td.last_manual_update IS NOT NULL THEN 1 ELSE 0 END) AS unlocked_edits_ct
        FROM test_definitions td
        WHERE td.test_suite_id = :test_suite_id
            AND td.last_auto_gen_date IS NOT NULL;
        """,
        {"test_suite_id": test_suite_id},
    )

    if not totals or not totals.test_ct:
        return None

    per_type = fetch_all_from_db(
        """
        SELECT td.test_type, COUNT(*) AS test_ct
        FROM test_definitions td
        WHERE td.test_suite_id = :test_suite_id
            AND td.last_auto_gen_date IS NOT NULL
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
def lock_edited_tests(test_suite_id: str) -> None:
    execute_db_query(
        """
        UPDATE test_definitions
            SET lock_refresh = 'Y'
        WHERE test_suite_id = :test_suite_id
            AND last_manual_update IS NOT NULL
            AND lock_refresh = 'N';
        """,
        {"test_suite_id": test_suite_id}
    )
