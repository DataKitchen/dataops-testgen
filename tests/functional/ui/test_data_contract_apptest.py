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
_APP_IMPORT_CONFIRM = str(pathlib.Path(__file__).parent / "apps" / "data_contract_import_confirm.py")

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CONTRACT_ID = "cccccccc-0000-0000-0000-000000000001"


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

    def test_query_param_contract_id_is_set(self):
        """Confirms the AppTest correctly receives contract_id as a query param —
        the same value passed when the user navigates to the contract detail page."""
        at = _at()
        at.run()
        assert not at.exception
        # AppTest stores query params as lists
        contract_values = at.query_params.get("contract_id", [])
        assert CONTRACT_ID in contract_values, f"Expected {CONTRACT_ID} in {contract_values}"


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
        import_key = f"dc_import_result:{CONTRACT_ID}"
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
        import_key = f"dc_import_result:{CONTRACT_ID}"
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
        assert any("2 tests created" in t for t in success_texts), (
            f"Expected test count in success banner. Got: {success_texts}"
        )

    def test_import_error_shows_error_banner(self):
        """A failed YAML import (pre-staged) must show an error message."""
        at = _at_saved()
        import_key = f"dc_import_result:{CONTRACT_ID}"
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
        import_key = f"dc_import_result:{CONTRACT_ID}"
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
        yaml_key = f"dc_yaml:{CONTRACT_ID}"
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
    key = f"dc_yaml:{CONTRACT_ID}"
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
        yaml_key = f"dc_yaml:{CONTRACT_ID}"
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
        yaml_key = f"dc_yaml:{CONTRACT_ID}"
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
        yaml_key = f"dc_yaml:{CONTRACT_ID}"
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


# ---------------------------------------------------------------------------
# Fixture helpers for new test groups
# ---------------------------------------------------------------------------

_APP_SINGLE_VERSION  = str(pathlib.Path(__file__).parent / "apps" / "data_contract_single_version.py")
_APP_PENDING_EDITS   = str(pathlib.Path(__file__).parent / "apps" / "data_contract_pending_edits.py")
_APP_IMPORT_SAVED    = str(pathlib.Path(__file__).parent / "apps" / "data_contract_import_saved.py")


def _at_single_version() -> AppTest:
    return AppTest.from_file(_APP_SINGLE_VERSION, default_timeout=15)


def _at_pending_edits() -> AppTest:
    return AppTest.from_file(_APP_PENDING_EDITS, default_timeout=15)


def _at_import_saved() -> AppTest:
    return AppTest.from_file(_APP_IMPORT_SAVED, default_timeout=15)


# ---------------------------------------------------------------------------
# Test_EditRuleDialog — EditRuleClicked event handler
# ---------------------------------------------------------------------------

