"""The results queries count each result's notes from its test definition, after the fetch."""

from unittest.mock import patch

import pandas as pd
import pytest

from testgen.ui.queries import test_result_queries

pytestmark = pytest.mark.unit


def test_each_result_gets_its_test_definitions_note_count():
    df = pd.DataFrame({"test_definition_id": ["a", "b", "a", None]})
    with patch.object(
        test_result_queries.TestDefinitionNote, "get_notes_count_by_ids", return_value={"a": 2}
    ) as counts:
        test_result_queries._add_notes_count(df)

    assert sorted(counts.call_args.args[0]) == ["a", "b"]
    assert df["notes_count"].tolist() == [2, 0, 2, 0]


def test_no_results_issue_no_count_query():
    df = pd.DataFrame({"test_definition_id": []})
    with patch.object(test_result_queries.TestDefinitionNote, "get_notes_count_by_ids") as counts:
        test_result_queries._add_notes_count(df)

    counts.assert_not_called()
    assert "notes_count" in df
