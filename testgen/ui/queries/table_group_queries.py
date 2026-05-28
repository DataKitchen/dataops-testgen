"""UI cache adapter around the table-group preview service.

The implementation lives in ``testgen.common.database.table_group_service`` so
MCP tools and the CLI can reuse identical logic without a Streamlit runtime.
This module wraps the service in ``@st.cache_data`` for the Streamlit pages.
"""

from collections.abc import Callable
from uuid import UUID

import streamlit as st

from testgen.common.database.table_group_service import (
    TableGroupPreview,
    make_save_data_chars,
    preview_table_group,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.ui.services.query_cache import get_connection


def get_table_group_preview(
    table_group: TableGroup,
    connection: Connection | None = None,
    verify_table_access: bool = False,
) -> tuple[TableGroupPreview, Callable[[UUID], None] | None]:
    """Streamlit-cached wrapper around ``preview_table_group``.

    The service returns ``(preview, data_chars, sql_generator)`` — all picklable —
    so the cache can store the result. The ``save_data_chars`` closure is built
    here, outside the cached function, because local closures can't be pickled.

    When the caller does not supply a ``Connection`` and the table group has a
    ``connection_id``, the connection is resolved via the Streamlit cache so
    repeated previews on the same page don't re-fetch it.
    """
    if connection is None and table_group.connection_id:
        connection = get_connection(table_group.connection_id)

    if verify_table_access:
        preview, data_chars, sql_generator = preview_table_group(
            table_group, connection=connection, verify_access=True,
        )
    else:
        preview, data_chars, sql_generator = _cached_preview(table_group, connection)

    save = (
        make_save_data_chars(data_chars, sql_generator)
        if data_chars is not None and sql_generator is not None
        else None
    )
    return preview, save


def reset_table_group_preview() -> None:
    _cached_preview.clear()


@st.cache_data(
    show_spinner=False,
    hash_funcs={
        TableGroup: lambda x: (
            x.table_group_schema,
            x.profiling_table_set,
            x.profiling_include_mask,
            x.profiling_exclude_mask,
        ),
        Connection: lambda x: x.to_dict(),
    },
)
def _cached_preview(table_group, connection):
    return preview_table_group(table_group, connection=connection, verify_access=False)
