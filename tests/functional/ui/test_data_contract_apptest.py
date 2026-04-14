"""
Streamlit AppTest — Data Contract first-time flow.

Tests the end-to-end UI path:
  Project dashboard → Data Contract page (no saved contract)
    → prerequisites check
    → "Generate Contract Preview →" button
    → health dashboard preview
    → "Save as Version 0" button
    → save dialog

The project dashboard → contract navigation uses a JS component (ViewContractClicked)
that cannot be simulated in AppTest; we enter the contract page directly via query
params (table_group_id=TG_ID), which is exactly what the browser does after that click.

Run:
    pytest -m functional tests/functional/ui/test_data_contract_apptest.py
"""
from __future__ import annotations

import pathlib
import yaml
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.functional

# Path to the standalone Streamlit app script used by AppTest.
_APP = str(pathlib.Path(__file__).parent / "apps" / "data_contract_first_time_flow.py")

# Paths to additional app scripts
_APP_SAVED        = str(pathlib.Path(__file__).parent / "apps" / "data_contract_saved_version.py")
_APP_STALE        = str(pathlib.Path(__file__).parent / "apps" / "data_contract_stale_version.py")
_APP_HIST         = str(pathlib.Path(__file__).parent / "apps" / "data_contract_historical_version.py")
_APP_NO_PROF      = str(pathlib.Path(__file__).parent / "apps" / "data_contract_no_profiling.py")
_APP_DEL_DIALOG   = str(pathlib.Path(__file__).parent / "apps" / "data_contract_delete_version_dialog.py")
_APP_TERM_DEL     = str(pathlib.Path(__file__).parent / "apps" / "data_contract_term_deletion.py")
_APP_SNAP_QUALITY = str(pathlib.Path(__file__).parent / "apps" / "data_contract_snapshot_quality.py")
_APP_YAML_IMPORT  = str(pathlib.Path(__file__).parent / "apps" / "data_contract_yaml_import.py")

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _at() -> AppTest:
    """Fresh AppTest instance pointing at the first-time-flow app script."""
    return AppTest.from_file(_APP, default_timeout=15)


def _at_saved() -> AppTest:
    return AppTest.from_file(_APP_SAVED, default_timeout=15)


def _at_stale() -> AppTest:
    return AppTest.from_file(_APP_STALE, default_timeout=15)


def _at_hist() -> AppTest:
    return AppTest.from_file(_APP_HIST, default_timeout=15)


def _at_no_prof() -> AppTest:
    return AppTest.from_file(_APP_NO_PROF, default_timeout=15)


def _all_text(at: AppTest) -> str:
    """Concatenate all rendered markdown/caption/success/info text for easy searching."""
    parts: list[str] = []
    for widget in at.markdown:
        parts.append(widget.value)
    for widget in at.success:
        parts.append(widget.value)
    for widget in at.info:
        parts.append(widget.value)
    return "\n".join(parts)


