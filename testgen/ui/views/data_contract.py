"""
Data Contract UI view — ODCS v3.1.0

Health dashboard · Coverage matrix · Gap analysis · Terms detail with inline editing.

Pure logic lives in data_contract_props.py / data_contract_yaml.py.
DB access lives in testgen/ui/queries/data_contract_queries.py.
Dialog functions live in testgen/ui/views/dialogs/data_contract_dialogs.py.
"""
from __future__ import annotations

import logging
import typing

_log = logging.getLogger(__name__)

import streamlit as st
import yaml

from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite
from testgen.commands.contract_staleness import (
    StaleDiff,
    TermDiffResult,
    compute_staleness_diff,
    compute_term_diff,
)
from testgen.commands.contract_versions import (
    has_any_version,
    list_contract_versions,
    load_contract_version,
    mark_contract_not_stale,
)
from testgen.commands.odcs_contract import ContractDiff as OdcsContractDiff
from testgen.commands.odcs_contract import get_updated_yaml, run_import_contract
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.queries.data_contract_queries import (
    _dismiss_hygiene_anomaly,
    _fetch_anomalies,
    _fetch_governance_data,
    _fetch_last_run_dates,
    _fetch_suite_scope,
    _fetch_test_statuses,
    _lookup_column_id,
)
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session
from testgen.ui.views.data_contract_props import (
    _build_contract_props,
    _is_covered,
    _quality_counts,
)
from testgen.ui.views.data_contract_yaml import (
    _apply_pending_test_edit,
    _pending_edit_count,
)
from testgen.ui.views.dialogs.data_contract_dialogs import (
    _delete_version_dialog,
    _edit_rule_dialog,
    _governance_edit_dialog,
    _monitor_term_dialog,
    _regenerate_dialog,
    _review_changes_panel,
    _save_version_dialog,
    _suite_picker_dialog,
    _term_edit_dialog,
    _term_read_dialog,
    _test_term_dialog,
    _update_version_dialog,
    cancel_all_changes_dialog,
)

PAGE_TITLE = "Data Contract"
PAGE_ICON = "contract"


def _get_snapshot_test_count(snapshot_suite_id: str) -> int:
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"SELECT COUNT(*) AS cnt FROM {schema}.test_definitions WHERE test_suite_id = CAST(:sid AS uuid)",
        params={"sid": snapshot_suite_id},
    )
    return int(rows[0]["cnt"]) if rows else 0


def _format_pending_labels(pending: dict) -> list[str]:
    labels: list[str] = []
    for e in pending.get("governance", []):
        col = e.get("col", "?")
        if e.get("value") is None:
            labels.append(f"deleted {col}")
        else:
            labels.append(f"edited {col}.{e.get('field', '')}")
    for e in pending.get("tests", []):
        if e.get("_removed"):
            col_hint = e.get("_col") or e.get("rule_id", "?")[:8]
            labels.append(f"deleted {col_hint} test")
        else:
            col_hint = e.get("col") or e.get("rule_id", "?")[:8]
            labels.append(f"edited {col_hint} rule")
    for e in pending.get("deletions", []):
        labels.append(f"deleted {e.get('table', '')}.{e.get('col', '')} {e.get('name', '')}")
    return labels


# ---------------------------------------------------------------------------
# Health dashboard
# ---------------------------------------------------------------------------

