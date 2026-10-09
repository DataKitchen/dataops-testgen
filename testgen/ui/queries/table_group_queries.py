"""UI cache adapter around the table-group preview service.

The implementation lives in ``testgen.common.database.table_group_service`` so
MCP tools and the CLI can reuse identical logic without a Streamlit runtime.
This module wraps the service in ``@st.cache_data`` for the Streamlit pages.
"""

import json

import streamlit as st

from testgen.common.database.table_group_service import (
    TableGroupPreview,
    preview_table_group,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.ui.services.query_cache import get_connection


def get_table_group_preview(
    table_group: TableGroup,
    connection: Connection | None = None,
    verify_table_access: bool = False,
) -> TableGroupPreview:
    """Streamlit-cached wrapper around ``preview_table_group``.

    When the caller does not supply a ``Connection`` and the table group has a
    ``connection_id``, the connection is resolved via the Streamlit cache so
    repeated previews on the same page don't re-fetch it.
    """
    if connection is None and table_group.connection_id:
        connection = get_connection(table_group.connection_id)

    if verify_table_access:
        preview, _, _ = preview_table_group(table_group, connection=connection, verify_access=True)
        return preview
    return _cached_preview(table_group, connection)


def reset_table_group_preview() -> None:
    _cached_preview.clear()


def preview_cache_key(table_group: TableGroup) -> tuple:
    """Every field that changes which tables the preview finds.

    A field left out serves the previous preview back after it is edited.
    """
    return (
        table_group.table_group_schema,
        table_group.profiling_table_set,
        table_group.profiling_include_mask,
        table_group.profiling_exclude_mask,
        json.dumps(table_group.file_declarations, sort_keys=True),
    )


@st.cache_data(
    show_spinner=False,
    hash_funcs={
        TableGroup: preview_cache_key,
        Connection: lambda x: x.to_dict(),
    },
)
def _cached_preview(table_group, connection):
    # Only the preview is cached: the column list can run to hundreds of thousands of entries.
    preview, _, _ = preview_table_group(table_group, connection=connection, verify_access=False)
    return preview
