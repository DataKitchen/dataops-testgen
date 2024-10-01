
import pandas
from pandas.core.dtypes.common import is_numeric_dtype, is_string_dtype
from reportlab.lib import colors, enums
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BalancedColumns,
    CondPageBreak,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from testgen.ui.services.database_service import get_schema
from testgen.ui.services.test_results_service import (
    do_source_data_lookup,
    do_source_data_lookup_custom,
    get_test_result_history,
)

MARGIN = 0.4 * inch

SECTION_MIN_AVAILABLE_HEIGHT = 60

COLOR_GRAY_BG = HexColor(0xF2F2F2)

COLOR_GREEN_BG = HexColor(0xDCE4DA)

COLOR_YELLOW_BG = HexColor(0xA0C84E40, hasAlpha=True)

COLOR_GREEN_TEXT = HexColor(0x139549)

COLOR_FADED_TEXT = HexColor(0x404040)

COLOR_TEST_STATUS = {
    "Passed": HexColor(0x94C465),
    "Warning": HexColor(0xFCD349),
    "Failed": HexColor(0xE94D4A),
}

PARA_STYLE_DEFAULT = ParagraphStyle(
    "default",
    fontSize=8,
    fontName="Helvetica",
)

PARA_STYLE_TEXT = ParagraphStyle(
    "text",
    PARA_STYLE_DEFAULT,
    fontName="Times-Roman",
)

PARA_STYLE_INFO = ParagraphStyle(
    "info",
    PARA_STYLE_DEFAULT,
    fontName="Helvetica",
    backColor=COLOR_YELLOW_BG,
    borderPadding=12,
    leftIndent=12,
    rightIndent=12,
    spaceBefore=18,
    spaceAfter=18,
)


PARA_STYLE_MONO = ParagraphStyle(
    "monospaced",
    PARA_STYLE_DEFAULT,
    fontName="Courier",
    borderPadding=4,
    backColor=COLOR_GRAY_BG,
    leftIndent=4,
    rightIndent=4,
    spaceBefore=8,
    spaceAfter=8,
)

PARA_STYLE_FOOTNOTE = ParagraphStyle(
    "footnote",
    PARA_STYLE_DEFAULT,
    fontSize=6,
    fontName="Helvetica-Oblique",
    textColor=COLOR_FADED_TEXT,
)


PARA_STYLE_TITLE = ParagraphStyle(
    "title",
    PARA_STYLE_DEFAULT,
    fontSize=18,
    leading=30,
    alignment=enums.TA_CENTER,
    spaceBefore=12,
    spaceAfter=4,
    textColor=COLOR_GREEN_TEXT,
)

PARA_STYLE_H1 = ParagraphStyle(
    "heading_1",
    PARA_STYLE_TITLE,
    fontSize=12,
    leading=16,
    alignment=enums.TA_LEFT,
)

TABLE_STYLE_DEFAULT = TableStyle(
    (
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
    )
)

PARA_STYLE_CELL = ParagraphStyle(
    "table_cell",
    fontSize=7,
    fontName="Helvetica",
)

PARA_STYLE_CELL_NUMERIC = ParagraphStyle(
    "table_cell_numeric",
    PARA_STYLE_CELL,
    alignment=enums.TA_RIGHT,
    fontName="Courier",
)

PARA_STYLE_CELL_NULL = ParagraphStyle(
    "table_cell_null",
    PARA_STYLE_CELL_NUMERIC,
    alignment=enums.TA_CENTER,
    textColor=COLOR_FADED_TEXT,
)


# One time use styles



TABLE_HEADER_CELL_CMD = (
    ("FONT", "Helvetica-Bold"),
    ("ALIGN", "RIGHT"),
    ("BACKGROUND", COLOR_GREEN_BG),
)

TABLE_STYLE_SUMMARY = TableStyle(
    (
        ("GRID", (0, 0), (-1, -1), 2, colors.white),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_GRAY_BG),
        *[(cmd[0], (0, 0), (0, -1), *cmd[1:]) for cmd in TABLE_HEADER_CELL_CMD],
    ),
    parent=TABLE_STYLE_DEFAULT,
)