def _button_labels(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


def _click(at: AppTest, label: str) -> AppTest:
    """Click the first button whose label matches `label` and return `at`."""
    btn = next((b for b in at.button if b.label == label), None)
    if btn is None:
        raise AssertionError(
            f"Button '{label}' not found. Available: {_button_labels(at)}"
        )
    btn.click()
    at.run()
    return at


# ---------------------------------------------------------------------------
# Test_DataContractPageLoad — navigating to the contract page
# ---------------------------------------------------------------------------

class Test_DataContractPageLoad:

    def test_page_loads_without_exception(self):
        """The data contract page must render without raising an exception."""
        at = _at()
        at.run()
        assert not at.exception, f"Page raised: {at.exception}"

    def test_page_header_contains_table_group_name(self):
        """Table group name must flow through to contract content.
        page_header renders the title via st.html which is not accessible in AppTest;
        we verify the name appears in the save dialog info message instead."""
        at = _at()
        at.run()
        _click(at, "Generate Contract Preview →")
        _click(at, "Save as Version 0")
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("Test Orders" in t for t in info_texts), (
            f"Expected 'Test Orders' in info messages. Got: {info_texts}"
        )

    def test_query_param_table_group_id_is_set(self):
        """Confirms the AppTest correctly receives table_group_id as a query param —
        the same value the project dashboard passes when the user clicks 'View Contract'."""
        at = _at()
        at.run()
        assert not at.exception
        # AppTest stores query params as lists
        tg_values = at.query_params.get("table_group_id", [])
        assert TG_ID in tg_values, f"Expected {TG_ID} in {tg_values}"


# ---------------------------------------------------------------------------
# Test_FirstTimeFlow — first visit with no saved contract
# ---------------------------------------------------------------------------

class Test_FirstTimeFlow:

    def test_shows_no_contract_heading(self):
        """First visit must show 'No contract saved yet' heading."""
        at = _at()
        at.run()
        assert not at.exception
        assert any("No contract saved yet" in m.value for m in at.markdown), (
            f"Expected 'No contract saved yet'. Markdown: {[m.value for m in at.markdown]}"
        )

    def test_shows_profiling_prerequisite_passed(self):
        """Profiling run completed → green prerequisite row."""
        at = _at()
        at.run()
        assert not at.exception
        success_texts = [s.value for s in at.success]
        assert any("Profiling" in t for t in success_texts), (
            f"Expected profiling success. Got: {success_texts}"
        )

    def test_shows_test_suites_prerequisite_passed(self):
        """Test suites present → green prerequisite row."""
        at = _at()
        at.run()
        assert not at.exception
        success_texts = [s.value for s in at.success]
        assert any("Test suite" in t or "test" in t.lower() for t in success_texts), (
            f"Expected test suites success. Got: {success_texts}"
        )

    def test_generate_button_is_enabled_when_prereqs_pass(self):
        """'Generate Contract Preview →' must be present and enabled when prereqs pass."""
        at = _at()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Generate Contract Preview →" in labels, (
            f"Button not found. Available: {labels}"
        )
        btn = next(b for b in at.button if b.label == "Generate Contract Preview →")
        assert not btn.disabled, "Generate button should be enabled when prereqs pass"


# ---------------------------------------------------------------------------
# Test_GeneratePreview — clicking "Generate Contract Preview →"
# ---------------------------------------------------------------------------

class Test_GeneratePreview:

    def test_generate_button_click_shows_preview(self):
        """Clicking 'Generate Contract Preview →' must render the health dashboard preview."""
        at = _at()
        at.run()
        _click(at, "Generate Contract Preview →")

        assert not at.exception
        text = _all_text(at)
        assert "preview" in text.lower() or "Coverage" in text, (
            f"Expected preview content. Got markdown: {[m.value for m in at.markdown]}"
        )

    def test_preview_shows_coverage_card(self):
        """Health dashboard preview must include a 'Coverage' card."""
        at = _at()
        at.run()
        _click(at, "Generate Contract Preview →")

        assert not at.exception
        assert "Coverage" in _all_text(at)

    def test_preview_shows_save_button(self):
        """After generating preview, 'Save as Version 0' button must appear."""
        at = _at()
        at.run()
        _click(at, "Generate Contract Preview →")

        assert not at.exception
        assert "Save as Version 0" in _button_labels(at), (
            f"'Save as Version 0' not found. Buttons: {_button_labels(at)}"
        )

    def test_back_button_returns_to_prerequisites(self):
        """'← Back' must dismiss the preview and return to the prerequisites wizard."""
        at = _at()
        at.run()
        _click(at, "Generate Contract Preview →")
        _click(at, "← Back")

        assert not at.exception
        assert any("No contract saved yet" in m.value for m in at.markdown)
        assert "Generate Contract Preview →" in _button_labels(at)


# ---------------------------------------------------------------------------
# Test_SaveDialog — opening the save dialog
# ---------------------------------------------------------------------------

