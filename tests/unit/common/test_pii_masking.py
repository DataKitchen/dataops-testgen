import pandas as pd

from testgen.common.pii_masking import PII_REDACTED, mask_hygiene_detail, mask_profiling_pii, mask_source_data_pii


class Test_mask_source_data_pii:
    def test_masks_pii_columns(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "ssn": ["123-45-6789", "987-65-4321"],
            "age": [30, 25],
        })
        mask_source_data_pii(df, {"ssn"})
        assert df["ssn"].tolist() == [PII_REDACTED, PII_REDACTED]
        assert df["age"].tolist() == [30, 25]
        assert df["name"].tolist() == ["Alice", "Bob"]

    def test_preserves_non_pii_columns(self):
        df = pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]})
        mask_source_data_pii(df, {"col_a"})
        assert df["col_b"].tolist() == ["x", "y"]

    def test_handles_empty_dataframe(self):
        df = pd.DataFrame(columns=["name", "ssn"])
        mask_source_data_pii(df, {"ssn"})
        assert df.empty

    def test_handles_missing_pii_column(self):
        df = pd.DataFrame({"col_a": [1, 2]})
        mask_source_data_pii(df, {"nonexistent_col"})
        assert df["col_a"].tolist() == [1, 2]

    def test_handles_empty_pii_set(self):
        df = pd.DataFrame({"col_a": [1, 2]})
        mask_source_data_pii(df, set())
        assert df["col_a"].tolist() == [1, 2]

    def test_case_insensitive_matching(self):
        df = pd.DataFrame({"SSN": ["123-45-6789"], "Name": ["Alice"]})
        mask_source_data_pii(df, {"ssn"})
        assert df["SSN"].tolist() == [PII_REDACTED]
        assert df["Name"].tolist() == ["Alice"]

    def test_multiple_pii_columns(self):
        df = pd.DataFrame({
            "name": ["Alice"],
            "ssn": ["123"],
            "email": ["a@b.com"],
            "age": [30],
        })
        mask_source_data_pii(df, {"ssn", "email"})
        assert df["ssn"].tolist() == [PII_REDACTED]
        assert df["email"].tolist() == [PII_REDACTED]
        assert df["name"].tolist() == ["Alice"]
        assert df["age"].tolist() == [30]


class Test_mask_profiling_pii:
    def _make_profiling_df(self):
        return pd.DataFrame({
            "column_name": ["ssn", "age", "email"],
            "top_freq_values": ["123|456", "30|25", "a@b|c@d"],
            "min_text": ["000", "20", "a@a"],
            "max_text": ["999", "40", "z@z"],
            "min_value": [0, 20, None],
            "max_value": [999, 40, None],
        })

    def test_masks_pii_profiling_fields(self):
        df = self._make_profiling_df()
        mask_profiling_pii(df, {"ssn", "email"})

        ssn_row = df[df["column_name"] == "ssn"].iloc[0]
        assert ssn_row["top_freq_values"] == PII_REDACTED
        assert ssn_row["min_text"] == PII_REDACTED
        assert ssn_row["max_text"] == PII_REDACTED
        assert ssn_row["min_value"] == PII_REDACTED
        assert ssn_row["max_value"] == PII_REDACTED

        email_row = df[df["column_name"] == "email"].iloc[0]
        assert email_row["top_freq_values"] == PII_REDACTED

    def test_preserves_non_pii_rows(self):
        df = self._make_profiling_df()
        mask_profiling_pii(df, {"ssn"})

        age_row = df[df["column_name"] == "age"].iloc[0]
        assert age_row["top_freq_values"] == "30|25"
        assert age_row["min_text"] == "20"
        assert age_row["max_text"] == "40"

    def test_handles_empty_dataframe(self):
        df = pd.DataFrame(columns=["column_name", "top_freq_values"])
        mask_profiling_pii(df, {"ssn"})
        assert df.empty

    def test_handles_empty_pii_set(self):
        df = self._make_profiling_df()
        original_values = df["top_freq_values"].tolist()
        mask_profiling_pii(df, set())
        assert df["top_freq_values"].tolist() == original_values

    def test_handles_missing_fields(self):
        df = pd.DataFrame({
            "column_name": ["ssn", "age"],
            "top_freq_values": ["123", "30"],
        })
        mask_profiling_pii(df, {"ssn"})
        assert df.loc[0, "top_freq_values"] == PII_REDACTED
        assert df.loc[1, "top_freq_values"] == "30"

    def test_case_insensitive_column_name_matching(self):
        df = pd.DataFrame({
            "column_name": ["SSN", "age"],
            "top_freq_values": ["123", "30"],
            "min_text": ["000", "20"],
        })
        mask_profiling_pii(df, {"ssn"})
        assert df.loc[0, "top_freq_values"] == PII_REDACTED
        assert df.loc[0, "min_text"] == PII_REDACTED
        assert df.loc[1, "top_freq_values"] == "30"