TABLE_STYLE_DATA = TableStyle(
    (
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRAY_BG),
        ("INNERGRID", (0, 0), (-1, 0), 1, colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_GRAY_BG),
        ("FONT", (0, 0), (-10, 0), "Helvetica-Bold"),

    ),
    parent=TABLE_STYLE_DEFAULT,
)

def get_report_content(document, tr_data):

    yield Paragraph("TestGen Issue Report", PARA_STYLE_TITLE)

    status_color = COLOR_TEST_STATUS.get(tr_data["result_status"], COLOR_GRAY_BG)
    summary_table_style = TableStyle(
        (
            *[(cmd[0], (3, 3), (3, -1), *cmd[1:]) for cmd in TABLE_HEADER_CELL_CMD],
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

            # Measure cell
            ("FONT", (1, 1), (1, 1), "Helvetica-Bold"),

            # Status cell
            ("BACKGROUND", (5, 0), (5, 0), status_color),
            ("FONT", (5, 0), (5, 0), "Helvetica", 14),
            ("ALIGN", (5, 0), (5, 0), "CENTER"),
            ("VALIGN", (5, 0), (5, 0), "MIDDLE"),
            ("TEXTCOLOR", (5, 0), (5, 0), colors.white),
        ),
        parent=TABLE_STYLE_SUMMARY,
    )

    test_timestamp = pandas.to_datetime(tr_data["test_time"]).strftime("%Y-%m-%d %H:%M:%S")
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

        ("Date", test_timestamp, None, "Table Group", tr_data["table_groups_name"]),
        ("Database/Schema", tr_data["schema_name"], None, "Test Suite", tr_data["test_suite"]),
        ("Table", tr_data["table_name"], None, "Data Quality Dimension", tr_data["dq_dimension"]),
        ("Column", tr_data["column_names"], None, "Risk Level", tr_data["severity"]),
    ]

    summary_table_col_widths = [n * document.width for n in (.2, .1, .2, .2, .15, .15)]
    yield Table(summary_table_data, style=summary_table_style, hAlign="LEFT", colWidths=summary_table_col_widths)

    yield KeepTogether([
        Paragraph("Usage Notes", PARA_STYLE_H1),
        Paragraph(f"{tr_data['usage_notes']}", PARA_STYLE_TEXT),
    ])

    history_data = get_test_result_history(get_schema(), tr_data)

    history_table_style = TableStyle(
        (
            ("FONT", (1, 1), (2, -1), "Courier"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ALIGN", (1, 1), (2, -1), "RIGHT"),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ),
        parent=TABLE_STYLE_DATA,
    )

    history_iterator = iter(history_data.iterrows())
    historical_status = history_data["result_status"][0]
    status_change_idx = 1
    while historical_status:
        try:
            idx, row = next(history_iterator)
        except StopIteration:
            row = {"result_status": None}
            idx += 1

        if row["result_status"] != historical_status:
            history_table_style.add(
                "TEXTCOLOR",
                (3, status_change_idx),
                (3, idx),
                COLOR_TEST_STATUS.get(historical_status, COLOR_GRAY_BG)
            )
            historical_status = row["result_status"]
            status_change_idx = idx + 1

        if idx > 1 and "test_date" in row and str(row["test_date"]) == test_timestamp:
            history_table_style.add(
                "BACKGROUND", (0, idx + 1), (-1, idx + 1), COLOR_GRAY_BG
            )

    history_table_data = (
        ("Test Date", "Threshold Value", "Measure Value", "Status"),
        *[
            (r["test_date"], r["threshold_value"], r["result_measure"], r["result_status"])
            for _, r in history_data.iterrows()
        ],
    )

    history_table = Table(history_table_data, style=history_table_style, repeatRows=1, hAlign="LEFT")

    yield CondPageBreak(SECTION_MIN_AVAILABLE_HEIGHT)
    yield Paragraph("Result History", PARA_STYLE_H1)
    yield BalancedColumns(history_table) if len(history_table_data) > 10 else history_table

    yield CondPageBreak(SECTION_MIN_AVAILABLE_HEIGHT)
    yield Paragraph("Sample Data", PARA_STYLE_H1)
    col_padding = 16

    if tr_data["test_type"] == "CUSTOM":
        bad_data_status, bad_data_msg, lookup_query, sample_data = do_source_data_lookup_custom(get_schema(), tr_data)
    else:
        bad_data_status, bad_data_msg, lookup_query, sample_data = do_source_data_lookup(get_schema(), tr_data)

    if bad_data_status in ("ND", "NA"):
        yield Paragraph(bad_data_msg, style=PARA_STYLE_INFO)
    elif bad_data_status == "ERR" or sample_data is None:
        yield Paragraph("It was not possible to fetch the sample data this time.", style=PARA_STYLE_INFO)
    else:
        table_data = sample_data.fillna(Paragraph("NULL", style=PARA_STYLE_CELL_NULL))
        col_len_data = pandas.DataFrame(columns=["min_chars", "max_chars", "min_width", "max_width"], index=iter(sample_data))

        for col_idx in sample_data:
            col = sample_data[col_idx]
            para_style = PARA_STYLE_CELL_NUMERIC if is_numeric_dtype(col) else PARA_STYLE_CELL
            if not is_string_dtype(sample_data[col_idx]):
                col = sample_data[col_idx].astype(str)

            max_width = col.map(lambda cell: stringWidth(cell, para_style.fontName, para_style.fontSize)).max()
            min_chars = col.map(
                lambda cell: max([len(word) for word in cell.split(" ")])
            ).max()
            max_chars = col.str.len().max()
            col_padding = 16
            col_len_data.loc[col_idx] = (
                min_chars,
                max_chars,
                min_chars * max_width / max_chars + col_padding,
                max_width + col_padding,
            )
            table_data[col_idx] = col.map(
                lambda cell: Paragraph(cell, style=para_style) if cell else Paragraph("NULL", PARA_STYLE_CELL_NUMERIC)
            )

        available_width = document.width

        while True:
            if col_len_data["min_width"].sum() <= available_width:
                break
            largest_col = col_len_data["min_width"].idxmax()
            table_data = table_data.drop(columns=largest_col)
            col_len_data = col_len_data.drop(index=largest_col)
            bad_data_msg = "Some too wide columns are omitted. Visit the website to check the full content."

        expandable_width = available_width - col_len_data["min_width"].sum()
        col_len_data["expand_appetite"] = col_len_data["max_width"] - col_len_data["min_width"]
        col_len_data["width"] = col_len_data["min_width"] + col_len_data["expand_appetite"] * max(1, col_len_data["expand_appetite"].sum() / expandable_width)

        sample_data_table = Table(
            (
                [col.replace("_", " ").title() for col in table_data.columns],
                *(data.tolist() for _, data in table_data.iterrows()),
            ),
            style=TABLE_STYLE_DATA,
            hAlign="LEFT",
            colWidths=col_len_data["width"].tolist(),
            repeatRows=1,
        )

        layout_columns = int(available_width / (col_len_data["width"].sum() + col_padding))
        if layout_columns > 1 and len(table_data) > 10:
            yield BalancedColumns(sample_data_table, layout_columns)
        else:
            yield sample_data_table
        if bad_data_msg:
            yield Paragraph(bad_data_msg, style=PARA_STYLE_FOOTNOTE)

    if lookup_query:
        lookup_query_para = Paragraph(lookup_query, PARA_STYLE_MONO)
    else:
        lookup_query_para = Paragraph("No sample data lookup query registered for this test.")

    yield KeepTogether([
        Paragraph("SQL Query", PARA_STYLE_H1),
        lookup_query_para
    ])


def create_report(filename, tr_data):
    doc = SimpleDocTemplate(filename, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
    doc.build(flowables=list(get_report_content(doc, tr_data)))