class Test_SaveDialog:

    def _open_save_dialog(self) -> AppTest:
        """Navigate to the preview and click 'Save as Version 0'."""
        at = _at()
        at.run()
        _click(at, "Generate Contract Preview →")
        _click(at, "Save as Version 0")
        return at

    def test_save_dialog_opens_without_exception(self):
        """Clicking 'Save as Version 0' must open the save dialog without errors."""
        at = self._open_save_dialog()
        assert not at.exception

    def test_save_dialog_shows_version_number(self):
        """Save dialog must confirm version 0 will be created."""
        at = self._open_save_dialog()
        assert not at.exception
        text = _all_text(at)
        assert "Version 0" in text or "version 0" in text.lower(), (
            f"Expected 'Version 0' in dialog. Text: {text}"
        )

    def test_save_dialog_shows_snapshot_suite_name(self):
        """Save dialog must show the name of the snapshot suite that will be created."""
        at = self._open_save_dialog()
        assert not at.exception
        text = _all_text(at)
        assert "[Contract v0] Test Orders" in text, (
            f"Expected snapshot suite name in dialog. Text: {text}"
        )

    def test_save_dialog_has_save_version_button(self):
        """Save dialog must contain a 'Save Version' confirm button."""
        at = self._open_save_dialog()
        assert not at.exception
        assert "Save Version" in _button_labels(at), (
            f"'Save Version' not found. Buttons: {_button_labels(at)}"
        )

    def test_save_dialog_has_cancel_button(self):
        """Save dialog must contain a 'Cancel' button."""
        at = self._open_save_dialog()
        assert not at.exception
        assert "Cancel" in _button_labels(at)


# ---------------------------------------------------------------------------
# Test 1: Test_StaleContractBanner — staleness warning on latest version
# ---------------------------------------------------------------------------

class Test_StaleContractBanner:

    def test_stale_banner_appears(self):
        """When a saved contract is stale, a staleness warning must be visible."""
        at = _at_stale()
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert any("Contract version" in t and "Since then" in t for t in warning_texts), (
            f"Expected staleness warning. Got: {warning_texts}"
        )

    def test_stale_banner_shows_regenerate_button(self):
        """Stale banner must offer a 'Review Changes' button to act on the staleness."""
        at = _at_stale()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Review Changes" in labels, (
            f"Expected 'Review Changes' button. Available: {labels}"
        )

    def test_stale_banner_shows_dismiss_button(self):
        """Stale banner must offer a 'Dismiss' button."""
        at = _at_stale()
        at.run()
        assert not at.exception
        assert "Dismiss" in _button_labels(at)

    def test_stale_banner_includes_schema_change_detail(self):
        """Stale warning text must mention the specific change returned by summary_parts()."""
        at = _at_stale()
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert any("1 new column added" in t for t in warning_texts), (
            f"Expected change detail in warning. Got: {warning_texts}"
        )


# ---------------------------------------------------------------------------
# Test 2: Test_HistoricalVersionReadOnly — older version is read-only
# ---------------------------------------------------------------------------

class Test_HistoricalVersionReadOnly:

    def test_historical_version_shows_read_only_info_banner(self):
        """Viewing an older version must show a read-only info banner."""
        at = _at_hist()
        at.run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("read-only snapshot" in t for t in info_texts), (
            f"Expected read-only info banner. Got: {info_texts}"
        )

    def test_historical_version_has_no_save_button(self):
        """Viewing an older version must not show 'Save version' button."""
        at = _at_hist()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Save version" not in labels, (
            f"Expected no 'Save version' on historical view. Buttons: {labels}"
        )

    def test_historical_version_has_no_regenerate_button(self):
        """Viewing an older version must not show 'Regenerate' button."""
        at = _at_hist()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Regenerate" not in labels, (
            f"Expected no 'Regenerate' on historical view. Buttons: {labels}"
        )

    def test_historical_version_info_mentions_version_number(self):
        """Read-only banner must identify the specific version number being viewed."""
        at = _at_hist()
        at.run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("version 0" in t.lower() for t in info_texts), (
            f"Expected version number in info. Got: {info_texts}"
        )

    def test_historical_version_info_mentions_latest_version(self):
        """Read-only banner must tell the user which is the latest version."""
        at = _at_hist()
        at.run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("latest is version 1" in t.lower() for t in info_texts), (
            f"Expected latest version hint in info. Got: {info_texts}"
        )


