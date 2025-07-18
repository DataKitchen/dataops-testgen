from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from testgen.common.models.scores import ScoreCard

import json
import urllib.parse
from typing import Any, TypeVar
from uuid import UUID

import pandas as pd
import streamlit as st

T = TypeVar("T")


def to_int(value: float | int) -> int:
    if pd.notnull(value):
        return int(value)
    return 0


def to_dataframe(
    data: Iterable[Any],
    columns: list[str] | None = None,
) -> pd.DataFrame:
    records = []
    for item in data:
        if hasattr(item, "to_dict") and callable(item.to_dict):
            row = item.to_dict()
        elif hasattr(item, "__dict__"):
            row = item.__dict__
        else:
            row = dict(item)
        records.append(row)
    return pd.DataFrame.from_records(records, columns=columns)


def is_uuid4(value: str) -> bool:
    if isinstance(value, UUID): 
        return True
    
    try:
        uuid = UUID(value, version=4)
    except Exception:
        return False

    return str(uuid) == value


def try_json(value: str | None, default: T | None) -> T:
    try:
        return json.loads(value)
    except:
        return default


# https://github.com/streamlit/streamlit/issues/798#issuecomment-1647759949
def get_base_url() -> str:
    session = st.runtime.get_instance()._session_mgr.list_active_sessions()[0]
    return urllib.parse.urlunparse([session.client.request.protocol, session.client.request.host, "", "", "", ""])


def make_json_safe(value: Any) -> str | bool | int | float | None:
    if isinstance(value, UUID):
        return str(value)
    elif isinstance(value, datetime):
        return int(value.replace(tzinfo=UTC).timestamp())
    elif isinstance(value, Decimal):
        return float(value)
    elif isinstance(value, list):
        return [ make_json_safe(item) for item in value ]
    elif isinstance(value, dict):
        return { key: make_json_safe(value) for key, value in value.items() }
    return value


def chunk_queries(queries: list[str], join_string: str, max_query_length: int) -> list[str]:
    full_query = join_string.join(queries)
    if len(full_query) <= max_query_length:
        return [full_query]

    queries = iter(queries)
    chunked_queries = []
    current_chunk = next(queries)
    for query in queries:
        temp_chunk = join_string.join([current_chunk, query])
        if len(temp_chunk) <= max_query_length:
            current_chunk = temp_chunk
        else:
            chunked_queries.append(current_chunk)
            current_chunk = query
    chunked_queries.append(current_chunk)

    return chunked_queries
    

def score(profiling_score_: float, tests_score_: float) -> float:
    tests_score = _pandas_default(tests_score_, 0.0)
    profiling_score = _pandas_default(profiling_score_, 0.0)
    final_score = profiling_score or tests_score or 0.0
    if profiling_score and tests_score:
        final_score = profiling_score * tests_score
    return final_score


def _pandas_default(value: Any, default: T) -> T:
    if pd.isnull(value):
        return default
    return value


def format_score_card(score_card: ScoreCard | None) -> ScoreCard:
    definition = None
    if score_card:
        definition = score_card.get("definition")

    categories_label = {
        "table_groups_name": "Table Group",
        "data_location": "Data Location",
        "data_source": "Data Source",
        "source_system": "Source System",
        "source_process": "Source Process",
        "business_domain": "Business Domain",
        "stakeholder_group": "Stakeholder Group",
        "transform_level": "Transform Level",
        "aggregation_level": "Aggregation Level",
        "dq_dimension": "Quality Dimension",
        "data_product": "Data Product",
    }
    if not score_card:
        return {
            "id": None,
            "project_code": "",
            "name": "",
            "score": "--" if not definition or definition.total_score else None,
            "cde_score": "--" if not definition or definition.cde_score else None,
            "profiling_score": "--" if not definition or definition.total_score else None,
            "testing_score": "--" if not definition or definition.total_score else None,
            "categories_label": None,
            "categories": [],
            "history": [],
        }

    return {
        "id": str(score_card_id) if (score_card_id := score_card.get("id")) else None,
        "project_code": score_card["project_code"],
        "name": score_card["name"],
        "score": (friendly_score(score_card.get("score")) or "--")
            if not definition or definition.total_score else None,
        "profiling_score": friendly_score(score_card.get("profiling_score"))
            if not definition or definition.total_score else None,
        "testing_score": friendly_score(score_card.get("testing_score"))
            if not definition or definition.total_score else None,
        "cde_score": (friendly_score(score_card.get("cde_score")) or "--")
            if not definition or definition.cde_score else None,
        "categories_label": categories_label[definition.category.value] if definition and definition.category else None,
        "categories": [
            {**category, "score": friendly_score(category["score"])}
            for category in score_card.get("categories", [])
        ],
        "history": [
            {**entry, "score": round(100 * float(entry["score"]), 1), "time": entry["time"].isoformat()}
            for entry in score_card.get("history", [])
            if entry["score"] and not pd.isnull(entry["score"])
        ],
    }


def format_score_card_breakdown(breakdown: list[dict], category: str) -> dict:
    return {
        "columns": [category, "impact", "score", "issue_ct"],
        "items": [{
            **row,
            "table_groups_id": str(row["table_groups_id"]) if row.get("table_groups_id") else None,
            "score": friendly_score(row["score"]),
            "impact": friendly_score_impact(row["impact"]),
            "issue_ct": int(row["issue_ct"]),
        } for row in breakdown],
    }


def format_score_card_issues(issues: list[dict], category: str) -> dict:
    columns = ["type", "status", "detail", "time"]
    if category != "column_name":
        columns.insert(0, "column")
    return {
        "columns": columns,
        "items": [{
            **row,
            "time": int(row["time"]),
        } for row in issues],
    }


def friendly_score(score: float) -> str:
    if not score or pd.isnull(score):
        return None

    score = 100 * score
    if score == 100:
        return "100"
    
    rounded = round(score, 1)
    if rounded == 0:
        return "< 0.1"
    elif rounded == 100:
        return "> 99.9"

    return str(rounded)


def friendly_score_impact(impact: float) -> str:
    if not impact or pd.isnull(impact):
        return "-"

    if impact == 100:
        return "100"
    
    rounded = round(impact, 2)
    if rounded == 0:
        return "< 0.01"
    elif rounded == 100:
        return "> 99.99"

    return str(rounded)