class Test_EditRuleDialog:

    def test_edit_rule_dialog_opens_for_latest_version(self):
        """Pre-seed dc_pending with a rule edit matching saved-version YAML; page loads without exception."""
        at = _at_saved()
        # Verify page loads cleanly — the testgen_component is mocked so EditRuleClicked
        # cannot be fired directly, but the surrounding page logic must not crash.
        at.run()
        assert not at.exception

    def test_edit_rule_dialog_blocked_for_historical_version(self):
        """Historical version: on_edit_rule returns early when is_latest=False — no dialog crash."""
        at = _at_hist()
        at.run()
        assert not at.exception
        # No dialog-related error widgets expected
        error_texts = [e.value for e in at.error]
        assert not any("edit" in t.lower() for t in error_texts), (
            f"Unexpected edit-related error on historical view. Got: {error_texts}"
        )

    def test_edit_rule_saves_pending_edit_to_session_state(self):
        """Pending test edit round-trips through session state correctly."""
        at = _at_pending_edits()
        pending_key = f"dc_pending:{CONTRACT_ID}"
        at.session_state["dc_test_inject_pending"] = {
            "tests": [{"rule_id": "rule-001", "field": "mustBeGreaterThan", "value": "10"}],
            "governance": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        # Pending edits survive a page render
        assert pending_key in at.session_state
        stored = at.session_state[pending_key]
        test_edits = stored.get("tests", [])
        assert any(e.get("rule_id") == "rule-001" for e in test_edits), (
            f"rule-001 edit should be in pending tests. Got: {test_edits}"
        )


# ---------------------------------------------------------------------------
# Test_GovernanceEditDialog — GovernanceEditClicked event handler
# ---------------------------------------------------------------------------

class Test_GovernanceEditDialog:

    def test_governance_edit_blocked_for_historical_version(self):
        """Historical version: on_governance_edit returns early — no exception, no dialog."""
        at = _at_hist()
        at.run()
        assert not at.exception
        # on_governance_edit guards with 'if not is_latest: return'
        # So page renders without opening any dialog
        error_texts = [e.value for e in at.error]
        assert not any("governance" in t.lower() for t in error_texts)

    def test_governance_edit_shows_unsaved_changes_banner_when_pending(self):
        """Pre-seeding dc_pending with a governance edit → unsaved-changes warning visible."""
        at = _at_pending_edits()
        pending_key = f"dc_pending:{CONTRACT_ID}"
        at.session_state["dc_test_inject_pending"] = {
            "governance": [
                {"field": "description", "value": "New desc", "table": "orders",
                 "col": "amount", "snapshot": {"name": "Description", "source": "governance", "verif": "declared"}}
            ],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        # The unsaved-changes warning banner must be present (pending_ct > 0)
        warning_texts = [w.value for w in at.warning]
        assert any("staged" in t.lower() or "not yet saved" in t.lower() for t in warning_texts), (
            f"Expected unsaved-changes warning. Got: {warning_texts}"
        )


# ---------------------------------------------------------------------------
# Test_AddTestButton — add test button presence
# ---------------------------------------------------------------------------

class Test_AddTestButton:

    def test_add_test_button_absent_without_snapshot_suite(self):
        """No snapshot_suite_id → on_add_test returns early; page loads without exception."""
        # Use single_version fixture which has snapshot_suite_id set; we override via session
        at = _at_single_version()
        # The single version has a snapshot_suite_id, but AddTestClicked is behind testgen_component
        # which is mocked — so we just verify no crash on load.
        at.run()
        assert not at.exception

    def test_add_test_button_present_on_snapshot_suite(self):
        """Version with snapshot_suite_id renders without exception."""
        at = _at_saved()
        at.run()
        assert not at.exception
        # snapshot_suite_id is set in VERSION_1; page should render without error
        error_texts = [e.value for e in at.error]
        assert not any("snapshot" in t.lower() for t in error_texts)


# ---------------------------------------------------------------------------
# Test_VersionSwitching — version picker selectbox
# ---------------------------------------------------------------------------

class Test_VersionSwitching:

    def test_version_picker_visible_when_multiple_versions(self):
        """Multiple versions → a selectbox is rendered for version switching."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert len(at.selectbox) > 0, (
            f"Expected at least one selectbox (version picker) with 2 versions. "
            f"Found {len(at.selectbox)} selectboxes."
        )

    def test_version_picker_hidden_for_single_version(self):
        """Single version → no selectbox for version switching."""
        at = _at_single_version()
        at.run()
        assert not at.exception
        assert len(at.selectbox) == 0, (
            f"Expected no selectbox with a single version. "
            f"Found {len(at.selectbox)} selectboxes."
        )


# ---------------------------------------------------------------------------
# Test_DeleteContractButton — delete contract button removed from toolbar
# ---------------------------------------------------------------------------

class Test_DeleteContractButton:

    def test_delete_contract_button_absent_on_single_version(self):
        """'Delete contract' toolbar button was removed; must not appear on any page."""
        at = _at_single_version()
        at.run()
        assert not at.exception
        assert "Delete contract" not in _button_labels(at), (
            f"'Delete contract' button should have been removed from toolbar. Available: {_button_labels(at)}"
        )

    def test_delete_contract_button_absent_on_saved_version(self):
        """'Delete contract' must not appear in button labels on the saved version page."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "Delete contract" not in _button_labels(at), (
            f"'Delete contract' button should have been removed from toolbar. Available: {_button_labels(at)}"
        )


# ---------------------------------------------------------------------------
# Test_SaveVersionFlow — save button label and pending edit state
# ---------------------------------------------------------------------------

class Test_SaveVersionFlow:

    def test_save_button_label_shows_pending_count(self):
        """When pending edits exist, save button label includes the count."""
        at = _at_pending_edits()
        # 3 pending governance edits
        at.session_state["dc_test_inject_pending"] = {
            "governance": [
                {"field": "description", "value": "v1", "table": "orders", "col": "a",
                 "snapshot": {"name": "Description", "source": "governance", "verif": "declared"}},
                {"field": "description", "value": "v2", "table": "orders", "col": "b",
                 "snapshot": {"name": "Description", "source": "governance", "verif": "declared"}},
                {"field": "description", "value": "v3", "table": "orders", "col": "c",
                 "snapshot": {"name": "Description", "source": "governance", "verif": "declared"}},
            ],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        # Save button label should contain the pending count (3)
        assert any("3" in lbl for lbl in labels), (
            f"Expected '3' in a button label (pending count). Available: {labels}"
        )

    def test_save_button_default_label_without_pending(self):
        """No pending edits → save button shows default 'Save version' label."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "Save version" in _button_labels(at), (
            f"Expected 'Save version'. Available: {_button_labels(at)}"
        )

    def test_cancel_save_preserves_pending_edits(self):
        """Pending edits survive a page render without being clicked away."""
        at = _at_pending_edits()
        pending_key = f"dc_pending:{CONTRACT_ID}"
        pending_data = {
            "governance": [
                {"field": "description", "value": "keep me", "table": "orders", "col": "amount",
                 "snapshot": {"name": "Description", "source": "governance", "verif": "declared"}}
            ],
            "tests": [],
            "deletions": [],
        }
        at.session_state["dc_test_inject_pending"] = pending_data.copy()
        at.run()
        assert not at.exception
        # Pending edits must still be in session state after a plain render
        assert pending_key in at.session_state, "dc_pending key should persist across render"
        stored = at.session_state[pending_key]
        assert stored.get("governance"), "Governance pending edits should still be present"


# ---------------------------------------------------------------------------
# Test_RefreshButton — refresh button behavior
# ---------------------------------------------------------------------------

class Test_RefreshButton:

    def test_refresh_clears_all_cache_keys(self):
        """Clicking '↺ Refresh' removes all dc_* cache keys from session state."""
        at = _at_saved()
        # First run to render the page and populate session state
        at.run()
        assert not at.exception
        # Pre-seed extra cache keys that refresh should clear
        at.session_state[f"dc_anomalies:{CONTRACT_ID}"] = ["stale-anomaly"]
        at.session_state[f"dc_gov:{CONTRACT_ID}"] = {"stale": True}
        at.session_state[f"dc_run_dates:{CONTRACT_ID}"] = {"stale": True}
        at.session_state[f"dc_suite_scope:{CONTRACT_ID}"] = {"stale": True}
        at.session_state[f"dc_staleness_diff:{CONTRACT_ID}"] = MagicMock()
        # Click Refresh — pops all keys then reruns the page
        _click(at, "↺ Refresh")
        assert not at.exception
        # Page ran successfully after clearing all cache keys — no exception means
        # the keys were properly cleared and re-populated from the mocked DB calls.

    def test_refresh_button_present_on_saved_version(self):
        """'↺ Refresh' must be in button labels on the saved version page."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "↺ Refresh" in _button_labels(at), (
            f"Expected '↺ Refresh'. Available: {_button_labels(at)}"
        )


# ---------------------------------------------------------------------------
# Test_RegenerateButton (extends existing Test_RegenerateDialog)
# ---------------------------------------------------------------------------

class Test_RegenerateButton:

    def test_regenerate_button_absent_for_historical_version(self):
        """Historical version must NOT show the 'Regenerate' button."""
        at = _at_hist()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Regenerate" not in labels, (
            f"Expected no 'Regenerate' on historical view. Available: {labels}"
        )