class Test_mask_profiling_pii_dict:
    def test_masks_fields_when_column_is_pii(self):
        data = {
            "column_name": "ssn",
            "top_freq_values": "123|456",
            "min_text": "000",
            "max_text": "999",
            "min_value": 0,
            "max_value": 999,
            "min_value_over_0": 1,
            "min_date": "2024-01-01",
            "max_date": "2024-12-31",
        }
        mask_profiling_pii(data, {"ssn"})
        assert data["top_freq_values"] == PII_REDACTED
        assert data["min_text"] == PII_REDACTED
        assert data["max_text"] == PII_REDACTED
        assert data["min_value"] == PII_REDACTED
        assert data["max_value"] == PII_REDACTED
        assert data["min_value_over_0"] == PII_REDACTED
        assert data["min_date"] == PII_REDACTED
        assert data["max_date"] == PII_REDACTED

    def test_preserves_non_pii_column(self):
        data = {
            "column_name": "age",
            "top_freq_values": "30|25",
            "min_text": "20",
            "max_text": "40",
        }
        mask_profiling_pii(data, {"ssn"})
        assert data["top_freq_values"] == "30|25"
        assert data["min_text"] == "20"
        assert data["max_text"] == "40"

    def test_case_insensitive_matching(self):
        data = {"column_name": "SSN", "min_text": "000"}
        mask_profiling_pii(data, {"ssn"})
        assert data["min_text"] == PII_REDACTED

    def test_empty_pii_set_skips_masking(self):
        data = {"column_name": "ssn", "min_text": "000"}
        mask_profiling_pii(data, set())
        assert data["min_text"] == "000"

    def test_missing_fields_handled(self):
        data = {"column_name": "ssn", "min_text": "000"}
        mask_profiling_pii(data, {"ssn"})
        assert data["min_text"] == PII_REDACTED
        assert "top_freq_values" not in data

    def test_no_column_name_masks_unconditionally(self):
        data = {"top_freq_values": "123|456", "min_text": "000"}
        mask_profiling_pii(data, {"ssn"})
        assert data["top_freq_values"] == PII_REDACTED
        assert data["min_text"] == PII_REDACTED

    def test_preserves_non_profiling_fields(self):
        data = {
            "column_name": "ssn",
            "top_freq_values": "123",
            "record_ct": 100,
            "distinct_value_ct": 50,
        }
        mask_profiling_pii(data, {"ssn"})
        assert data["top_freq_values"] == PII_REDACTED
        assert data["record_ct"] == 100
        assert data["distinct_value_ct"] == 50