def _render_health_dashboard(
    doc: dict,
    anomalies: list[dict],
    table_group_id: str,
    is_latest: bool = True,
    test_statuses: dict[str, str] | None = None,
) -> None:
    schema = doc.get("schema") or []
    quality = list(doc.get("quality") or [])

    # Inject live test statuses so counts reflect the latest run, not the cached YAML.
    # Accept pre-fetched statuses to avoid a second DB round-trip when render() already fetched them.
    live_statuses = test_statuses if test_statuses is not None else _fetch_test_statuses(table_group_id)
    if live_statuses:
        for rule in quality:
            rule_id = rule.get("id", "")
            if rule_id in live_statuses:
                rule.setdefault("lastResult", {})["status"] = live_statuses[rule_id]

    all_props = [(t.get("name", ""), p) for t in schema for p in (t.get("properties") or [])]
    n_cols = len(all_props)

    rules_by_element: dict[str, list[dict]] = {}
    for rule in quality:
        rules_by_element.setdefault(rule.get("element", ""), []).append(rule)

    covered = sum(
        1 for tbl, prop in all_props
        if _is_covered(
            prop,
            rules_by_element.get(f"{tbl}.{prop.get('name', '')}", [])
            + rules_by_element.get(prop.get("name", ""), []),
        )
    )
    coverage_pct = int(100 * covered / n_cols) if n_cols else 0

    counts = _quality_counts(quality)
    n_tests = len(quality)
    passing = counts.get("passing", 0)
    warning_ct = counts.get("warning", 0)
    failing = counts.get("failing", 0) + counts.get("error", 0)
    not_run = counts.get("not run", 0)

    definite = sum(1 for a in anomalies if a.get("issue_likelihood") == "Definite")
    likely = sum(1 for a in anomalies if a.get("issue_likelihood") == "Likely")
    possible = sum(1 for a in anomalies if a.get("issue_likelihood") == "Possible")

    filter_key = f"dc_filter:{table_group_id}"
    active = st.session_state.get(filter_key)

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)

        with c1:
            bar_fill = int(coverage_pct / 10)
            bar = "█" * bar_fill + "░" * (10 - bar_fill)
            color = "green" if coverage_pct >= 80 else "orange" if coverage_pct >= 50 else "red"
            st.markdown(f"**Coverage** &nbsp; :{color}[{bar}] {coverage_pct}%")
            st.caption(f"{covered} of {n_cols} columns have ≥1 non-schema term")
            uncovered = n_cols - covered
            if uncovered > 0:
                label = "✕ Clear filter" if active == "uncovered" else f"View {uncovered} uncovered →"
                if st.button(label, key=f"dc_filter_uncov:{table_group_id}", type="tertiary"):
                    st.session_state[filter_key] = None if active == "uncovered" else "uncovered"
                    safe_rerun()

        with c2:
            if n_tests == 0:
                st.markdown("**Test Health** &nbsp; ⏳ no tests defined")
                st.caption("Add quality tests to enforce terms")
            else:
                parts = []
                if passing:
                    parts.append(f"✅ {passing}")
                if warning_ct:
                    parts.append(f"⚠️ {warning_ct}")
                if failing:
                    parts.append(f"❌ {failing}")
                if not_run:
                    parts.append(f"⏳ {not_run}")
                st.markdown(f"**Test Health** &nbsp; {'  '.join(parts)}")
                st.caption(f"{n_tests} tests total")
                if failing > 0:
                    label = "✕ Clear filter" if active == "failing" else f"View {failing} failure(s) →"
                    if st.button(label, key=f"dc_filter_fail:{table_group_id}", type="tertiary"):
                        st.session_state[filter_key] = None if active == "failing" else "failing"
                        safe_rerun()

        with c3:
            if not anomalies:
                st.markdown("**Hygiene** &nbsp; ✅ clean")
                st.caption("No anomalies from latest profiling run")
            else:
                parts = []
                if definite:
                    parts.append(f"❌ {definite}")
                if likely:
                    parts.append(f"⚠️ {likely}")
                if possible:
                    parts.append(f"🔵 {possible}")
                st.markdown(f"**Hygiene** &nbsp; {'  '.join(parts)}")
                st.caption(f"{len(anomalies)} findings from latest profile run")
                label = "✕ Clear filter" if active == "anomalies" else f"View {len(anomalies)} anomalies →"
                if st.button(label, key=f"dc_filter_anom:{table_group_id}", type="tertiary"):
                    st.session_state[filter_key] = None if active == "anomalies" else "anomalies"
                    safe_rerun()
            if not is_latest:
                st.caption("⚠ Anomalies are always current — not from this snapshot.")

    if active:
        st.info(
            f"Filter active: **{active}** — showing only matching columns. "
            "Click the button above to clear.",
            icon=":material/filter_alt:",
        )


# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------

@with_database_session
def _check_contract_prerequisites(table_group_id: str) -> dict:
    """Check whether the prerequisites for generating a first contract are met."""
    schema = get_tg_schema()

    profiling_rows = fetch_dict_from_db(
        f"SELECT MAX(profiling_starttime) AS last_run FROM {schema}.profiling_runs "
        f"WHERE table_groups_id = :tg_id AND status = 'Complete'",
        params={"tg_id": table_group_id},
    )
    last_profiling = dict(profiling_rows[0]).get("last_run") if profiling_rows else None

    suite_rows = fetch_dict_from_db(
        f"SELECT COUNT(*) AS ct FROM {schema}.test_suites ts "
        f"JOIN {schema}.test_definitions td ON td.test_suite_id = ts.id "
        f"WHERE ts.table_groups_id = :tg_id AND ts.is_monitor IS NOT TRUE "
        f"AND td.test_active = 'Y'",
        params={"tg_id": table_group_id},
    )
    suite_ct = int(dict(suite_rows[0]).get("ct", 0)) if suite_rows else 0

    meta_rows = fetch_dict_from_db(
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN description IS NOT NULL OR pii_flag IS NOT NULL THEN 1 ELSE 0 END) AS with_meta "
        f"FROM {schema}.data_column_chars WHERE table_groups_id = :tg_id",
        params={"tg_id": table_group_id},
    )
    if meta_rows:
        mr = dict(meta_rows[0])
        total = int(mr.get("total") or 0)
        with_meta = int(mr.get("with_meta") or 0)
        meta_pct = int(100 * with_meta / total) if total else 0
    else:
        meta_pct = 0

    return {
        "has_profiling": last_profiling is not None,
        "last_profiling": last_profiling,
        "has_suites": suite_ct > 0,
        "suite_ct": suite_ct,
        "meta_pct": meta_pct,
    }


# ---------------------------------------------------------------------------
# Staleness banner
# ---------------------------------------------------------------------------

def _render_staleness_banner(
    version_record: dict,
    stale_diff: StaleDiff,
    table_group_id: str,
    dismissed_key: str,
) -> None:
    """Render the staleness warning banner. Returns silently if not stale or dismissed."""
    if st.session_state.get(dismissed_key):
        return
    parts = stale_diff.summary_parts()
    saved_at = version_record.get("saved_at")
    saved_str = saved_at.strftime("%b %d, %Y") if saved_at else "unknown date"
    version_num = version_record.get("version", "?")
    st.warning(
        f"Contract version {version_num} was saved on {saved_str}. "
        f"Since then: {', '.join(parts)}.",
        icon="⚠️",
    )
    col1, col2 = st.columns([1, 8])
    if col1.button("Review Changes", key=f"dc_review_changes:{table_group_id}"):
        st.session_state[f"dc_show_review:{table_group_id}"] = True
        safe_rerun()
    if col2.button("Dismiss", key=f"dc_dismiss_stale:{table_group_id}"):
        st.session_state[dismissed_key] = True
        safe_rerun()


