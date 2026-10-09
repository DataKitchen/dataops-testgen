"""Paged reads of a table group's data catalog for the Data Catalog tree.

A table is shown when it matches the search and filters itself or when any of its columns
does; a column is shown when it matches. Tags are inherited: a column without its own value
takes its table's, and a table without its own takes the table group's.
"""

import typing
from dataclasses import dataclass

import streamlit as st

from testgen.common.data_catalog_service import TAG_FIELDS
from testgen.ui.services.database_service import fetch_all_from_db
from testgen.utils import is_uuid4

CATALOG_PAGE_SIZE = 500

# Table groups have no aggregation level of their own.
_TABLE_GROUP_TAG_FIELDS = [tag for tag in TAG_FIELDS if tag != "aggregation_level"]


@dataclass(frozen=True)
class CatalogFilters:
    search: str = ""
    search_tables: bool = True
    search_columns: bool = True
    critical_data_element: bool = False
    pii_flag: bool = False
    show_excluded: bool = False
    tags: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_dict(cls, data: dict | None) -> "CatalogFilters":
        data = data or {}
        search_tables = bool(data.get("search_tables", True))
        search_columns = bool(data.get("search_columns", True))
        if not search_tables and not search_columns:
            # Searching neither name would match nothing, with no hint why.
            search_tables = search_columns = True
        return cls(
            search=str(data.get("search") or "").strip(),
            search_tables=search_tables,
            search_columns=search_columns,
            critical_data_element=bool(data.get("critical_data_element")),
            pii_flag=bool(data.get("pii_flag")),
            show_excluded=bool(data.get("show_excluded")),
            tags=tuple(
                (tag, str(value)) for tag, value in sorted((data.get("tags") or {}).items())
                if tag in TAG_FIELDS and value is not None
            ),
        )

    def to_dict(self) -> dict:
        return {
            "search": self.search,
            "search_tables": self.search_tables,
            "search_columns": self.search_columns,
            "critical_data_element": self.critical_data_element,
            "pii_flag": self.pii_flag,
            "show_excluded": self.show_excluded,
            "tags": dict(self.tags),
        }


class CatalogPage(typing.TypedDict):
    tables: list[dict]
    columns: list[dict]
    page: int
    page_size: int
    visible_count: int
    total_count: int


def _effective_tag(tag: str, level: typing.Literal["column", "table"]) -> str:
    sources = ["c", "t", "tg"] if level == "column" else ["t", "tg"]
    if tag not in _TABLE_GROUP_TAG_FIELDS:
        sources.remove("tg")
    return f"COALESCE({', '.join(f'{source}.{tag}' for source in sources)})"


def _visibility_ctes(table_group_id: str, filters: CatalogFilters) -> tuple[str, dict]:
    params: dict = {"table_group_id": table_group_id}
    column_conditions: list[str] = []
    table_conditions: list[str] = []

    if filters.search:
        params["search"] = filters.search.lower()
        column_conditions.append("POSITION(:search IN LOWER(c.column_name)) > 0" if filters.search_columns else "FALSE")
        table_conditions.append("POSITION(:search IN LOWER(t.table_name)) > 0" if filters.search_tables else "FALSE")
    if filters.critical_data_element:
        column_conditions.append("COALESCE(c.critical_data_element, t.critical_data_element) IS TRUE")
        table_conditions.append("t.critical_data_element IS TRUE")
    if filters.pii_flag:
        column_conditions.append("NULLIF(c.pii_flag, '') IS NOT NULL")
        table_conditions.append("FALSE")
    if not filters.show_excluded:
        column_conditions.append("c.excluded_data_element IS NOT TRUE")
    for index, (tag, value) in enumerate(filters.tags):
        params[f"tag_{index}"] = value
        column_conditions.append(f"{_effective_tag(tag, 'column')} = :tag_{index}")
        table_conditions.append(f"{_effective_tag(tag, 'table')} = :tag_{index}")

    column_visible = " AND ".join(column_conditions) or "TRUE"
    table_visible = " AND ".join(table_conditions) or "TRUE"
    # catalog_columns is inlined so a page's table filter reaches the column scan. Materialized, every
    # page would first read every column of the table group.
    ctes = f"""
    WITH catalog_columns AS NOT MATERIALIZED (
        SELECT c.table_id, c.column_id, ({column_visible}) AS visible
        FROM data_column_chars c
            INNER JOIN data_table_chars t ON (c.table_id = t.table_id)
            LEFT JOIN table_groups tg ON (c.table_groups_id = tg.id)
        WHERE c.table_groups_id = :table_group_id
    ),
    column_visibility AS (
        SELECT table_id, BOOL_OR(visible) AS any_visible
        FROM catalog_columns
        GROUP BY table_id
    ),
    catalog_tables AS (
        SELECT t.table_id, t.table_name, ({table_visible}) OR cv.any_visible AS visible
        FROM data_table_chars t
            INNER JOIN column_visibility cv ON (t.table_id = cv.table_id)
            LEFT JOIN table_groups tg ON (t.table_groups_id = tg.id)
    )
    """
    return ctes, params