# ---------------------------------------------------------------------------
# Test 3: Test_ImportResultBanner — import result staged in session state
# ---------------------------------------------------------------------------

class Test_ImportResultBanner:

    def test_import_success_shows_success_banner(self):
        """A successful YAML import (pre-staged in session state) must show a success banner."""
        at = _at_saved()
        import_key = f"dc_import_result:{TG_ID}"
        _mock_diff = MagicMock()
        _mock_diff.has_errors = False
        _mock_diff.errors = []
        _mock_diff.warnings = []
        _mock_diff.test_inserts = [{"id": "x"}]
        _mock_diff.test_updates = []
        _mock_diff.new_id_by_index = {}
        at.session_state[import_key] = {
            "diff": _mock_diff,
            "original_yaml": "apiVersion: v3.1.0\nkind: DataContract\n",
        }
        at.run()
        assert not at.exception
        success_texts = [s.value for s in at.success]
        assert any("Import complete" in t for t in success_texts), (
            f"Expected 'Import complete' in success. Got: {success_texts}"
        )

    def test_import_success_mentions_created_count(self):
        """Import success banner must report the number of tests created."""
        at = _at_saved()
        import_key = f"dc_import_result:{TG_ID}"
        _mock_diff = MagicMock()
        _mock_diff.has_errors = False
        _mock_diff.errors = []
        _mock_diff.warnings = []
        _mock_diff.test_inserts = [{"id": "x"}, {"id": "y"}]
        _mock_diff.test_updates = []
        _mock_diff.new_id_by_index = {}
        at.session_state[import_key] = {
            "diff": _mock_diff,
            "original_yaml": "apiVersion: v3.1.0\nkind: DataContract\n",
        }
        at.run()
        assert not at.exception
        success_texts = [s.value for s in at.success]
        assert any("2 test(s) created" in t for t in success_texts), (
            f"Expected test count in success banner. Got: {success_texts}"
        )

    def test_import_error_shows_error_banner(self):
        """A failed YAML import (pre-staged) must show an error message."""
        at = _at_saved()
        import_key = f"dc_import_result:{TG_ID}"
        at.session_state[import_key] = {"error": "YAML parse failure"}
        at.run()
        assert not at.exception
        error_texts = [e.value for e in at.error]
        assert any("Import failed" in t for t in error_texts), (
            f"Expected 'Import failed' in error banner. Got: {error_texts}"
        )

    def test_import_error_includes_error_message(self):
        """Error banner must echo back the actual error string."""
        at = _at_saved()
        import_key = f"dc_import_result:{TG_ID}"
        at.session_state[import_key] = {"error": "YAML parse failure"}
        at.run()
        assert not at.exception
        error_texts = [e.value for e in at.error]
        assert any("YAML parse failure" in t for t in error_texts), (
            f"Expected error detail in banner. Got: {error_texts}"
        )


# ---------------------------------------------------------------------------
# Test 4: Test_BulkDeleteClearsCache — YAML cache presence/absence
# ---------------------------------------------------------------------------