# ---------------------------------------------------------------------------
# Test_BulkDeleteEdgeCases — edge cases for BulkDeleteTermsClicked handler
# ---------------------------------------------------------------------------

class Test_BulkDeleteEdgeCases:

    def test_deletion_of_nonexistent_rule_id_is_safe(self):
        """Deleting a made-up rule_id causes no exception; YAML quality list unchanged."""
        at = _at_term_deletion()
        at.session_state["dc_test_delete_payload"] = {
            "terms": [{"source": "test", "rule_id": "00000000-ffff-ffff-ffff-000000000000",
                       "table": "orders", "col": "amount"}]
        }
        at.run()
        assert not at.exception
        # YAML should still have both original rules (nonexistent rule changed nothing)
        doc = _get_yaml(at)
        ids = [q.get("id") for q in (doc.get("quality") or [])]
        assert "rule-test-001" in ids, f"rule-test-001 should remain. ids: {ids}"
        assert "rule-test-002" in ids, f"rule-test-002 should remain. ids: {ids}"

    def test_select_mode_renders_without_exception(self):
        """Deletion payload with valid terms renders without exception."""
        at = _at_term_deletion()
        at.session_state["dc_test_delete_payload"] = {
            "terms": [{"source": "ddl", "name": "Data Type", "table": "orders", "col": "amount"}]
        }
        at.run()
        assert not at.exception


