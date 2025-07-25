from collections.abc import Iterable
from math import nan

import pandas
from numpy import NaN
from pandas.core.dtypes.common import is_numeric_dtype
from reportlab.lib import colors, enums
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import BalancedColumns, Flowable, Paragraph, Table, TableStyle

from testgen.ui.pdf.style import COLOR_FADED_TEXT, COLOR_GRAY_BG, PARA_STYLE_CELL, TABLE_STYLE_DEFAULT

PARA_STYLE_CELL_DATA = ParagraphStyle(
    "table_cell_data",
    PARA_STYLE_CELL,
    leading=10,
)

PARA_STYLE_CELL_NUMERIC = ParagraphStyle(
    "table_cell_numeric",
    PARA_STYLE_CELL_DATA,
    alignment=enums.TA_RIGHT,
    fontName="Courier",
)

PARA_STYLE_CELL_NULL = ParagraphStyle(
    "table_cell_null",
    PARA_STYLE_CELL_NUMERIC,
    alignment=enums.TA_CENTER,
    textColor=COLOR_FADED_TEXT,
    fontName="Courier-Oblique",
)

PARA_STYLE_CELL_HEADER = ParagraphStyle(
    "table_cell_header",
    PARA_STYLE_CELL_DATA,
    alignment=enums.TA_CENTER,
    fontName="Helvetica",
    splitLongWords=0,
)

TABLE_STYLE_DATA = TableStyle(
    (
        # All table
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRAY_BG),

        # Header
        *[
            (cmd[0], (0, 0), (-1, 0), *cmd[1:])
            for cmd in (
                ("INNERGRID", 1, colors.white),
                ("BACKGROUND", COLOR_GRAY_BG),
                ("VALIGN", "MIDDLE"),
                ("LEFTPADDING", 4),
                ("RIGHTPADDING", 4),
                ("TOPPADDING", 6),
                ("BOTTOMPADDING", 6),
            )
        ],
    ),
    parent=TABLE_STYLE_DEFAULT,
)


class VerticalHeaderCell(Flowable):
    """
    Wrap a Paragraph rotating it 90 degrees.

    Technically, it could rotate any element, but it was designed to rotate a Paragraph (which uses all the available
    with by default, and grows vertically as needed) into a narrow space, such as a table column with a pre-determined
    width, which is the case of our DataFrame table implementation.

    It leverages a starting value for the height as an attempt to avoid unnecessary line breaks, when there's room
    available. It attempts to wrap the Paragraph using the header height as its width, but it checks if the Paragraph
    height is exceeding the column width, making more room and re-wrapping the Paragraph when necessary.

    It also centralizes the flowable, regardless of the cell style.
    """

    INITIAL_HEIGHT = 40
    MAX_HEIGHT = 100
    HEIGHT_INCR_STEP = 5

    def __init__(self, flowable):
        self.flowable = flowable
        self.available_width = 0
        self.flowable_width = 0
        super().__init__()

    def wrap(self, availWidth, _):
        self.available_width = availWidth

        available_height = self.INITIAL_HEIGHT
        while True:
            flowable_height, self.flowable_width = self.flowable.wrap(available_height, self.available_width)

            if self.flowable_width > self.available_width and available_height <= self.MAX_HEIGHT:
                available_height += self.HEIGHT_INCR_STEP
            else:
                break

        return self.available_width, flowable_height

    def drawOn(self, canvas, x, y, _sW=0):
        canvas.saveState()
        canvas.rotate(90)
        # Besides translating x and y for the rotated canvas, we are horizontally centralizing the content by adding
        # half of the "unused" width to the y position (which affects what we as "x" in the rotated canvas)
        ret = self.flowable.drawOn(
            canvas,
            y,
            -(x + self.available_width - (self.available_width - self.flowable_width) / 2),
            _sW,
        )
        canvas.restoreState()
        return ret


