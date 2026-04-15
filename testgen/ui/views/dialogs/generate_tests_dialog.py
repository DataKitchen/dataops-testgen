import streamlit as st

from testgen.common.models import database_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.test_suite import TestSuiteMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.services.database_service import execute_db_query, fetch_all_from_db, fetch_one_from_db

RESULT_KEY = "generate_tests_dialog:result"
LOCK_RESULT_KEY = "generate_tests_dialog:lock_result"


def generate_tests_dialog_widget(
    test_suite: TestSuiteMinimal,
    dialog: dict,
    on_close: callable,
) -> None:
    test_suite_id = str(test_suite.id)
    test_suite_name = test_suite.test_suite

    generation_sets = get_generation_set_choices()
    default_set = "Standard" if "Standard" in generation_sets else (generation_sets[0] if generation_sets else "")

    refresh_warning = None
    test_ct, unlocked_test_ct, unlocked_edits_ct = get_test_suite_refresh_warning(test_suite_id)
    if test_ct:
        refresh_warning = {
            "test_ct": test_ct,
            "unlocked_test_ct": unlocked_test_ct or 0,
            "unlocked_edits_ct": unlocked_edits_ct or 0,
        }

    def on_lock_edited_tests(*_) -> None:
        lock_edited_tests(test_suite_id)
        st.session_state[LOCK_RESULT_KEY] = "Edited tests have been successfully locked."

    def on_generate_tests_confirmed(data: dict) -> None:
        selected_id = data.get("test_suite_id")
        selected_set = data.get("generation_set", "")
        try:
            with database_session():
                JobExecution.submit(
                    job_key="run-test-generation",
                    kwargs={"test_suite_id": str(test_suite_id), "generation_set": selected_set},
                    source="ui",
                    project_code=test_suite.project_code,
                )
            st.session_state[RESULT_KEY] = {"success": True, "message": f"Test generation started for test suite '{test_suite_name}'."}
            st.cache_data.clear()
            on_close()
        except Exception as e:
            st.session_state[RESULT_KEY] = {"success": False, "message": f"Test generation encountered errors: {e!s}."}

    def on_close_clicked(*_) -> None:
        st.session_state.pop(RESULT_KEY, None)
        st.session_state.pop(LOCK_RESULT_KEY, None)
        on_close()

    testgen.generate_tests_dialog_widget(
        key="generate_tests_dialog",
        data={
            "dialog": dialog,
            "test_suite_id": test_suite_id,
            "test_suite_name": test_suite_name,
            "generation_sets": generation_sets,
            "default_generation_set": default_set,
            "refresh_warning": refresh_warning,
            "lock_result": st.session_state.get(LOCK_RESULT_KEY),
            "result": st.session_state.get(RESULT_KEY),
        },
        on_LockEditedTests_change=on_lock_edited_tests,
        on_GenerateTestsConfirmed_change=on_generate_tests_confirmed,
        on_CloseClicked_change=on_close_clicked,
    )


@with_database_session
def get_test_suite_refresh_warning(test_suite_id: str) -> tuple[int, int, int]:
    result = fetch_one_from_db(
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

    if result:
        return result.test_ct, result.unlocked_test_ct, result.unlocked_edits_ct

    return None, None, None


@with_database_session
def get_generation_set_choices() -> list[str]:
    results = fetch_all_from_db(
        """
        SELECT DISTINCT generation_set
        FROM generation_sets
        ORDER BY generation_set;
        """
    )
    return [row.generation_set for row in results]


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
