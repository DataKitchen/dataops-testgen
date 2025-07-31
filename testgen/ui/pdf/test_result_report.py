import pandas
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    Paragraph,
    Table,
    TableStyle,
)

from testgen.settings import ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT
from testgen.ui.pdf.dataframe_table import TABLE_STYLE_DATA, DataFrameTableBuilder
from testgen.ui.pdf.style import (
    COLOR_GRAY_BG,
    COLOR_GREEN_BG,
    PARA_STYLE_CELL,
    PARA_STYLE_FOOTNOTE,
    PARA_STYLE_H1,
    PARA_STYLE_INFO,
    PARA_STYLE_LINK,
    PARA_STYLE_MONO,
    PARA_STYLE_TEXT,
    PARA_STYLE_TITLE,
    TABLE_STYLE_DEFAULT,
    get_formatted_datetime,
)
from testgen.ui.pdf.templates import DatakitchenTemplate
from testgen.ui.queries.source_data_queries import get_test_issue_source_data, get_test_issue_source_data_custom
from testgen.ui.queries.test_result_queries import (
    get_test_result_history,
)
from testgen.utils import get_base_url

SECTION_MIN_AVAILABLE_HEIGHT = 120

RESULT_STATUS_COLORS = {
    "Passed": HexColor(0x8BC34A),
    "Warning": HexColor(0xFBC02D),
    "Failed": HexColor(0xEF5350),
    "Error": HexColor(0x8D6E63),
}


def build_summary_table(document, tr_data):
    status_color = RESULT_STATUS_COLORS.get(tr_data["result_status"], COLOR_GRAY_BG)
    summary_table_style = TableStyle(
        (
            # All-table styles
            ("GRID", (0, 0), (-1, -1), 2, colors.white),
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_GRAY_BG),

            # Header cells
            *[
                (cmd[0], *coords, *cmd[1:])
                for coords in (
                    ((3, 3), (3, -3)),
                    ((0, 0), (0, -2))
                )
                for cmd in (
                    ("FONT", "Helvetica-Bold"),
                    ("ALIGN", "RIGHT"),
                    ("BACKGROUND", COLOR_GREEN_BG),
                )
            ],

            # Layout
            ("SPAN", (1, 0), (4, 0)),
            ("SPAN", (5, 0), (5, 2)),
            ("SPAN", (2, 1), (4, 1)),
            ("SPAN", (2, 2), (4, 2)),
            ("SPAN", (1, 3), (2, 3)),
            ("SPAN", (4, 3), (5, 3)),
            ("SPAN", (1, 4), (2, 4)),
            ("SPAN", (4, 4), (5, 4)),
            ("SPAN", (1, 5), (2, 5)),
            ("SPAN", (4, 5), (5, 5)),
            ("SPAN", (1, 6), (2, 6)),
            ("SPAN", (4, 6), (5, 6)),
            ("SPAN", (1, 7), (5, 7)),
            ("SPAN", (0, 8), (5, 8)),

            # Link cell
            ("BACKGROUND", (0, 8), (5, 8), colors.white),

            # Measure cell
            ("FONT", (1, 1), (1, 1), "Helvetica-Bold"),

            # Status cell
            *[
                (cmd[0], (5, 0), (5, 0), *cmd[1:])
                for cmd in (
                    ("BACKGROUND", status_color),
                    ("FONT", "Helvetica", 14),
                    ("ALIGN", "CENTER"),
                    ("VALIGN", "MIDDLE"),
                    ("TEXTCOLOR", colors.white),
                )
            ],
        ),
        parent=TABLE_STYLE_DEFAULT,
    )

    test_timestamp = get_formatted_datetime(tr_data["test_date"])
    summary_table_data = [
        (
            "Test",
            (
                Paragraph(f"""<b>{tr_data["test_name_short"]}:</b> {tr_data["test_name_long"]}""",
                          style=PARA_STYLE_CELL),
                Paragraph(tr_data["test_description"], style=PARA_STYLE_CELL),
            ),
            None,
            None,
            None,
            tr_data["result_status"],
        ),
        ("Measured Value", tr_data["result_measure"], tr_data["measure_uom_description"]),
        ("Threshold Value", tr_data["threshold_value"], tr_data["threshold_description"]),

        ("Test Run Date", test_timestamp, None, "Test Suite", tr_data["test_suite"]),
        ("Database/Schema", tr_data["schema_name"], None, "Table Group", tr_data["table_groups_name"]),
        ("Table", tr_data["table_name"], None, "Data Quality Dimension", tr_data["dq_dimension"]),
        ("Column", tr_data["column_names"], None, "Disposition", tr_data["disposition"] or "No Decision"),
        (
            "Column Tags",
            (
                Paragraph(
                    "<b>Critical data element</b>: Yes" if tr_data["critical_data_element"] else "<i>Critical data element</i>: No",
                    style=PARA_STYLE_CELL,
                ),
                Paragraph(f"<i>Description</i>: {tr_data['column_description']}", style=PARA_STYLE_CELL)
                if tr_data["column_description"]
                else [],
                [
                    Paragraph(f"<i>{tag.replace('_', ' ').capitalize()}</i>: {tr_data[tag]}", style=PARA_STYLE_CELL)
                    for tag in [
                        "data_source",
                        "source_system",
                        "source_process",
                        "business_domain",
                        "stakeholder_group",
                        "transform_level",
                        "aggregation_level",
                        "data_product",
                    ]
                    if tr_data[tag]
                ],
            ),
        ),
        (
            Paragraph(
                f"""<a href="{get_base_url()}/test-runs:results?run_id={tr_data["test_run_id"]}&selected={tr_data["test_result_id"]}">
                    View on TestGen >
                </a>""",
                style=PARA_STYLE_LINK,
            ),
        ),
    ]

    summary_table_col_widths = [n * document.width for n in (.2, .1, .2, .2, .15, .15)]
    return Table(summary_table_data, style=summary_table_style, hAlign="LEFT", colWidths=summary_table_col_widths)


