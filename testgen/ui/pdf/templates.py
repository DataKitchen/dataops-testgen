from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate

from testgen.ui.pdf.dk_logo import get_logo

MARGIN = 0.4 * inch


class DatakitchenTemplate(SimpleDocTemplate):

    def __init__(self, filename):
        super().__init__(filename, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 10, bottomMargin=MARGIN)

    def beforePage(self):
        header_padding = 5
        header_base_y = self.pagesize[1] - 18
        self.canv.setFont("Helvetica", 8)
        self.canv.drawString(MARGIN + header_padding, header_base_y , "DataOps Data Quality TestGen")
        self.canv.line(
            MARGIN + header_padding,
            header_base_y - header_padding,
            self.pagesize[0] - MARGIN,
            header_base_y - header_padding
        )

        logo = get_logo(80)
        logo.drawOn(
            self.canv,
            self.pagesize[0] - logo.width - MARGIN,
            header_base_y
        )
