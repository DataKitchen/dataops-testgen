from reportlab.lib import enums
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from testgen.ui.services.database_service import get_schema
from testgen.ui.services.test_results_service import (
    do_source_data_lookup,
    do_source_data_lookup_custom,
    get_test_result_history,
)

PARA_STYLE_DEFAULT = ParagraphStyle(
    "default",
    fontSize=8,
)

PARA_STYLE_INFO = PARA_STYLE_DEFAULT


PARA_STYLE_ERROR = PARA_STYLE_DEFAULT


PARA_STYLE_MONO = ParagraphStyle(
    "heading_1",
    PARA_STYLE_DEFAULT,

)


PARA_STYLE_H1 = ParagraphStyle(
    "heading_1",
    PARA_STYLE_DEFAULT,
    fontSize=12,
    leading=16,
)

PARA_STYLE_TITLE = ParagraphStyle(
    "title",
    PARA_STYLE_DEFAULT,
    fontSize=18,
    leading=30,
    alignment=enums.TA_CENTER,
)

TABLE_STYLE_SUMMARY = TableStyle(
    (
        # All cells
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7),

        # Header
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
    )
)

def get_report_content(tr_data):

    yield Paragraph(f"TestGen Issue Report: {tr_data['result_status']}", PARA_STYLE_TITLE)

    yield Paragraph("Summary", PARA_STYLE_H1)

    summary_table_data = [
        ("Date", tr_data["test_date"]),
        ("Database/Schema", tr_data["schema_name"]),
        ("Table", tr_data["table_name"]),
        ("Column", tr_data["column_names"]),
        ("Table Group", tr_data["table_groups_name"]),
        ("Test Suite", tr_data["test_suite"]),
        ("Issue Type", "Test Result"),
        ("Risk Level", tr_data["severity"]),
        ("Data Quality Dimension", tr_data["dq_dimension"]),
        ("Test", f"""{tr_data["test_name_short"]}: {tr_data["test_name_long"]}\n{tr_data["test_description"]}"""),
        ("Result Measure", tr_data["result_measure"]),
        ("Threshold Value", f"""{tr_data["threshold_value"]} {tr_data["threshold_description"]}"""),
    ]
    if tr_data["measure_uom_description"]:
        summary_table_data.append(("Units", tr_data["measure_uom_description"]))

    yield Table(summary_table_data, style=TABLE_STYLE_SUMMARY, hAlign="LEFT")

    yield Paragraph("Usage Notes", PARA_STYLE_H1)
    yield Paragraph(tr_data["usage_notes"], PARA_STYLE_DEFAULT)

    yield Paragraph("Result History", PARA_STYLE_H1)

    history_data = get_test_result_history(get_schema(), tr_data)

    history_table_data = [
        (r["test_date"], r["threshold_value"], r["result_measure"], r["result_status"])
        for _, r in history_data.iterrows()
    ]

    yield Table(history_table_data)

    yield Paragraph("Sample Data", PARA_STYLE_H1)

    if tr_data["test_type"] == "CUSTOM":
        bad_data_status, bad_data_msg, lookup_query, sample_data = do_source_data_lookup_custom(get_schema(), tr_data)
    else:
        bad_data_status, bad_data_msg, lookup_query, sample_data = do_source_data_lookup(get_schema(), tr_data)
    if bad_data_status in {"ND", "NA"}:
        yield Paragraph(bad_data_msg, style=PARA_STYLE_INFO)
    elif bad_data_status == "ERR":
        yield Paragraph(bad_data_msg, style=PARA_STYLE_ERROR)
    elif sample_data is None:
        yield Paragraph("An unknown error was encountered.", style=PARA_STYLE_ERROR)
    else:
        if bad_data_msg:
            yield Paragraph(bad_data_msg, style=PARA_STYLE_DEFAULT)

        sample_data.fillna("[NULL]", inplace=True)

        yield Table(
            (
                [col.replace("_", " ").title() for col in sample_data.columns],
                *(data for _, data in sample_data.iterrows()),
            )
        )


    yield Paragraph("SQL Query", PARA_STYLE_H1)

    yield Paragraph(lookup_query, PARA_STYLE_MONO)


def create_report(filename, test_result_id):
    doc = SimpleDocTemplate(filename)
    doc.build(flowables=list(get_report_content(test_result_id)))