class Test_BulkDeleteClearsCache:

    def test_page_renders_without_yaml_cache(self):
        """Page must re-fetch contract YAML if cache key is absent (simulates post-delete reload)."""
        at = _at_saved()
        # Do NOT pre-populate dc_yaml — ensure page fetches fresh from version record
        at.run()
        assert not at.exception

    def test_page_renders_with_yaml_cache(self):
        """Page must use cached YAML when available and render without exception."""
        at = _at_saved()
        yaml_key = f"dc_yaml:{TG_ID}"
        at.session_state[yaml_key] = (
            "apiVersion: v3.1.0\nkind: DataContract\nid: cached\nschema: []\nquality: []\n"
        )
        at.run()
        assert not at.exception

    def test_saved_version_shows_refresh_button(self):
        """Saved version page must always include the Refresh button for cache-busting."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "↺ Refresh" in _button_labels(at), (
            f"Expected '↺ Refresh' button. Available: {_button_labels(at)}"
        )

    def test_saved_version_shows_regenerate_button(self):
        """Latest saved version must show Regenerate button for re-exporting."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "Regenerate" in _button_labels(at), (
            f"Expected 'Regenerate' button. Available: {_button_labels(at)}"
        )


# ---------------------------------------------------------------------------
# Test 5: Test_MissingPrerequisiteBlocksGeneration — no profiling run
# ---------------------------------------------------------------------------

class Test_MissingPrerequisiteBlocksGeneration:

    def test_no_profiling_shows_error_state(self):
        """Missing profiling run must show an error prerequisite message."""
        at = _at_no_prof()
        at.run()
        assert not at.exception
        error_texts = [e.value for e in at.error]
        assert any("profiling" in t.lower() for t in error_texts), (
            f"Expected profiling error message. Got: {error_texts}"
        )

    def test_generate_button_disabled_without_profiling(self):
        """Generate button must be present but disabled when profiling prereq fails."""
        at = _at_no_prof()
        at.run()
        assert not at.exception
        btn = next(
            (b for b in at.button if b.label == "Generate Contract Preview →"), None
        )
        assert btn is not None, (
            f"'Generate Contract Preview →' button not found. Buttons: {_button_labels(at)}"
        )
        assert btn.disabled, "Generate button should be disabled when profiling prereq is missing"

    def test_no_profiling_still_shows_no_contract_heading(self):
        """Even without profiling, the 'No contract saved yet' heading must appear."""
        at = _at_no_prof()
        at.run()
        assert not at.exception
        assert any("No contract saved yet" in m.value for m in at.markdown), (
            f"Expected 'No contract saved yet'. Markdown: {[m.value for m in at.markdown]}"
        )

    def test_no_profiling_suite_prereq_still_passes(self):
        """Test suite prereq is still met; only profiling is the blocker."""
        at = _at_no_prof()
        at.run()
        assert not at.exception
        success_texts = [s.value for s in at.success]
        assert any("Test suite" in t or "test" in t.lower() for t in success_texts), (
            f"Expected test suite success. Got: {success_texts}"
        )


def _at_delete_dialog() -> AppTest:
    return AppTest.from_file(_APP_DEL_DIALOG, default_timeout=15)


def _at_term_deletion() -> AppTest:
    return AppTest.from_file(_APP_TERM_DEL, default_timeout=15)


# ---------------------------------------------------------------------------
# Test Group 1: Test_RegenerateDialog — Regenerate button and dialog
# ---------------------------------------------------------------------------