# ---------------------------------------------------------------------------
# First-time flow renderer
# ---------------------------------------------------------------------------

def _render_first_time_flow(table_group_id: str) -> None:
    """Render the guided first-contract generation wizard."""
    from testgen.ui.queries.data_contract_queries import _capture_yaml

    prereqs = _check_contract_prerequisites(table_group_id)
    preview_key = f"dc_preview:{table_group_id}"
    in_preview = preview_key in st.session_state

    st.markdown("### No contract saved yet")
    st.caption("Generate your first contract by completing the steps below.")

    if not in_preview:
        prof_ok = prereqs["has_profiling"]
        suite_ok = prereqs["has_suites"]

        st.markdown("**Before generating a contract we need:**")
        if prof_ok:
            last = prereqs["last_profiling"]
            last_str = last.strftime("%b %d, %Y") if last else ""
            st.success(f"✅  Profiling run complete   ({last_str})", icon=None)
        else:
            st.error("❌  No profiling run found — run profiling first.", icon=None)

        if suite_ok:
            st.success(f"✅  Test suites present   ({prereqs['suite_ct']} active tests, monitor suites excluded)", icon=None)
        else:
            st.error("❌  No non-monitor test suites with active tests found.", icon=None)

        meta_pct = prereqs["meta_pct"]
        if meta_pct < 25:
            st.warning(
                f"⚠️  Column metadata sparse ({meta_pct}% of columns have descriptions or PII flags). "
                "You can add these now or later — they improve contract coverage.",
                icon=None,
            )

        all_ok = prof_ok and suite_ok
        if st.button("Generate Contract Preview →", disabled=not all_ok, type="primary"):
            import io
            buf = io.StringIO()
            _capture_yaml(table_group_id, buf)
            st.session_state[preview_key] = buf.getvalue()
            safe_rerun()
    else:
        preview_yaml = st.session_state[preview_key]
        try:
            _parsed = yaml.safe_load(preview_yaml)
            preview_doc = _parsed if isinstance(_parsed, dict) else {}
        except yaml.YAMLError:
            preview_doc = {}

        st.info("📋 Contract preview — not yet saved", icon=None)
        anomalies: list[dict] = []
        _render_health_dashboard(preview_doc, anomalies, table_group_id)

        col1, col2 = st.columns([1, 3])
        if col1.button("← Back"):
            st.session_state.pop(preview_key, None)
            safe_rerun()

        if col2.button("Save as Version 0", type="primary"):
            _save_version_dialog(table_group_id, {}, preview_yaml, None)

    st.divider()
    with st.expander("Or import from YAML", expanded=False):
        st.caption("Upload an existing ODCS v3.1.0 YAML file to create a new contract version.")
        uploaded = st.file_uploader(
            "Upload ODCS YAML",
            type=["yaml", "yml"],
            key=f"dc_yaml_upload:{table_group_id}",
        )
        if uploaded is not None:
            from testgen.commands.create_data_contract import create_contract_from_yaml, validate_odcs_header
            raw = uploaded.read().decode("utf-8")
            errors = validate_odcs_header(raw)
            if errors:
                for err in errors:
                    st.error(err)
            else:
                import_label = st.text_input("Version label (optional)", key=f"dc_yaml_upload_label:{table_group_id}")
                if st.button("Save as Version 0", key=f"dc_yaml_upload_save:{table_group_id}", type="primary"):
                    try:
                        create_contract_from_yaml(table_group_id, raw, import_label or None)
                        st.success("Contract version 0 saved.")
                        safe_rerun()
                    except ValueError as exc:
                        st.error(str(exc))


# ---------------------------------------------------------------------------
# Shared term-deletion helper
# ---------------------------------------------------------------------------