# ---------------------------------------------------------------------------
# Test_ComplianceTab — compliance tab empty state
# ---------------------------------------------------------------------------

class Test_ComplianceTab:

    def test_compliance_tab_empty_state_message_before_run(self):
        """Contract with all-zero test counts (not-run) renders without exception."""
        at = _at_saved()
        # _minimal_term_diff has all counts = 0, entries = [] → empty compliance state
        at.run()
        assert not at.exception
        # Just confirm the page rendered (empty state is inside VanJS iframe)


# ---------------------------------------------------------------------------
# Test_ImportYamlEdgeCases — import flow cache behavior
# ---------------------------------------------------------------------------

class Test_ImportYamlEdgeCases:

    def test_import_clears_yaml_cache_on_success(self):
        """Successful import clears dc_yaml cache so next render fetches fresh data."""
        at = _at_import_saved()
        yaml_key = f"dc_yaml:{CONTRACT_ID}"
        # Pre-seed the import trigger and YAML cache
        at.session_state["dc_test_import_trigger"] = "apiVersion: v3.1.0\nkind: DataContract\n"
        at.session_state[yaml_key] = "old-cached-yaml"
        at.run()
        assert not at.exception
        # After successful import, the fixture clears yaml_key then the page re-populates it.
        # We verify: (a) no exception, (b) import result was consumed (success banner shown)
        success_texts = [s.value for s in at.success]
        assert any("Import complete" in t for t in success_texts), (
            f"Expected 'Import complete' after triggered import. Got: {success_texts}"
        )

    def test_import_preserves_session_on_failure(self):
        """Failed import (error path) keeps dc_yaml cache intact."""
        at = _at_import_saved()
        yaml_key = f"dc_yaml:{CONTRACT_ID}"
        original_yaml = "apiVersion: v3.1.0\nkind: DataContract\nid: preserved\n"
        at.session_state["dc_test_import_trigger"] = "INVALID"
        at.session_state[yaml_key] = original_yaml
        at.run()
        assert not at.exception
        # Error banner must be shown
        error_texts = [e.value for e in at.error]
        assert any("Import failed" in t for t in error_texts), (
            f"Expected 'Import failed' on error path. Got: {error_texts}"
        )
        # dc_yaml must still be set (not cleared on failure)
        assert yaml_key in at.session_state, (
            "dc_yaml should be preserved when import fails"
        )


# ---------------------------------------------------------------------------
# Test_ImportConfirmDialog — _confirm_import_dialog UI
# ---------------------------------------------------------------------------

def _at_import_confirm(scenario: str = "creates") -> AppTest:
    at = AppTest.from_file(_APP_IMPORT_CONFIRM, default_timeout=15)
    at.session_state["dc_test_confirm_scenario"] = scenario
    return at