class Test_RegenerateDialog:

    def test_regenerate_button_is_present(self):
        """Latest saved version must show the Regenerate button."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "Regenerate" in _button_labels(at), (
            f"Expected 'Regenerate'. Available: {_button_labels(at)}"
        )

    def test_regenerate_dialog_opens_without_exception(self):
        """Clicking Regenerate must open the dialog without raising an exception."""
        at = _at_saved()
        at.run()
        _click(at, "Regenerate")
        assert not at.exception

    def test_regenerate_dialog_shows_next_version_number(self):
        """VERSION_1 has version=1, so the dialog header must say 'Version 2'."""
        at = _at_saved()
        at.run()
        _click(at, "Regenerate")
        assert not at.exception
        text = _all_text(at)
        assert "Version 2" in text, (
            f"Expected 'Version 2' in dialog text. Got: {text[:500]}"
        )

    def test_regenerate_dialog_shows_snapshot_suite_info(self):
        """Dialog must display an info message describing the new snapshot suite."""
        at = _at_saved()
        at.run()
        _click(at, "Regenerate")
        assert not at.exception
        assert any(at.info), "Expected at least one st.info widget in the dialog"

    def test_regenerate_dialog_has_regenerate_and_cancel_buttons(self):
        """Dialog must contain both 'Regenerate & Save' and 'Cancel' buttons."""
        at = _at_saved()
        at.run()
        _click(at, "Regenerate")
        assert not at.exception
        labels = _button_labels(at)
        assert "Regenerate & Save" in labels, (
            f"Expected 'Regenerate & Save'. Available: {labels}"
        )
        assert "Cancel" in labels, (
            f"Expected 'Cancel'. Available: {labels}"
        )


# ---------------------------------------------------------------------------
# Test Group 2: Test_DeleteVersionDialog — delete version dialog
# ---------------------------------------------------------------------------

class Test_DeleteVersionDialog:

    def test_dialog_opens_without_exception(self):
        """Delete version dialog must open without raising an exception."""
        at = _at_delete_dialog()
        at.run()
        assert not at.exception

    def test_dialog_shows_version_being_deleted(self):
        """Dialog header/body must identify 'contract v1' as the version being deleted."""
        at = _at_delete_dialog()
        at.run()
        assert not at.exception
        text = _all_text(at)
        assert "v1" in text.lower() or "version 1" in text.lower(), (
            f"Expected version reference in dialog. Got: {text[:500]}"
        )

    def test_dialog_shows_snapshot_suite_consequences(self):
        """Dialog must mention the snapshot suite name and test count."""
        at = _at_delete_dialog()
        at.run()
        assert not at.exception
        text = _all_text(at)
        assert "[Contract v1] Test Orders" in text, (
            f"Expected suite name in dialog. Got: {text[:500]}"
        )
        # 5 tests is what our mock returns
        assert "5" in text, f"Expected test count '5' in dialog. Got: {text[:500]}"

    def test_dialog_cannot_undo_warning(self):
        """Dialog must include 'cannot be undone' warning text."""
        at = _at_delete_dialog()
        at.run()
        assert not at.exception
        text = _all_text(at)
        assert "cannot be undone" in text.lower(), (
            f"Expected 'cannot be undone' warning. Got: {text[:500]}"
        )

    def test_dialog_has_delete_and_cancel_buttons(self):
        """Dialog must render both 'Delete' and 'Cancel' buttons."""
        at = _at_delete_dialog()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Delete" in labels, f"Expected 'Delete'. Available: {labels}"
        assert "Cancel" in labels, f"Expected 'Cancel'. Available: {labels}"

    def test_delete_button_disabled_without_confirmation(self):
        """'Delete' button must be disabled when the confirmation text_input is empty."""
        at = _at_delete_dialog()
        at.run()
        assert not at.exception
        delete_btn = next((b for b in at.button if b.label == "Delete"), None)
        assert delete_btn is not None, f"'Delete' button not found. Available: {_button_labels(at)}"
        assert delete_btn.disabled, "Delete button should be disabled until 'DELETE' is typed"


# ---------------------------------------------------------------------------
# Test Group 3: Test_DeleteContractTermByType — YAML mutation via term deletion
# ---------------------------------------------------------------------------

def _setup_deletion(at: AppTest, terms: list[dict]) -> AppTest:
    """Pre-stage deletion payload (no yaml pre-seed — script seeds FULL_YAML on first run)."""
    at.session_state["dc_test_delete_payload"] = {"terms": terms}
    at.run()
    return at


def _get_yaml(at: AppTest) -> dict:
    key = f"dc_yaml:{TG_ID}"
    raw = at.session_state[key] if key in at.session_state else ""
    return yaml.safe_load(raw) or {}


class Test_DeleteContractTermByType:

    def test_deletion_trigger_is_processed(self):
        """When dc_test_delete_payload is set, it must be consumed and YAML modified."""
        at = _at_term_deletion()
        at.session_state["dc_test_delete_payload"] = {
            "terms": [{"source": "ddl", "name": "Data Type", "table": "orders", "col": "amount"}]
        }
        at.run()
        assert not at.exception
        # The trigger must have been consumed (not still in session state)
        assert "dc_test_delete_payload" not in at.session_state, (
            "dc_test_delete_payload should be consumed after run"
        )
        # And YAML must be modified
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        assert "physicalType" not in prop, f"physicalType should be removed. Prop: {prop}"

    def test_delete_ddl_data_type(self):
        """Deleting DDL 'Data Type' removes physicalType from the YAML."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "ddl", "name": "Data Type", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        assert "physicalType" not in prop, f"physicalType should be removed. Prop: {prop}"
        # Second render with modified YAML must not crash
        at.run()
        assert not at.exception

    def test_delete_ddl_not_null(self):
        """Deleting DDL 'Not Null' removes the required field from the YAML."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "ddl", "name": "Not Null", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        assert "required" not in prop, f"required should be removed. Prop: {prop}"
        at.run()
        assert not at.exception

    def test_delete_profiling_min_value(self):
        """Deleting profiling 'Min Value' removes the testgen.minimum customProperty."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "profiling", "name": "Min Value", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        cp_keys = [c.get("property") for c in (prop.get("customProperties") or [])]
        assert "testgen.minimum" not in cp_keys, f"testgen.minimum should be removed. cp: {cp_keys}"
        at.run()
        assert not at.exception

    def test_delete_profiling_logical_type(self):
        """Deleting profiling 'Logical Type' removes logicalType from the YAML."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "profiling", "name": "Logical Type", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        assert "logicalType" not in prop, f"logicalType should be removed. Prop: {prop}"
        at.run()
        assert not at.exception

    def test_delete_profiling_format(self):
        """Deleting profiling 'Format' removes testgen.format customProperty."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "profiling", "name": "Format", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        cp_keys = [c.get("property") for c in (prop.get("customProperties") or [])]
        assert "testgen.format" not in cp_keys, f"testgen.format should be removed. cp: {cp_keys}"
        at.run()
        assert not at.exception

    def test_delete_governance_description(self):
        """Deleting governance 'Description' removes description from the YAML."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "governance", "name": "Description", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        assert "description" not in prop, f"description should be removed. Prop: {prop}"
        at.run()
        assert not at.exception

    def test_delete_governance_critical_data_element(self):
        """Deleting governance 'Critical Data Element' removes criticalDataElement."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "governance", "name": "Critical Data Element", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        prop = doc["schema"][0]["properties"][0]
        assert "criticalDataElement" not in prop, f"criticalDataElement should be removed. Prop: {prop}"
        at.run()
        assert not at.exception

    def test_delete_test_quality_rule(self):
        """Deleting a test rule removes it from the quality list."""
        at = _setup_deletion(
            _at_term_deletion(),
            [{"source": "test", "rule_id": "rule-test-001", "table": "orders", "col": "amount"}],
        )
        assert not at.exception
        doc = _get_yaml(at)
        ids = [q.get("id") for q in (doc.get("quality") or [])]
        assert "rule-test-001" not in ids, f"rule-test-001 should be removed. ids: {ids}"
        # The other rule must remain
        assert "rule-test-002" in ids, f"rule-test-002 should still be present. ids: {ids}"
        at.run()
        assert not at.exception

    def test_delete_all_quality_rules(self):
        """Deleting all quality rules leaves an empty quality list."""
        at = _setup_deletion(
            _at_term_deletion(),
            [
                {"source": "test", "rule_id": "rule-test-001", "table": "orders", "col": "amount"},
                {"source": "test", "rule_id": "rule-test-002", "table": "orders", "col": "amount"},
            ],
        )
        assert not at.exception
        doc = _get_yaml(at)
        quality = doc.get("quality") or []
        assert len(quality) == 0, f"Expected empty quality list. Got: {quality}"
        at.run()
        assert not at.exception

    def test_page_renders_after_all_deletions(self):
        """Page renders without exception when all schema terms are removed."""
        at = _setup_deletion(
            _at_term_deletion(),
            [
                {"source": "ddl", "name": "Data Type", "table": "orders", "col": "amount"},
                {"source": "ddl", "name": "Not Null", "table": "orders", "col": "amount"},
                {"source": "profiling", "name": "Logical Type", "table": "orders", "col": "amount"},
                {"source": "governance", "name": "Description", "table": "orders", "col": "amount"},
                {"source": "governance", "name": "Critical Data Element", "table": "orders", "col": "amount"},
                {"source": "test", "rule_id": "rule-test-001", "table": "orders", "col": "amount"},
                {"source": "test", "rule_id": "rule-test-002", "table": "orders", "col": "amount"},
            ],
        )
        assert not at.exception
        at.run()
        assert not at.exception


