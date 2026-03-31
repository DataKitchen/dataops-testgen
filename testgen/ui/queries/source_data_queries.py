"""Thin UI wrappers around the shared source data service.

These add @st.cache_data and preserve the existing function signatures
for backward compatibility with UI callers. All business logic lives in
testgen.common.source_data_service.
"""
from typing import Literal

import pandas as pd
import streamlit as st

from testgen.common.source_data_service import (
    SourceDataResult,
    build_hygiene_query,
    build_test_result_query,
    fetch_hygiene_source_data,
    fetch_test_result_source_data,
)

DEFAULT_LIMIT = 500


def _to_tuple(
    result: SourceDataResult,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    return result.status, result.message, result.query, result.df


def get_hygiene_issue_source_query(issue_data: dict, limit: int = DEFAULT_LIMIT) -> str:
    return build_hygiene_query(issue_data, limit)


@st.cache_data(show_spinner=False)
def get_hygiene_issue_source_data(
    issue_data: dict,
    limit: int = DEFAULT_LIMIT,
    mask_pii: bool = False,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    return _to_tuple(fetch_hygiene_source_data(issue_data, limit, mask_pii))


def get_test_issue_source_query(issue_data: dict, limit: int = DEFAULT_LIMIT) -> str:
    return build_test_result_query(issue_data, limit)


@st.cache_data(show_spinner=False)
def get_test_issue_source_data(
    issue_data: dict,
    limit: int = DEFAULT_LIMIT,
    mask_pii: bool = False,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    return _to_tuple(fetch_test_result_source_data(issue_data, limit, mask_pii))


def get_test_issue_source_query_custom(issue_data: dict) -> str:
    return build_test_result_query(issue_data, limit=0)


@st.cache_data(show_spinner=False)
def get_test_issue_source_data_custom(
    issue_data: dict,
    limit: int | None = None,
    mask_pii: bool = False,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    return _to_tuple(fetch_test_result_source_data(issue_data, limit=limit, mask_pii=mask_pii))