class Test_mask_hygiene_detail_dataframe:
    def test_masks_detail_for_pii_redactable_rows(self):
        df = pd.DataFrame({
            "column_name": ["ssn", "age", "email"],
            "detail": ["SSN range: 100-999", "Count: 50", "Email range: a@b - z@y"],
            "detail_redactable": [True, False, True],
            "pii_flag": ["A/ID/SSN", None, "B/CONTACT/Email"],
        })
        mask_hygiene_detail(df)
        assert df.loc[0, "detail"] == PII_REDACTED
        assert df.loc[1, "detail"] == "Count: 50"
        assert df.loc[2, "detail"] == PII_REDACTED

    def test_preserves_non_redactable_pii_rows(self):
        df = pd.DataFrame({
            "column_name": ["ssn"],
            "detail": ["Non-printing chars: 5"],
            "detail_redactable": [False],
            "pii_flag": ["A/ID/SSN"],
        })
        mask_hygiene_detail(df)
        assert df.loc[0, "detail"] == "Non-printing chars: 5"

    def test_preserves_redactable_non_pii_rows(self):
        df = pd.DataFrame({
            "column_name": ["age"],
            "detail": ["Date range: 2020-2024"],
            "detail_redactable": [True],
            "pii_flag": [None],
        })
        mask_hygiene_detail(df)
        assert df.loc[0, "detail"] == "Date range: 2020-2024"

    def test_handles_empty_dataframe(self):
        df = pd.DataFrame(columns=["column_name", "detail", "detail_redactable", "pii_flag"])
        mask_hygiene_detail(df)
        assert df.empty

    def test_handles_missing_detail_redactable_column(self):
        df = pd.DataFrame({
            "column_name": ["ssn"],
            "detail": ["some detail"],
            "pii_flag": ["A/ID/SSN"],
        })
        mask_hygiene_detail(df)
        assert df.loc[0, "detail"] == "some detail"

    def test_handles_null_detail_redactable(self):
        df = pd.DataFrame({
            "column_name": ["ssn"],
            "detail": ["SSN range: 100-999"],
            "detail_redactable": [None],
            "pii_flag": ["A/ID/SSN"],
        })
        mask_hygiene_detail(df)
        assert df.loc[0, "detail"] == "SSN range: 100-999"


class Test_mask_hygiene_detail_list_with_pii_flag:
    def test_masks_detail_when_redactable_and_pii(self):
        issues = [
            {"detail": "Date range: 2020-2024", "detail_redactable": True, "pii_flag": "A/ID/SSN"},
            {"detail": "Count: 50", "detail_redactable": False, "pii_flag": "A/ID/SSN"},
            {"detail": "Min text: Alice", "detail_redactable": True, "pii_flag": None},
        ]
        mask_hygiene_detail(issues)
        assert issues[0]["detail"] == PII_REDACTED
        assert issues[1]["detail"] == "Count: 50"
        assert issues[2]["detail"] == "Min text: Alice"

    def test_handles_empty_list(self):
        issues = []
        mask_hygiene_detail(issues)
        assert issues == []

    def test_handles_missing_fields(self):
        issues = [{"detail": "some detail"}]
        mask_hygiene_detail(issues)
        assert issues[0]["detail"] == "some detail"


class Test_mask_hygiene_detail_list_with_pii_columns:
    def test_masks_detail_when_column_is_pii(self):
        issues = [
            {"column_name": "ssn", "detail": "Date range: 2020-2024", "detail_redactable": True},
            {"column_name": "age", "detail": "Count: 50", "detail_redactable": True},
            {"column_name": "email", "detail": "Min text: a@b", "detail_redactable": True},
        ]
        mask_hygiene_detail(issues, pii_columns={"ssn", "email"})
        assert issues[0]["detail"] == PII_REDACTED
        assert issues[1]["detail"] == "Count: 50"
        assert issues[2]["detail"] == PII_REDACTED

    def test_case_insensitive_column_matching(self):
        issues = [{"column_name": "SSN", "detail": "range: 100-999", "detail_redactable": True}]
        mask_hygiene_detail(issues, pii_columns={"ssn"})
        assert issues[0]["detail"] == PII_REDACTED

    def test_empty_pii_columns_skips_masking(self):
        issues = [{"column_name": "ssn", "detail": "range: 100-999", "detail_redactable": True}]
        mask_hygiene_detail(issues, pii_columns=set())
        assert issues[0]["detail"] == "range: 100-999"

    def test_non_redactable_issues_preserved(self):
        issues = [{"column_name": "ssn", "detail": "Non-printing: 5", "detail_redactable": False}]
        mask_hygiene_detail(issues, pii_columns={"ssn"})
        assert issues[0]["detail"] == "Non-printing: 5"