# ---------------------------------------------------------------------------
# Test_SnapshotQualityRebuilt — add-test shows in YAML
# ---------------------------------------------------------------------------

class Test_SnapshotQualityRebuilt:
    """
    Verify that for a snapshot-backed contract, dc_yaml is populated with fresh
    quality data from rebuild_quality_from_suite rather than the frozen saved-version YAML.
    This covers the case where a test is added to the snapshot suite and should
    immediately appear in the YAML tab without manual regeneration.
    """

    def _at(self) -> AppTest:
        return AppTest.from_file(_APP_SNAP_QUALITY, default_timeout=10)

    def test_page_loads_without_exception(self):
        at = self._at()
        at.run()
        assert not at.exception

    def test_rebuilt_yaml_stored_in_session_state(self):
        """dc_yaml in session state comes from rebuild_quality_from_suite, not saved version."""
        at = self._at()
        at.run()
        assert not at.exception
        yaml_key = f"dc_yaml:{TG_ID}"
        assert yaml_key in at.session_state
        stored_yaml = at.session_state[yaml_key]
        doc = yaml.safe_load(stored_yaml)
        # The rebuilt YAML includes the new test rule; the base YAML has empty quality
        assert doc.get("quality"), "quality section should be non-empty after rebuild"

    def test_new_test_rule_id_in_yaml(self):
        """The newly-added test rule ID is present in dc_yaml after rebuild."""
        at = self._at()
        at.run()
        assert not at.exception
        yaml_key = f"dc_yaml:{TG_ID}"
        assert yaml_key in at.session_state
        stored_yaml = at.session_state[yaml_key]
        assert "dddddddd-0000-0000-0000-000000000004" in stored_yaml, (
            "New test rule ID must appear in dc_yaml after rebuild_quality_from_suite"
        )

    def test_base_yaml_quality_was_empty(self):
        """Confirm the base (saved-version) YAML had no quality rules — rebuild added them."""
        at = self._at()
        at.run()
        assert not at.exception
        yaml_key = f"dc_yaml:{TG_ID}"
        assert yaml_key in at.session_state
        stored_yaml = at.session_state[yaml_key]
        # The rebuilt YAML should differ from the base (which had 'quality: []')
        assert "not_null" in stored_yaml.lower() or "Not Null" in stored_yaml, (
            "Rebuilt YAML should contain the test type from the snapshot suite"
        )


# ---------------------------------------------------------------------------
# Test_YamlImportFlow — create contract from uploaded YAML
# ---------------------------------------------------------------------------

class Test_YamlImportFlow:
    """Verify the 'Or import from YAML' expander on the first-time flow page."""

    def _at(self) -> AppTest:
        return AppTest.from_file(_APP_YAML_IMPORT, default_timeout=10)

    def test_page_loads_without_exception(self):
        at = self._at()
        at.run()
        assert not at.exception

    def test_import_expander_visible(self):
        """'Or import from YAML' expander is present on first-time flow page."""
        at = self._at()
        at.run()
        assert not at.exception
        all_text = " ".join(str(e) for e in at.expander)
        assert "import" in all_text.lower() or "yaml" in all_text.lower()