class DataFrameTableBuilder:
    """
    Build a Table based on the contents of a Pandas DataFrame.

    It wraps the content of each cell into a Paragraph, to ease line breaks when necessary. Both Tables and Paragraphs
    adjusts their widths automatically, but they don't play well together, so this class calculates each column width
    based on the DataFrame content. It can discard columns when they don't fit in the page width, dropping the widest
    until it fits.

    It also provides a utility method to wrap the table (any potentially any other content that should be rendered
    within it) into a columned layout.
    """

    null_para = Paragraph("NULL", style=PARA_STYLE_CELL_NULL)

    def __init__(self, dataframe, available_width, col_padding=16, max_header_exp_factor=0.4):
        self._dataframe = dataframe
        self.available_width = available_width
        self.col_padding = col_padding
        self.max_header_exp_factor = max_header_exp_factor
        self.omitted_columns = []
        self.col_len_data = pandas.DataFrame(columns=["width", "max_width"], index=iter(dataframe))
        self.table_data = None

    def build_table(self, **kwargs):
        if "colWidths" in kwargs:
            raise ValueError("Can not override the calculated column widths")

        self.table_data = self._prepare_data()
        self._drop_columns_that_dont_fit()
        self.col_len_data["width"] += self._calc_content_cols_expansion()
        header = self._setup_header()

        kwargs["colWidths"] = self.col_len_data["width"].tolist()
        kwargs.setdefault("style", TABLE_STYLE_DATA)
        kwargs.setdefault("repeatRows", 1)

        table_data = (
            header,
            *(data.tolist() for _, data in self.table_data.iterrows()),
        )

        return Table(table_data, **kwargs)

    def split_in_columns(self, flowables, min_rows=5, col_padding=10):
        # We don't want the columns to be glued together, so we add a padding for calculation
        table_width = self._get_current_width() + col_padding

        # Adding one `col_padding` to the available width to compensate for the fact that
        # only n-1 col "paddings" will be rendered for a BC with n cols
        layout_columns = int((self.available_width + col_padding) / table_width)

        # Limiting the number of columns so each column has at least `min_rows` rows
        layout_columns = min(layout_columns, int(len(self.table_data) / min_rows))

        if layout_columns > 1:
            columns = BalancedColumns(
                flowables, layout_columns, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0
            )
            # Honoring the `flowables` input type, for consistency
            return [columns] if isinstance(flowables, Iterable) else columns
        else:
            return flowables

    def _setup_header(self):
        header_cells = pandas.Series(
            [Paragraph(label, style=PARA_STYLE_CELL_HEADER) for label in self.table_data.columns],
            index=self.table_data.columns,
        )

        min_max_widths = header_cells.map(self._calc_cell_width)

        min_widths = min_max_widths.map(lambda t: t[0])
        min_exp_appetite = self._calc_expansion_appetite(min_widths)

        # If the minimal expansion fits into the available width, the columns are expanded.
        # Otherwise, the header is converted to vertical text
        if min_exp_appetite.sum() <= self._get_expansible_width():
            self.col_len_data["width"] += min_exp_appetite

            # If the maximum expansion would grow the table width under the `max_header_exp_factor`,
            # it's expanded to match
            max_widths = min_max_widths.map(lambda t: t[1])
            max_exp_appetite = self._calc_expansion_appetite(max_widths)
            if max_exp_appetite.sum() / self._get_current_width() <= self.max_header_exp_factor:
                self.col_len_data["width"] += max_exp_appetite
        else:
            header_cells = header_cells.map(VerticalHeaderCell)

        return header_cells.tolist()

    def _get_expansible_width(self):
        return self.available_width - self._get_current_width()

    def _get_current_width(self):
        return self.col_len_data["width"].sum()

    def _calc_expansion_appetite(self, desired_widths):
        """
        Given a series of "ideal" widths, return a series with how much each smaller column has to grow to match.
        """
        return (desired_widths - self.col_len_data["width"]).apply(max, args=(0,))

    def _calc_content_cols_expansion(self):
        """
        Calculate how much each column has to grow to fit all the text without wrapping.

        The growth is limited by the available width and applied proportionally.
        """
        expansion_appetite = self._calc_expansion_appetite(self.col_len_data["max_width"])
        expansible_width = self._get_expansible_width()
        expand_factor = max(1, expansion_appetite.sum() / expansible_width) if expansible_width else 0
        return expansion_appetite * expand_factor

    def _drop_columns_that_dont_fit(self):
        while True:
            if self._get_expansible_width() >= 0:
                break
            largest_col = self.col_len_data["width"].idxmax()
            self.table_data = self.table_data.drop(columns=largest_col)
            self.col_len_data = self.col_len_data.drop(index=largest_col)
            self.omitted_columns.append(largest_col)

    def _calc_cell_width(self, cell):
        """
        Calculate the minimum and maximum widths required by a given cell (Paragraph).

        The min width considers wrapping only at the spaces, while the max width considers no wrapping.
        """
        font_name = cell.style.fontName
        font_size = cell.style.fontSize
        space_width = stringWidth(" ", font_name, font_size)
        words_width = [stringWidth(word, font_name, font_size) for word in cell.text.split(" ")]
        min_width = max(words_width) + self.col_padding
        max_width = sum(words_width) + self.col_padding + space_width * (len(words_width) - 1)
        return min_width, max_width

    def _calc_col_width(self, col):
        col_width = col.map(self._calc_cell_width)
        min_width = col_width.max()[0]
        max_width = col_width.map(lambda t: t[1]).max()
        return min_width, max_width

    def _convert_col_values(self, col):
        """
        Convert all values of a given column into Paragraphs.

        It applies different styles depending on the data type, and skips converting values that are already Paragraphs.
        """
        para_style = PARA_STYLE_CELL_NUMERIC if is_numeric_dtype(col.dtype) else PARA_STYLE_CELL

        def _convert_value(value):
            if isinstance(value, Paragraph):
                return value
            elif value in (None, NaN, nan):
                return self.null_para
            else:
                return Paragraph(str(value), para_style)

        return col.map(_convert_value)

    def _prepare_data(self):
        """
        Create a new DataFrame with the converted values from the input DataFrame.

        It also calculates the initial column widths.
        """
        table_data = pandas.DataFrame()
        for col_idx in self._dataframe.columns:
            col = self._dataframe[col_idx]
            table_data[col_idx] = self._convert_col_values(col)
            self.col_len_data.loc[col_idx] = self._calc_col_width(table_data[col_idx])

        # Freeing up the reference to the original Dataframe, in case it's ready to be garbage collected
        del self._dataframe

        return table_data