@st.cache_data(show_spinner=False)
def get_catalog_page(table_group_id: str, filters: CatalogFilters, page: int) -> CatalogPage:
    """Fetch one page of a table group's catalog tree.

    :param table_group_id: Table group whose catalog is read.
    :param filters: Search and filters applied to tables and columns.
    :param page: Zero-based page of matching tables, ordered by name.
    :returns: The page's tables, their matching columns, and the counts of matching and of all tables.
    """
    empty: CatalogPage = {
        "tables": [], "columns": [], "page": page, "page_size": CATALOG_PAGE_SIZE, "visible_count": 0, "total_count": 0,
    }
    if not is_uuid4(table_group_id):
        return empty

    ctes, params = _visibility_ctes(table_group_id, filters)
    counts = fetch_all_from_db(
        f"""{ctes}
        SELECT COUNT(*) AS total_count, COUNT(*) FILTER (WHERE visible) AS visible_count
        FROM catalog_tables
        """,
        params,
    )[0]

    tables = [
        dict(row) for row in fetch_all_from_db(
            f"""{ctes}
            SELECT CONCAT('table_', t.table_id) AS table_id,
                t.table_name,
                t.record_ct,
                t.add_date,
                t.drop_date,
                t.critical_data_element,
                {", ".join(f"{_effective_tag(tag, 'table')} AS {tag}" for tag in TAG_FIELDS)}
            FROM catalog_tables ct
                INNER JOIN data_table_chars t ON (ct.table_id = t.table_id)
                LEFT JOIN table_groups tg ON (t.table_groups_id = tg.id)
            WHERE ct.visible
            ORDER BY LOWER(t.table_name), t.table_id
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": CATALOG_PAGE_SIZE, "offset": page * CATALOG_PAGE_SIZE},
        )
    ]

    columns = []
    if tables:
        columns = [
            dict(row) for row in fetch_all_from_db(
                f"""{ctes}
                SELECT CONCAT('column_', c.column_id) AS column_id,
                    CONCAT('table_', c.table_id) AS table_id,
                    c.column_name,
                    c.general_type,
                    c.functional_data_type,
                    pr.value_ct,
                    c.add_date,
                    c.drop_date,
                    COALESCE(c.critical_data_element, t.critical_data_element) AS critical_data_element,
                    c.pii_flag,
                    c.excluded_data_element,
                    {", ".join(f"{_effective_tag(tag, 'column')} AS {tag}" for tag in TAG_FIELDS)}
                FROM catalog_columns cc
                    INNER JOIN data_column_chars c ON (cc.column_id = c.column_id)
                    INNER JOIN data_table_chars t ON (c.table_id = t.table_id)
                    LEFT JOIN table_groups tg ON (c.table_groups_id = tg.id)
                    LEFT JOIN profile_results pr ON (
                        c.last_complete_profile_run_id = pr.profile_run_id
                        AND c.table_name = pr.table_name
                        AND c.column_name = pr.column_name
                    )
                WHERE cc.visible
                    AND cc.table_id = ANY(CAST(:table_ids AS UUID[]))
                ORDER BY LOWER(t.table_name), t.table_id, c.ordinal_position
                """,
                {**params, "table_ids": [table["table_id"].removeprefix("table_") for table in tables]},
            )
        ]

    return {
        "tables": tables,
        "columns": columns,
        "page": page,
        "page_size": CATALOG_PAGE_SIZE,
        "visible_count": counts["visible_count"],
        "total_count": counts["total_count"],
    }


def get_catalog_page_of_item(
    table_group_id: str,
    filters: CatalogFilters,
    item_type: typing.Literal["table", "column"],
    item_id: str,
) -> int | None:
    """Return the zero-based page that shows a table or column, or ``None`` when the filters hide it."""
    if not is_uuid4(table_group_id) or not is_uuid4(item_id) or item_type not in ("table", "column"):
        return None

    ctes, params = _visibility_ctes(table_group_id, filters)
    selected_table = (
        "SELECT table_id FROM data_column_chars WHERE column_id = :item_id"
        if item_type == "column"
        else "SELECT CAST(:item_id AS UUID)"
    )
    rows = fetch_all_from_db(
        f"""{ctes},
        selected_table AS (
            SELECT t.table_id, LOWER(t.table_name) AS sort_name
            FROM data_table_chars t
            WHERE t.table_id = ({selected_table})
        )
        SELECT
            (SELECT ct.visible FROM catalog_tables ct INNER JOIN selected_table st ON (ct.table_id = st.table_id))
                AS selected_visible,
            COUNT(*) AS preceding_count
        FROM catalog_tables ct
            CROSS JOIN selected_table st
        WHERE ct.visible
            AND (LOWER(ct.table_name), ct.table_id) < (st.sort_name, st.table_id)
        """,
        {**params, "item_id": item_id},
    )
    if not rows or not rows[0]["selected_visible"]:
        return None
    return rows[0]["preceding_count"] // CATALOG_PAGE_SIZE


def get_catalog_visible_items(table_group_id: str, filters: CatalogFilters) -> list[dict]:
    """Return every table and column the filters show, as ``{"type", "id"}`` items."""
    if not is_uuid4(table_group_id):
        return []

    ctes, params = _visibility_ctes(table_group_id, filters)
    rows = fetch_all_from_db(
        f"""{ctes}
        SELECT 'table' AS type, table_id::VARCHAR AS id FROM catalog_tables WHERE visible
        UNION ALL
        SELECT 'column' AS type, cc.column_id::VARCHAR AS id
        FROM catalog_columns cc
            INNER JOIN catalog_tables ct ON (cc.table_id = ct.table_id)
        WHERE cc.visible AND ct.visible
        """,
        params,
    )
    return [{"type": row["type"], "id": row["id"]} for row in rows]