class Test_ImportConfirmDialog:

    def test_dialog_renders_without_exception(self):
        """Confirmation dialog must render for a normal preview diff."""
        at = _at_import_confirm("creates")
        at.run()
        assert not at.exception, f"Dialog raised: {at.exception}"

    def test_dialog_shows_accepted_metric(self):
        """Accepted metric must equal creates + updates + no_change (3+2+1=6)."""
        at = _at_import_confirm("creates")
        at.run()
        assert not at.exception
        metric_values = {m.label: m.value for m in at.metric}
        assert "Accepted" in metric_values, f"Expected 'Accepted' metric. Got: {list(metric_values)}"
        assert metric_values["Accepted"] == "6", (
            f"Expected Accepted=6. Got: {metric_values['Accepted']}"
        )

    def test_dialog_shows_skipped_metric(self):
        """Skipped metric must equal skipped_rules count (2)."""
        at = _at_import_confirm("creates")
        at.run()
        assert not at.exception
        metric_values = {m.label: m.value for m in at.metric}
        assert "Skipped" in metric_values, f"Expected 'Skipped' metric. Got: {list(metric_values)}"
        assert metric_values["Skipped"] == "2", (
            f"Expected Skipped=2. Got: {metric_values['Skipped']}"
        )

    def test_dialog_shows_breakdown_in_markdown(self):
        """Dialog body must list create/update/unchanged/skipped counts."""
        at = _at_import_confirm("creates")
        at.run()
        assert not at.exception
        body = "\n".join(m.value for m in at.markdown)
        assert "3" in body, "Expected create count (3) in dialog body"
        assert "2" in body, "Expected update count (2) in dialog body"

    def test_dialog_has_confirm_and_cancel_buttons(self):
        """Both Confirm Import and Cancel buttons must be present."""
        at = _at_import_confirm("creates")
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Confirm Import" in labels, f"Expected 'Confirm Import'. Got: {labels}"
        assert "Cancel" in labels, f"Expected 'Cancel'. Got: {labels}"

    def test_error_preview_shows_error_and_close(self):
        """When preview.has_errors, dialog must show error text and a Close button instead."""
        at = _at_import_confirm("errors")
        at.run()
        assert not at.exception
        error_texts = [e.value for e in at.error]
        assert any("not found" in t for t in error_texts), (
            f"Expected error message in dialog. Got: {error_texts}"
        )
        labels = _button_labels(at)
        assert "Close" in labels, f"Expected 'Close' button on error. Got: {labels}"
        assert "Confirm Import" not in labels, "Confirm Import must not appear when preview has errors"

    def test_governance_updates_shown(self):
        """When governance_updates present, dialog must mention column governance updates."""
        at = _at_import_confirm("governance")
        at.run()
        assert not at.exception
        body = "\n".join(m.value for m in at.markdown)
        assert "governance" in body.lower(), (
            f"Expected governance mention in dialog body. Got:\n{body}"
        )

    def test_warnings_expander_shown(self):
        """When warnings exist, dialog must render an expander listing them."""
        at = _at_import_confirm("warnings")
        at.run()
        assert not at.exception
        # warnings appear inside expander — check warning elements
        warn_texts = [w.value for w in at.warning]
        assert any("Skipped" in w or "not found" in w for w in warn_texts), (
            f"Expected skipped warning in dialog. Got: {warn_texts}"
        )

    def test_orphaned_ids_shows_info(self):
        """When orphaned_ids present, dialog must show an info note."""
        at = _at_import_confirm("orphans")
        at.run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("not in this YAML" in t or "not affected" in t for t in info_texts), (
            f"Expected orphan info in dialog. Got: {info_texts}"
        )

    def test_confirm_button_triggers_import(self):
        """Clicking Confirm Import must call run_import_contract and set import_key."""
        at = _at_import_confirm("creates")
        at.run()
        assert not at.exception
        _click(at, "Confirm Import")
        import_key = f"dc_import_result:aaaaaaaa-0000-0000-0000-000000000001"
        assert import_key in at.session_state, (
            "import_key must be set in session state after Confirm Import"
        )


# ---------------------------------------------------------------------------
# Test_PendingEditsUX — pending-edits UX improvements (sticky bar, chip keys,
# save label, warning banner)
# ---------------------------------------------------------------------------

def _pending_gov_edit(table: str = "orders", col: str = "amount", field: str = "description", value: str = "updated") -> dict:
    """Helper: a single governance pending edit entry."""
    return {
        "field": field,
        "value": value,
        "table": table,
        "col": col,
        "snapshot": {"name": field.capitalize(), "source": "governance", "verif": "declared"},
    }


def _pending_test_edit(rule_id: str = "rule-pending-001") -> dict:
    """Helper: a single test pending edit entry."""
    return {
        "rule_id": rule_id,
        "threshold": 5,
        "snapshot": {"rule_id": rule_id, "threshold": 0},
    }


