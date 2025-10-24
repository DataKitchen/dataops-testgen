# UNUSED CODE - TO BE REVIVED LATER

from uuid import UUID

import pandas as pd

from testgen.commands.queries.contingency_query import ContingencySQL
from testgen.commands.queries.profiling_query import ContingencyTable
from testgen.common.database.database_service import fetch_dict_from_db, write_to_app_db


def run_pairwise_contingency_check(profiling_run_id: UUID, threshold_ratio: float) -> None:
    # Goal: identify pairs of values that represent IF X=A THEN Y=B rules

    threshold_ratio = threshold_ratio / 100.0 if threshold_ratio else 0.95

    sql_generator = ContingencySQL()
    table_columns = fetch_dict_from_db(*sql_generator.get_contingency_columns(profiling_run_id))

    if not table_columns:
        return

    table_columns = [ContingencyTable(item) for item in table_columns]
    df_merged = None
    for table in table_columns:
        counts = fetch_dict_from_db(
            *sql_generator.get_contingency_counts(table),
            use_target_db=True,
        )
        if counts:
            df = pd.DataFrame(counts)
            columns = table.contingency_columns.lower().split(",")
            overall_counts = {col: df.groupby(col)["freq_ct"].sum() for col in columns}

            contingency_table = []
            for i, col1 in enumerate(columns):
                for col2 in columns[i + 1 :]:
                    # Create a pivot table for each pair
                    pivot = df.pivot_table(index=col1, columns=col2, values="freq_ct", aggfunc="sum", fill_value=0)
                    pivot = pivot.stack().reset_index()
                    pivot.rename(columns={0: "pair_count"}, inplace=True)

                    pivot["first_column_overall_count"] = pivot[col1].map(overall_counts[col1])
                    pivot["second_column_overall_count"] = pivot[col2].map(overall_counts[col2])

                    pivot["first_column_name"] = col1
                    pivot["second_column_name"] = col2

                    contingency_table.append(pivot)

            # Combine all pairs into a single DataFrame
            contingency_table = pd.concat(contingency_table, ignore_index=True)

            contingency_table["pair_to_first_ratio"] = (
                contingency_table["pair_count"] / contingency_table["first_column_overall_count"]
            )
            contingency_table["pair_to_second_ratio"] = (
                contingency_table["pair_count"] / contingency_table["second_column_overall_count"]
            )

            # Include rows where both cols meet minimum threshold count (max of 30 or 5%)
            total_observations = contingency_table["pair_count"].sum()
            threshold_min = max(total_observations * 0.05, 30)
            contingency_table = contingency_table[
                (contingency_table["first_column_overall_count"] >= threshold_min)
                & (contingency_table["second_column_overall_count"] >= threshold_min)
            ]
            # Drop rows where neither ratio meets the threshold ratio (keep if either meets it)
            #  -- note we still have to check individual columns when saving pairs
            contingency_table = contingency_table[
                ~(
                    (contingency_table["pair_to_first_ratio"] < threshold_ratio)
                    & (contingency_table["pair_to_second_ratio"] < threshold_ratio)
                )
            ]

            contingency_table["profiling_run_id"] = profiling_run_id
            contingency_table["schema_name"] = table.schema_name
            contingency_table["table_name"] = table.table_name

            if df_merged is None:
                df_merged = contingency_table
            else:
                df_merged = pd.concat([df_merged, contingency_table], ignore_index=True)

    save_contingency_rules(df_merged, threshold_ratio)


def save_contingency_rules(df: pd.DataFrame, threshold_ratio: float) -> None:
    if df is None or df.empty:
        return
    
    contingency_rules = []
    for row in df.itertuples():
        # First causes second: almost all of first coincide with second value
        if row.pair_to_first_ratio >= threshold_ratio:
            contingency_rules.append(
                [
                    row.profiling_run_id,
                    row.schema_name,
                    row.table_name,
                    row.first_column_name,
                    getattr(row, row.first_column_name),
                    row.second_column_name,
                    getattr(row, row.second_column_name),
                    row.pair_count,
                    row.first_column_overall_count,
                    row.second_column_overall_count,
                    row.pair_to_first_ratio,
                ]
            )

        # Second causes first: almost all of second coincide with first value
        if row.pair_to_second_ratio >= threshold_ratio:
            contingency_rules.append(
                [
                    row.profiling_run_id,
                    row.schema_name,
                    row.table_name,
                    row.second_column_name,
                    getattr(row, row.second_column_name),
                    row.first_column_name,
                    getattr(row, row.first_column_name),
                    row.pair_count,
                    row.second_column_overall_count,
                    row.first_column_overall_count,
                    row.pair_to_second_ratio,
                ]
            )

    write_to_app_db(
        contingency_rules,
        [
            "profile_run_id",
            "schema_name",
            "table_name",
            "cause_column_name",
            "cause_column_value",
            "effect_column_name",
            "effect_column_value",
            "pair_count",
            "cause_column_total",
            "effect_column_total",
            "rule_ratio",
        ],
        "profile_pair_rules",
    )