def _apply_term_deletions(
    terms: list[dict],
    yaml_key: str,
    pending_key: str,
    table_group_id: str,
    snapshot_suite_id: str | None = None,
) -> None:
    """Apply term deletions to YAML in session state and sync to snapshot suite.

    Shared core of both the BulkDeleteTermsClicked event handler and the
    individual modal "Delete term from contract" buttons.
    """
    current_yaml = st.session_state.get(yaml_key, "")
    try:
        parsed = yaml.safe_load(current_yaml)
        if not isinstance(parsed, dict):
            return
        doc = parsed
    except yaml.YAMLError:
        return

    # ── 1. Delete quality rules (test / monitor terms with rule_id) ──
    rule_ids_to_delete: set[str] = {
        t["rule_id"] for t in terms if t.get("rule_id")
    }
    element_by_id: dict[str, str] = {
        str(q.get("id", "")): str(q.get("element", ""))
        for q in (doc.get("quality") or [])
    }
    if rule_ids_to_delete:
        doc["quality"] = [
            q for q in (doc.get("quality") or [])
            if str(q.get("id", "")) not in rule_ids_to_delete
        ]

    # ── 2. Delete schema terms (DDL / profiling / governance) ──────
    schema_removals: dict[tuple[str, str], list[dict]] = {}
    for t in terms:
        if t.get("rule_id"):
            continue  # handled above
        key = (t.get("table", ""), t.get("col", ""))
        schema_removals.setdefault(key, []).append(t)

    if schema_removals:
        _SCHEMA_FIELD_MAP: dict[tuple[str, str], str] = {
            ("ddl",        "Data Type"):              "physicalType",
            ("ddl",        "Not Null"):               "required",
            ("ddl",        "Primary Key"):            "_customProperties.testgen.primaryKey",
            ("profiling",  "Min Value"):              "_customProperties.testgen.minimum",
            ("profiling",  "Max Value"):              "_customProperties.testgen.maximum",
            ("profiling",  "Min Length"):             "_customProperties.testgen.minLength",
            ("profiling",  "Max Length"):             "_customProperties.testgen.maxLength",
            ("profiling",  "Format"):                 "_customProperties.testgen.format",
            ("profiling",  "Logical Type"):           "logicalType",
            ("governance", "Critical Data Element"):  "criticalDataElement",
            ("governance", "Description"):            "description",
        }
        for schema_entry in (doc.get("schema") or []):
            tbl_name = schema_entry.get("name", "")
            for prop in (schema_entry.get("properties") or []):
                col_name = prop.get("name", "")
                removals = schema_removals.get((tbl_name, col_name), [])
                for rem in removals:
                    field = _SCHEMA_FIELD_MAP.get((rem.get("source", ""), rem.get("name", "")))
                    if not field:
                        continue
                    if field.startswith("_customProperties."):
                        cp_key = field[len("_customProperties."):]
                        existing = prop.get("customProperties") or []
                        updated_cp = [cp for cp in existing if cp.get("property") != cp_key]
                        if updated_cp:
                            prop["customProperties"] = updated_cp
                        else:
                            prop.pop("customProperties", None)
                    else:
                        prop.pop(field, None)

    updated_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # ── 3. Queue governance + schema deletions as pending edits ────
    pending = st.session_state.get(pending_key, {})
    for t in terms:
        if t.get("rule_id"):
            continue
        src = t.get("source", "")
        if src == "governance":
            snapshot = {"name": t.get("name", ""), "source": "governance", "verif": "declared"}
            pending.setdefault("governance", []).append({
                "field":    t.get("name", ""),
                "value":    None,
                "table":    t.get("table", ""),
                "col":      t.get("col", ""),
                "snapshot": snapshot,
            })
        elif src in ("ddl", "profiling"):
            # Track schema field removals so pending_ct > 0 and save routes to update-in-place
            pending.setdefault("deletions", []).append({
                "source": src,
                "name":   t.get("name", ""),
                "table":  t.get("table", ""),
                "col":    t.get("col", ""),
            })

    # ── 4. Dismiss hygiene anomalies ───────────────────────────────
    for t in terms:
        if (
            t.get("source") == "profiling"
            and t.get("name") == "Hygiene"
            and not t.get("rule_id")
            and t.get("anomaly_type")
        ):
            try:
                _dismiss_hygiene_anomaly(
                    table_group_id=table_group_id,
                    table_name=t.get("table", ""),
                    col_name=t.get("col", ""),
                    anomaly_type=t.get("anomaly_type", ""),
                )
            except Exception:
                _log.exception(
                    "_apply_term_deletions: hygiene anomaly dismiss failed for %s/%s",
                    t.get("table"), t.get("col"),
                )

    st.session_state[yaml_key] = updated_yaml

    # ── 5. Update pending edits for rule deletions ─────────────────
    for rid in rule_ids_to_delete:
        element = element_by_id.get(rid, "")
        parts = element.split(".", 1)
        tbl = parts[0] if parts else ""
        col = parts[1] if len(parts) > 1 else ""
        pending = _apply_pending_test_edit(
            pending,
            rid,
            {
                "_removed": True,
                "_table": tbl,
                "_col": col,
                "_snapshot": {"name": element or rid[:8], "source": "test", "verif": "tested"},
            },
        )
    st.session_state[pending_key] = pending

    # ── 6. Sync deletions immediately to snapshot suite ────────────
    if snapshot_suite_id and rule_ids_to_delete:
        try:
            sync_import_to_snapshot_suite(snapshot_suite_id, [], [], list(rule_ids_to_delete))
        except Exception:
            _log.exception(
                "_apply_term_deletions: failed to sync to snapshot suite %s", snapshot_suite_id
            )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class DataContractPage(Page):
    path = "data-contract"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "table_group_id" in st.query_params,
    ]
    menu_item = None

    def render(self, table_group_id: str, **_kwargs) -> None:
        from testgen.ui.components.widgets.testgen_component import testgen_component

        table_group = TableGroup.get_minimal(table_group_id)
        if not table_group:
            st.error("Table group not found.")
            return

        tg_name = getattr(table_group, "table_groups_name", "") or ""
        testgen.page_header(f"{PAGE_TITLE}: {tg_name}" if tg_name else PAGE_TITLE, "connect-your-database/manage-table-groups/")

        # ── First-time flow ───────────────────────────────────────────────────
        if not has_any_version(table_group_id):
            _render_first_time_flow(table_group_id)
            return

        # ── Session state keys ────────────────────────────────────────────────
        yaml_key        = f"dc_yaml:{table_group_id}"
        version_key     = f"dc_version:{table_group_id}"
        pending_key     = f"dc_pending:{table_group_id}"
        anomaly_key     = f"dc_anomalies:{table_group_id}"
        import_key      = f"dc_import_result:{table_group_id}"
        run_dates_key   = f"dc_run_dates:{table_group_id}"
        gov_key         = f"dc_gov:{table_group_id}"
        term_diff_key      = f"dc_term_diff:{table_group_id}"
        suite_scope_key    = f"dc_suite_scope:{table_group_id}"
        staleness_diff_key = f"dc_staleness_diff:{table_group_id}"

        # ── Version picker ────────────────────────────────────────────────────
        versions = list_contract_versions(table_group_id)
        requested_version: int | None = None
        raw_ver = st.query_params.get("version")
        if raw_ver is not None:
            try:
                requested_version = int(raw_ver)
            except ValueError:
                requested_version = None

        if version_key not in st.session_state or (
            requested_version is not None
            and st.session_state.get(version_key, {}).get("version") != requested_version
        ):
            record = load_contract_version(table_group_id, requested_version)
            if record is None:
                record = load_contract_version(table_group_id)
            st.session_state[version_key] = record
            st.session_state.pop(yaml_key, None)

        version_record: dict = st.session_state[version_key]
        is_latest = (version_record["version"] == versions[0]["version"]) if versions else True
        dismissed_key = f"dc_stale_dismissed:{table_group_id}:v{version_record['version']}"

        _snapshot_suite_id: str | None = version_record.get("snapshot_suite_id")

        if yaml_key not in st.session_state:
            base_yaml: str = version_record["contract_yaml"]
            if _snapshot_suite_id:
                from testgen.commands.export_data_contract import rebuild_quality_from_suite
                base_yaml = rebuild_quality_from_suite(base_yaml, _snapshot_suite_id)
            st.session_state[yaml_key] = base_yaml

        contract_yaml: str = st.session_state[yaml_key]
        pending: dict = st.session_state.get(pending_key, {})

        doc: dict = {}
        if contract_yaml:
            try:
                parsed = yaml.safe_load(contract_yaml)
                doc = parsed if isinstance(parsed, dict) else {}
            except yaml.YAMLError:
                doc = {}
        # Ensure ODCS v3.1.0 envelope fields are always present at top of YAML
        if "apiVersion" not in doc or "kind" not in doc:
            doc = {"apiVersion": "v3.1.0", "kind": "DataContract", **doc}
            contract_yaml = yaml.dump(doc, allow_unicode=True, sort_keys=False)

        # ── Staleness check (latest version only) ─────────────────────────────
        stale_diff: StaleDiff | None = None
        if is_latest:
            tg_full = TableGroup.get(table_group_id)
            is_stale = bool(getattr(tg_full, "contract_stale", False))
            if is_stale and not st.session_state.get(dismissed_key):
                if staleness_diff_key not in st.session_state:
                    computed = compute_staleness_diff(
                        table_group_id,
                        version_record["contract_yaml"],
                        snapshot_suite_id=version_record.get("snapshot_suite_id"),
                    )
                    if computed.is_empty:
                        mark_contract_not_stale(table_group_id)
                    else:
                        st.session_state[staleness_diff_key] = computed
                stale_diff = st.session_state.get(staleness_diff_key)

        # ── Toolbar: Refresh · [version picker] · Save ────────────────────────
        pending_ct = _pending_edit_count(pending)
        if pending_ct > 0:
            pending_items = (
                [f"{e['table']}.{e['col']} {e['field']}" for e in pending.get("governance", [])]
                + [f"test {e['rule_id'][:8]}…" for e in pending.get("tests", [])]
                + [f"deleted {e.get('table', '')}.{e.get('col', '')} {e.get('name', '')}" for e in pending.get("deletions", [])]
            )
            save_tip = f"{pending_ct} unsaved change(s): " + "; ".join(pending_items[:3])
        else:
            save_tip = "Snapshot the current contract state as a new version"

        if len(versions) > 1:
            version_labels = [
                (
                    f"Version {v['version']}  ·  {v['saved_at'].strftime('%b %d %Y %H:%M') if v.get('saved_at') else ''}  "
                    f"{'— ' + v['label'] if v.get('label') else ''}  (latest)"
                    if i == 0 else
                    f"Version {v['version']}  ·  {v['saved_at'].strftime('%b %d %Y %H:%M') if v.get('saved_at') else ''}  "
                    f"{'— ' + v['label'] if v.get('label') else ''}"
                )
                for i, v in enumerate(versions)
            ]
            current_idx = next(
                (i for i, v in enumerate(versions) if v["version"] == version_record["version"]), 0
            )
            picker_col, refresh_col, regen_col, save_col = st.columns([4, 1, 1, 1])
            with picker_col:
                chosen_idx = st.selectbox(
                    "Contract version",
                    options=range(len(versions)),
                    index=current_idx,
                    format_func=lambda i: version_labels[i],
                    label_visibility="collapsed",
                )
            if chosen_idx != current_idx:
                chosen_ver = versions[chosen_idx]["version"]
                if pending and _pending_edit_count(pending) > 0:
                    st.warning("You have unsaved changes. Switch versions? Changes will be lost.")
                    c1, c2 = st.columns(2)
                    if c1.button("Switch anyway"):
                        st.session_state.pop(pending_key, None)
                        st.session_state.pop(yaml_key, None)
                        st.session_state.pop(version_key, None)
                        st.query_params["version"] = str(chosen_ver)
                        safe_rerun()
                    if c2.button("Stay"):
                        safe_rerun()
                else:
                    st.session_state.pop(yaml_key, None)
                    st.session_state.pop(version_key, None)
                    st.query_params["version"] = str(chosen_ver)
                    safe_rerun()
        else:
            _, refresh_col, regen_col, save_col = st.columns([4, 1, 1, 1])

        with refresh_col:
            if st.button("↺ Refresh", key=f"dc_refresh_btn:{table_group_id}", use_container_width=True,
                         help="Reload the saved data contract from the database"):
                st.session_state.pop(yaml_key, None)
                st.session_state.pop(anomaly_key, None)
                st.session_state.pop(version_key, None)
                st.session_state.pop(pending_key, None)
                st.session_state.pop(run_dates_key, None)
                st.session_state.pop(gov_key, None)
                st.session_state.pop(term_diff_key, None)
                st.session_state.pop(suite_scope_key, None)
                st.session_state.pop(staleness_diff_key, None)
                safe_rerun()
        if is_latest:
            with regen_col:
                if st.button("⟳ Regenerate", key=f"dc_regen_btn:{table_group_id}", use_container_width=True,
                             help="Re-export from the current database state and save as a new version"):
                    _regenerate_dialog(table_group_id, version_record["version"], pending_ct)
            with save_col:
                if pending_ct > 0:
                    save_label = f"Save ● ({pending_ct})"
                    if st.button(save_label, type="secondary", help=save_tip, key=f"dc_save_btn:{table_group_id}", use_container_width=True):
                        _update_version_dialog(table_group_id, pending, contract_yaml, version_record["version"])
                else:
                    if st.button("Save version", type="secondary", help=save_tip, key=f"dc_save_btn:{table_group_id}", use_container_width=True):
                        _save_version_dialog(table_group_id, pending, contract_yaml, version_record["version"])

        # ── Unsaved changes banner ────────────────────────────────────────────
        if is_latest and pending_ct > 0:
            labels = _format_pending_labels(pending)
            shown = labels[:3]
            remainder = len(labels) - 3
            summary = ", ".join(shown) + (f" and {remainder} more" if remainder > 0 else "")
            noun = "change" if pending_ct == 1 else "changes"
            warn_col, cancel_col = st.columns([7, 1])
            with warn_col:
                st.warning(f"{pending_ct} unsaved {noun}: {summary}", icon="⚠️")
            with cancel_col:
                st.markdown("<div style='margin-top:0.4rem'></div>", unsafe_allow_html=True)
                if st.button("✕ Cancel all", key=f"dc_cancel_all:{table_group_id}", type="tertiary", use_container_width=True):
                    cancel_all_changes_dialog(table_group_id, pending_ct, version_record["contract_yaml"])

        # ── Historic read-only banner ─────────────────────────────────────────
        if not is_latest:
            saved_at = version_record.get("saved_at")
            saved_str = saved_at.strftime("%b %d, %Y at %H:%M") if saved_at else ""
            label_str = f' "{version_record["label"]}"' if version_record.get("label") else ""
            st.info(
                f"📋 Viewing version {version_record['version']}{label_str} — saved {saved_str}. "
                f"This is a read-only snapshot. The latest is version {versions[0]['version']}.",
                icon=None,
            )

        # ── Staleness banner (latest only) ────────────────────────────────────
        if stale_diff and is_latest:
            _render_staleness_banner(version_record, stale_diff, table_group_id, dismissed_key)

        # ── Review changes panel ──────────────────────────────────────────────
        if st.session_state.pop(f"dc_show_review:{table_group_id}", False) and stale_diff:
            _review_changes_panel(stale_diff, table_group_id, version_record, contract_yaml)

        # ── Anomalies ─────────────────────────────────────────────────────────
        if anomaly_key not in st.session_state:
            st.session_state[anomaly_key] = _fetch_anomalies(table_group_id)
        anomalies: list[dict] = st.session_state[anomaly_key]

        if run_dates_key not in st.session_state:
            st.session_state[run_dates_key] = _fetch_last_run_dates(
                table_group_id, snapshot_suite_id=_snapshot_suite_id
            )
        run_dates = st.session_state[run_dates_key]

        if suite_scope_key not in st.session_state:
            st.session_state[suite_scope_key] = _fetch_suite_scope(
                table_group_id, snapshot_suite_id=_snapshot_suite_id
            )
        suite_scope   = st.session_state[suite_scope_key]
        test_statuses = _fetch_test_statuses(table_group_id, snapshot_suite_id=_snapshot_suite_id)  # always fresh per design

        if gov_key not in st.session_state:
            st.session_state[gov_key] = _fetch_governance_data(table_group_id)
        gov_by_col = st.session_state[gov_key]
        props = _build_contract_props(
            table_group, doc, anomalies, contract_yaml,
            run_dates, suite_scope, test_statuses, gov_by_col,
        )

        # Inject pending deletions as grayed-out ghost chips in the terms grid
        if pending:
            deletions_by_col: dict[tuple[str, str], list[dict]] = {}
            for e in pending.get("governance", []):
                if e.get("value") is None and "snapshot" in e:
                    deletions_by_col.setdefault((e["table"], e["col"]), []).append(e["snapshot"])
            for e in pending.get("tests", []):
                if e.get("_removed") and "_snapshot" in e:
                    deletions_by_col.setdefault((e["_table"], e["_col"]), []).append(e["_snapshot"])
            if deletions_by_col:
                for tbl in props.get("tables", []):
                    for col in tbl.get("columns", []):
                        ghosts = deletions_by_col.get((tbl["name"], col["name"]))
                        if ghosts:
                            col["pending_delete_terms"] = ghosts

        props["version_info"] = {
            "version":            version_record["version"],
            "saved_at":           version_record["saved_at"].isoformat() if version_record.get("saved_at") else None,
            "label":              version_record.get("label"),
            "is_latest":          is_latest,
            "is_stale":           stale_diff is not None,
            "pending_count":      pending_ct,
            "snapshot_suite_id":  version_record.get("snapshot_suite_id"),
            "num_versions":       len(versions),
            "tests_count":        _get_snapshot_test_count(_snapshot_suite_id) if _snapshot_suite_id else None,
        }

        # ── Term diff (Card 2 / Card 3 / Differences tab / Compliance tab) ──────
        if term_diff_key not in st.session_state:
            st.session_state[term_diff_key] = compute_term_diff(
                table_group_id, contract_yaml, anomalies, snapshot_suite_id=_snapshot_suite_id
            )
        term_diff: TermDiffResult = st.session_state[term_diff_key]
        same_ct    = sum(1 for e in term_diff.entries if e.status == "same")
        changed_ct = sum(1 for e in term_diff.entries if e.status == "changed")
        deleted_ct = sum(1 for e in term_diff.entries if e.status == "deleted")
        new_ct     = sum(1 for e in term_diff.entries if e.status == "new")

        # Scope to saved-YAML elements only (same/changed/deleted) so hygiene_entries
        # matches the tg_hygiene_* counts computed in compute_term_diff.
        contract_elements: set[str] = {
            e.element for e in term_diff.entries
            if e.element and e.status != "new"
        }
        hygiene_entries = [
            {
                "element": (
                    f"{a['table_name']}.{a['column_name']}"
                    if a.get("column_name") else a["table_name"]
                ),
                "anomaly_type":     a.get("anomaly_type", ""),
                "issue_likelihood": a.get("issue_likelihood", ""),
            }
            for a in anomalies
            if (
                f"{a['table_name']}.{a['column_name']}"
                if a.get("column_name") else a["table_name"]
            ) in contract_elements
        ]

        props["term_diff"] = {
            "saved_count":   term_diff.saved_count,
            "current_count": term_diff.current_count,
            "same_count":    same_ct,
            "changed_count": changed_ct,
            "deleted_count": deleted_ct,
            "new_count":     new_ct,
            "entries": [
                {
                    "element":     e.element,
                    "test_type":   e.test_type,
                    "status":      e.status,
                    "detail":      e.detail,
                    "last_result": e.last_result,
                    "is_monitor":  e.is_monitor,
                }
                for e in term_diff.entries
            ],
            "hygiene_entries": hygiene_entries,
            "tg_monitor_passed":  term_diff.tg_monitor_passed,
            "tg_monitor_failed":  term_diff.tg_monitor_failed,
            "tg_monitor_warning": term_diff.tg_monitor_warning,
            "tg_monitor_error":   term_diff.tg_monitor_error,
            "tg_monitor_not_run": term_diff.tg_monitor_not_run,
            "tg_test_passed":     term_diff.tg_test_passed,
            "tg_test_failed":     term_diff.tg_test_failed,
            "tg_test_warning":    term_diff.tg_test_warning,
            "tg_test_error":      term_diff.tg_test_error,
            "tg_test_not_run":    term_diff.tg_test_not_run,
            "tg_hygiene_definite": term_diff.tg_hygiene_definite,
            "tg_hygiene_likely":   term_diff.tg_hygiene_likely,
            "tg_hygiene_possible": term_diff.tg_hygiene_possible,
        }

        # ── Select-term-from-modal handoff ────────────────────────────────────
        # When a dialog's "Delete term from contract" button is clicked, it stores
        # the term key here instead of immediately deleting.  We pass it to JS so
        # the term card becomes selected in the multi-select UI.
        _select_term_key = st.session_state.pop(f"dc_select_term:{table_group_id}", "") or ""
        props["select_term_key"] = _select_term_key

        # ── Event handlers ────────────────────────────────────────────────────
        def on_suite_picker(_payload: object) -> None:
            suite_runs = props.get("health", {}).get("suite_runs", [])
            if suite_runs:
                _project_code = getattr(table_group, "project_code", "")
                _suite_picker_dialog(suite_runs, _project_code, table_group_id)

        def on_term_detail(payload: dict) -> None:
            term       = payload.get("term", {})
            table_name = payload.get("tableName", "")
            col_name   = payload.get("colName", "")
            source = term.get("source", "")
            verif  = term.get("verif", "")
            term_name = term.get("name", "")
            snapshot_suite_id = version_record.get("snapshot_suite_id")
            if not is_latest:
                _term_read_dialog(term, table_name, col_name, table_group_id, yaml_key)
            elif source == "monitor":
                _monitor_term_dialog(term.get("rule", {}), term_name, table_name, col_name)
            elif source == "test":
                rule_id = term.get("rule_id", "")
                if rule_id:
                    from testgen.ui.views.test_definitions import show_test_form_by_id
                    show_test_form_by_id(rule_id)
                else:
                    _project_code = getattr(table_group, "project_code", "")
                    _test_term_dialog(term, table_name, col_name, _project_code, yaml_key, table_group_id)
            elif source == "governance" and verif == "declared":
                _term_edit_dialog(term, table_name, col_name, table_group_id, yaml_key)
            else:
                _term_read_dialog(term, table_name, col_name, table_group_id, yaml_key)

        def on_governance_edit(payload: dict) -> None:
            col_id     = payload.get("columnId", "")
            table_name = payload.get("tableName", "")
            col_name   = payload.get("colName", "")
            if not is_latest:
                return
            if not col_id:
                col_id = _lookup_column_id(table_group_id, table_name, col_name)
            _governance_edit_dialog(col_id, table_name, col_name, table_group_id, yaml_key)

        def on_edit_rule(payload: dict) -> None:
            if not is_latest:
                return
            rule_id = str(payload.get("rule_id", ""))
            rule = next(
                (r for r in (doc.get("quality") or []) if str(r.get("id", "")) == rule_id),
                None,
            )
            if rule:
                _edit_rule_dialog(rule, table_group_id, yaml_key, snapshot_suite_id=version_record.get("snapshot_suite_id"))

        def on_add_test(payload: dict) -> None:
            if not is_latest:
                return
            snapshot_suite_id = version_record.get("snapshot_suite_id")
            if not snapshot_suite_id:
                return
            from sqlalchemy import select

            from testgen.common.models.test_suite import TestSuite
            from testgen.ui.views.test_definitions import add_test_dialog
            _ts = get_current_session().scalars(
                select(TestSuite).where(TestSuite.id == snapshot_suite_id)
            ).first()
            if table_group and _ts:
                add_test_dialog(table_group, _ts, payload.get("tableName", ""), payload.get("colName", ""))

        def on_delete_version(payload: dict) -> None:
            _version_to_delete = payload.get("version")
            if _version_to_delete is None:
                return
            _delete_version_dialog(table_group_id, int(_version_to_delete))

        def on_import_contract(payload: dict) -> None:
            if not is_latest:
                return
            yaml_content = payload.get("payload", "")
            if not yaml_content:
                return
            try:
                diff: OdcsContractDiff = run_import_contract(yaml_content, table_group_id)
                st.session_state[import_key] = {
                    "diff": diff,
                    "original_yaml": yaml_content,
                }
                if not diff.has_errors:
                    # Sync created/updated/deleted tests to snapshot suite if one exists
                    snap_id = version_record.get("snapshot_suite_id")
                    if snap_id:
                        created_ids = list(diff.new_id_by_index.values()) if diff.new_id_by_index else []
                        updated_ids = [str(u["id"]) for u in (diff.test_updates or []) if u.get("id")]
                        deleted_ids = list(diff.orphaned_ids) if diff.orphaned_ids else []
                        if created_ids or updated_ids or deleted_ids:
                            try:
                                sync_import_to_snapshot_suite(snap_id, created_ids, updated_ids, deleted_ids)
                            except Exception:
                                _log.exception("on_import_contract: failed to sync to snapshot suite %s", snap_id)
                    # Bust YAML + anomaly + derived caches so the page reflects the newly created tests
                    st.session_state.pop(yaml_key, None)
                    st.session_state.pop(anomaly_key, None)
                    st.session_state.pop(version_key, None)
                    st.session_state.pop(run_dates_key, None)
                    st.session_state.pop(gov_key, None)
                    st.session_state.pop(term_diff_key, None)
                    st.session_state.pop(suite_scope_key, None)
            except Exception as exc:
                st.session_state[import_key] = {"error": str(exc)}
            safe_rerun()

        def on_bulk_delete_terms(payload: dict) -> None:
            if not is_latest:
                return
            terms: list[dict] = payload.get("terms") or []
            if not terms:
                return
            _apply_term_deletions(
                terms, yaml_key, pending_key, table_group_id,
                snapshot_suite_id=version_record.get("snapshot_suite_id"),
            )
            st.session_state.pop(term_diff_key, None)
            safe_rerun()

        testgen_component(
            "data_contract",
            props=props,
            event_handlers={
                "EditRuleClicked":          on_edit_rule,
                "TermDetailClicked":        on_term_detail,
                "SuitePickerClicked":       on_suite_picker,
                "GovernanceEditClicked":    on_governance_edit,
                "ImportContractClicked":    on_import_contract,
                "BulkDeleteTermsClicked":   on_bulk_delete_terms,
                "AddTestClicked":           on_add_test,
                "DeleteVersionClicked":     on_delete_version,
            },
        )

        # ── Import result banner ──────────────────────────────────────────────
        import_result = st.session_state.pop(import_key, None)
        if import_result:
            if "error" in import_result:
                st.error(f"Import failed: {import_result['error']}", icon="🚫")
            else:
                diff_result: OdcsContractDiff = import_result["diff"]
                if diff_result.has_errors:
                    for err in diff_result.errors:
                        st.error(err, icon="🚫")
                else:
                    created_ct = len(diff_result.test_inserts)
                    updated_ct = len(diff_result.test_updates)
                    parts = []
                    if created_ct:
                        parts.append(f"{created_ct} test(s) created")
                    if updated_ct:
                        parts.append(f"{updated_ct} test(s) updated")
                    st.success("Import complete — " + (", ".join(parts) or "no changes"), icon="✅")
                    for warn in diff_result.warnings:
                        st.warning(warn, icon="⚠️")
                    # Offer updated YAML download if new test IDs were written back
                    if diff_result.new_id_by_index:
                        updated_yaml = get_updated_yaml(
                            import_result["original_yaml"], diff_result.new_id_by_index
                        )
                        # Use a unique key per import so repeated imports don't collide
                        dl_key = f"dc_import_dl:{table_group_id}:{','.join(diff_result.new_id_by_index.values())}"
                        st.download_button(
                            label="⬇ Download YAML with new test IDs",
                            data=updated_yaml,
                            file_name="contract_with_ids.yaml",
                            mime="text/yaml",
                            key=dl_key,
                        )