def build_history_table(document, tr_data):
    history_data = get_test_result_history(tr_data, limit=15)

    history_table_style = TableStyle(
        (
            ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ),
        parent=TABLE_STYLE_DATA)

    test_timestamp = pandas.to_datetime(tr_data["test_date"])

    style_per_status = {
        status: ParagraphStyle(f"result_{status}", parent=PARA_STYLE_CELL, textColor=color)
        for status, color in RESULT_STATUS_COLORS.items()
    }

    for idx in history_data.index[history_data["test_date"] == test_timestamp]:
        if idx > 0:
            history_table_style.add("BACKGROUND", (0, idx + 1), (-1, idx + 1), COLOR_GRAY_BG)

    history_df = pandas.DataFrame()
    history_df = history_df.assign(
        test_date=history_data["test_date"].map(get_formatted_datetime).copy(),
        threshold_value=history_data["threshold_value"].astype(float).copy(),
        result_measure=history_data["result_measure"].astype(float).copy(),
        result_status=history_data["result_status"].map(
            lambda status: Paragraph(status, style=style_per_status[status])
        ).copy(),
    )
    history_df.columns = ("Test Date", "Threshold Value", "Measure Value", "Status")

    table_builder = DataFrameTableBuilder(history_df, document.width)
    table = table_builder.build_table(hAlign="LEFT", style=history_table_style)
    return table_builder.split_in_columns(table)


def build_sample_data_content(document, sample_data_tuple):
    sample_data_status, sample_data_msg, lookup_query, sample_data = sample_data_tuple
    if sample_data_status in ("ND", "NA"):
        yield Paragraph(sample_data_msg, style=PARA_STYLE_INFO)
    elif sample_data_status == "ERR" or sample_data is None:
        yield Paragraph("It was not possible to fetch the sample data this time.", style=PARA_STYLE_INFO)
    else:
        sample_data.columns = [col.replace("_", " ").title() for col in sample_data.columns]
        df_table_builder = DataFrameTableBuilder(sample_data, document.width)
        table_flowables = [df_table_builder.build_table(hAlign="LEFT")]
        if df_table_builder.omitted_columns:
            omitted_columns = ", ".join(df_table_builder.omitted_columns)
            sample_data_msg = f"Note: The following columns were omitted from this table: {omitted_columns}"
        if sample_data_msg:
            table_flowables.append(Paragraph(sample_data_msg, style=PARA_STYLE_FOOTNOTE))

        yield from df_table_builder.split_in_columns(table_flowables)


def build_sql_query_content(sample_data_tuple):
    lookup_query = sample_data_tuple[2]
    if lookup_query:
        return Paragraph(lookup_query, PARA_STYLE_MONO)
    else:
        return Paragraph("No sample data lookup query registered for this test.")


def get_report_content(document, tr_data):
    yield Paragraph("TestGen Test Issue Report", PARA_STYLE_TITLE)
    yield build_summary_table(document, tr_data)

    if tr_data["usage_notes"]:
        yield KeepTogether([
            Paragraph("Usage Notes", PARA_STYLE_H1),
            Paragraph(f"{tr_data['usage_notes']}", PARA_STYLE_TEXT),
        ])

    yield CondPageBreak(SECTION_MIN_AVAILABLE_HEIGHT)
    yield Paragraph("Result History", PARA_STYLE_H1)
    yield build_history_table(document, tr_data)

    if tr_data["test_type"] == "CUSTOM":
        sample_data_tuple = get_test_issue_source_data_custom(tr_data, limit=ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT)
    else:
        sample_data_tuple = get_test_issue_source_data(tr_data, limit=ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT)

    yield CondPageBreak(SECTION_MIN_AVAILABLE_HEIGHT)
    yield Paragraph("Sample Data", PARA_STYLE_H1)
    yield from build_sample_data_content(document, sample_data_tuple)

    yield KeepTogether([
        Paragraph("SQL Query", PARA_STYLE_H1),
        build_sql_query_content(sample_data_tuple)
    ])


def create_report(filename, tr_data):
    doc = DatakitchenTemplate(filename)
    doc.build(flowables=list(get_report_content(doc, tr_data)))