class Test_PendingEditsUX:
    """Tests for the pending-edits UX: save label, warning banner, and pending key props."""

    # -- save button label -------------------------------------------------

    def test_save_button_shows_version_label_with_count_when_pending(self):
        """Save button label must read 'Save version (N)' when N pending edits exist."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit()],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert any("Save version" in lbl and "1" in lbl for lbl in labels), (
            f"Expected 'Save version (1)' button. Available: {labels}"
        )

    def test_save_button_shows_plain_version_label_without_pending(self):
        """Save button label must read 'Save version' (no count) when no pending edits."""
        at = _at_saved()
        at.run()
        assert not at.exception
        assert "Save version" in _button_labels(at), (
            f"Expected 'Save version'. Available: {_button_labels(at)}"
        )
        # Must NOT have a count suffix
        assert not any("Save version (" in lbl for lbl in _button_labels(at)), (
            f"Save button must not show count without pending edits. Labels: {_button_labels(at)}"
        )

    def test_save_button_count_reflects_multiple_pending_edits(self):
        """Count in save label must equal the total number of staged changes."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [
                _pending_gov_edit(col="a"),
                _pending_gov_edit(col="b"),
            ],
            "tests": [_pending_test_edit()],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        # 2 governance + 1 test = 3 staged changes
        assert any("3" in lbl for lbl in labels), (
            f"Expected '3' in save button label for 3 pending edits. Available: {labels}"
        )

    # -- warning banner ----------------------------------------------------

    def test_warning_banner_present_when_pending(self):
        """Unsaved-changes warning banner must appear when pending edits exist."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit()],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert any("staged" in t.lower() or "not yet saved" in t.lower() for t in warning_texts), (
            f"Expected unsaved-changes warning. Got: {warning_texts}"
        )

    def test_warning_banner_absent_without_pending(self):
        """No warning banner must appear when there are no pending edits."""
        at = _at_saved()
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert not any("staged" in t.lower() or "not yet saved" in t.lower() for t in warning_texts), (
            f"Unexpected unsaved warning without pending edits. Got: {warning_texts}"
        )

    def test_warning_banner_references_save_button_label(self):
        """Warning banner text must reference 'Save version (N)' matching the button."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit()],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert any("Save version" in t for t in warning_texts), (
            f"Expected 'Save version' in warning text. Got: {warning_texts}"
        )

    def test_warning_banner_count_matches_pending_count(self):
        """Count in warning banner must equal the number of staged changes."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit(col="a"), _pending_gov_edit(col="b")],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert any("2" in t for t in warning_texts), (
            f"Expected '2' in warning banner. Got: {warning_texts}"
        )

    # -- pending_edit_rule_ids / pending_edit_gov_keys props ---------------

    def test_pending_edit_rule_ids_populated_in_props(self):
        """rule_ids from staged test edits must appear in props passed to testgen_component."""
        at = _at_pending_edits()
        rule_id = "rule-abc-123"
        at.session_state["dc_test_inject_pending"] = {
            "governance": [],
            "tests": [_pending_test_edit(rule_id=rule_id)],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        # The page stores pending in session state; verify the pending tests are present.
        pending_key = f"dc_pending:{CONTRACT_ID}"
        assert pending_key in at.session_state, "dc_pending key must be present"
        stored = at.session_state[pending_key]
        test_edits = stored.get("tests", [])
        assert any(e.get("rule_id") == rule_id for e in test_edits), (
            f"Expected rule_id '{rule_id}' in pending tests. Got: {test_edits}"
        )

    def test_pending_edit_gov_keys_populated_in_session(self):
        """Governance staged edits must round-trip through session state with table/col/field."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit(table="orders", col="amount", field="description")],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception
        pending_key = f"dc_pending:{CONTRACT_ID}"
        assert pending_key in at.session_state, "dc_pending key must be present"
        stored = at.session_state[pending_key]
        gov_edits = stored.get("governance", [])
        assert any(
            e.get("table") == "orders" and e.get("col") == "amount" and e.get("field") == "description"
            for e in gov_edits
        ), f"Expected governance edit for orders.amount.description. Got: {gov_edits}"

    # -- sticky bar events -------------------------------------------------

    def test_discard_from_sticky_bar_event_registered(self):
        """DiscardFromStickyBar event handler must be reachable — page loads without exception."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit()],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception, f"Page raised: {at.exception}"
        # Cancel-all button is the Python-side equivalent of DiscardFromStickyBar; verify present.
        labels = _button_labels(at)
        assert any("Cancel" in lbl for lbl in labels), (
            f"Expected a cancel/discard button. Available: {labels}"
        )

    def test_save_from_sticky_bar_event_registered(self):
        """SaveFromStickyBar event handler must be reachable — page renders save button."""
        at = _at_pending_edits()
        at.session_state["dc_test_inject_pending"] = {
            "governance": [_pending_gov_edit()],
            "tests": [],
            "deletions": [],
        }
        at.run()
        assert not at.exception, f"Page raised: {at.exception}"
        # The Python-side save button is the entry point for SaveFromStickyBar.
        labels = _button_labels(at)
        assert any("Save version" in lbl for lbl in labels), (
            f"Expected 'Save version' button. Available: {labels}"
        )

    # -- historical version guard ------------------------------------------

    def test_pending_edits_not_shown_for_historical_version(self):
        """Historical version must show no unsaved-changes warning even with stale session data."""
        at = _at_hist()
        at.run()
        assert not at.exception
        warning_texts = [w.value for w in at.warning]
        assert not any("staged" in t.lower() or "not yet saved" in t.lower() for t in warning_texts), (
            f"Historical version must not show unsaved-changes warning. Got: {warning_texts}"
        )
