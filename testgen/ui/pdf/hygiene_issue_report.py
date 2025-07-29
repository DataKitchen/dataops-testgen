from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, Table, TableStyle

from testgen.settings import ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT
from testgen.ui.pdf.dataframe_table import DataFrameTableBuilder
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
from testgen.ui.queries.source_data_queries import get_hygiene_issue_source_data
from testgen.utils import get_base_url

SECTION_MIN_AVAILABLE_HEIGHT = 120

CLASS_COLORS =  {
    "Definite": HexColor(0xEF5350),
    "Likely": HexColor(0xFF9800),
    "Possible": HexColor(0xFBC02D),
    "Potential PII": HexColor(0x8D6E63),
}

def build_summary_table(document, hi_data):

    summary_table_style = TableStyle(
        (
            # All-table styles
            ("GRID", (0, 0), (-1, -1), 2, colors.white),
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_GRAY_BG),

            # Header cells
            *[
                (cmd[0], *coords, *cmd[1:])
                for coords in (
                    ((2, 2), (2, -3)),
                    ((0, 0), (0, -2))
                )
                for cmd in (
                    ("FONT", "Helvetica-Bold"),
                    ("ALIGN", "RIGHT"),
                    ("BACKGROUND", COLOR_GREEN_BG),
                )
            ],

            # Layout
            ("SPAN", (1, 0), (3, 0)),

            ("SPAN", (1, 1), (4, 1)),

            ("SPAN", (3, 2), (4, 2)),
            ("SPAN", (3, 3), (4, 3)),
            ("SPAN", (3, 4), (4, 4)),
            ("SPAN", (3, 5), (4, 5)),
            ("SPAN", (1, 6), (4, 6)),
            ("SPAN", (0, 7), (4, 7)),

            # Link cell
            ("BACKGROUND", (0, 7), (4, 7), colors.white),

            # Status cell
            *[
                (cmd[0], (4, 0), (4, 0), *cmd[1:])
                for cmd in (
                    ("BACKGROUND", CLASS_COLORS.get(hi_data["issue_likelihood"], COLOR_GRAY_BG)),
                    ("ALIGNMENT", "CENTER"),
                    ("VALIGN", "MIDDLE"),
                )
            ],
        ),
        parent=TABLE_STYLE_DEFAULT,
    )


    profiling_timestamp = get_formatted_datetime(hi_data["profiling_starttime"])
    summary_table_data = [
        (
            "Hygiene Issue",
            (
                Paragraph(f"<b>{hi_data['anomaly_name']}:</b>", style=PARA_STYLE_CELL),
                Paragraph(hi_data["anomaly_description"], style=PARA_STYLE_CELL),
            ),
            None,
            None,
            Paragraph(
                hi_data["issue_likelihood"],
                style=ParagraphStyle("likelihood", textColor=colors.white, fontSize=10, parent=PARA_STYLE_CELL, alignment=TA_CENTER),
            ),
        ),
        (
            "Detail",
            Paragraph(
                hi_data["detail"],
                style=ParagraphStyle("detail", fontName="Helvetica-Bold", parent=PARA_STYLE_CELL),
            ),
        ),

        ("Profiling Date", profiling_timestamp, "Table Group", hi_data["table_groups_name"]),
        ("Database/Schema", hi_data["schema_name"], "Disposition", hi_data["disposition"] or "No Decision"),
        ("Table", hi_data["table_name"], "Column Type", hi_data["column_type"]),
        ("Column", hi_data["column_name"], "Semantic Data Type", hi_data["functional_data_type"]),
        (
            "Column Tags",
            (
                Paragraph(
                    "<b>Critical data element</b>: Yes" if hi_data["critical_data_element"] else "<i>Critical data element</i>: No",
                    style=PARA_STYLE_CELL,
                ),
                Paragraph(f"<i>Description</i>: {hi_data['column_description']}", style=PARA_STYLE_CELL)
                if hi_data["column_description"]
                else [],
                [
                    Paragraph(f"<i>{tag.replace('_', ' ').capitalize()}</i>: {hi_data[tag]}", style=PARA_STYLE_CELL)
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
                    if hi_data[tag]
                ],
            ),
        ),
        (
            Paragraph(
                f"""<a href="{get_base_url()}/profiling-runs:hygiene?run_id={hi_data["profile_run_id"]}&selected={hi_data["id"]}">
                    View on TestGen >
                </a>""",
                style=PARA_STYLE_LINK,
            ),
        ),
    ]

    summary_table_col_widths = [n * document.width for n in (.15, .35, .15, .15, .20)]
    return Table(summary_table_data, style=summary_table_style, hAlign="LEFT", colWidths=summary_table_col_widths)


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
        return Paragraph("No sample data lookup query registered for this issue.")


def get_report_content(document, hi_data):
    yield Paragraph("TestGen Hygiene Issue Report", PARA_STYLE_TITLE)
    yield build_summary_table(document, hi_data)

    yield CondPageBreak(SECTION_MIN_AVAILABLE_HEIGHT)
    yield Paragraph("Suggested Action", style=PARA_STYLE_H1)
    yield Paragraph(hi_data["suggested_action"], style=PARA_STYLE_TEXT)

    sample_data_tuple = get_hygiene_issue_source_data(hi_data, limit=ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT)

    yield CondPageBreak(SECTION_MIN_AVAILABLE_HEIGHT)
    yield Paragraph("Sample Data", PARA_STYLE_H1)
    yield from build_sample_data_content(document, sample_data_tuple)

    yield KeepTogether([
        Paragraph("SQL Query", PARA_STYLE_H1),
        build_sql_query_content(sample_data_tuple)
    ])


def create_report(filename, hi_data):
    doc = DatakitchenTemplate(filename)
    doc.build(flowables=list(get_report_content(doc, hi_data)))
