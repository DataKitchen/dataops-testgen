import math
from datetime import datetime

from testgen.common.models.profiling_run import ProfilingRunStatus
from testgen.common.models.test_definition import TestRunStatus
from testgen.common.notifications.base import BaseEmailTemplate
from testgen.utils import friendly_score


class BaseNotificationTemplate(BaseEmailTemplate):

    def pluralize_helper(self, count: int, singular: str, plural: str) -> str:
        return singular if count == 1 else plural

    def format_number_helper(self, number: int) -> str:
        return "" if number is None else f"{number:,}"

    def format_dt_helper(self, dt: datetime) -> str:
        return "" if dt is None else dt.strftime("%b %d, %-I:%M %p UTC")

    def format_duration_helper(self, start_time: datetime, end_time: datetime) -> str:
        total_seconds = abs(end_time - start_time).total_seconds()
        units = [
          (math.floor(total_seconds / (3600 * 24)), "d"),
          (math.floor((total_seconds % (3600 * 24)) / 3600), "h"),
          (math.floor((total_seconds % 3600) / 60), "m"),
          (round(total_seconds % 60), "s"),
        ]
        formatted = " ".join([ f"{unit[0]}{unit[1]}" for unit in units if unit[0] ])
        return formatted.strip() or "< 1s"

    def format_status_helper(self, status: TestRunStatus | ProfilingRunStatus) -> str:
        return {
            "Complete": "Completed",
            "Cancelled": "Canceled",
        }.get(status, status)

    def format_score_helper(self, score: float) -> str:
        return friendly_score(score)

    def percentage_helper(self, value: int, total: int) -> int:
        return round((value * 100) / total)

    def truncate_helper(self, length: int, text: str | None) -> str:
        if not text:
            return "-"
        return text if len(text) <= length else f"{text[:length-1]}…"

    def get_main_content_template(self) -> str:
        raise NotImplementedError

    def get_extra_css_template(self) -> str:
        return ""

    def get_body_template(self) -> str:
        return """
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>DataKitchen</title>
  <style type="text/css">
    body {
      margin: 0;
      padding: 0;
      background: #eeeeee !important;
    }

    h1, p {
      margin: 0;
    }

    .background {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      background-color: #eeeeee;
    }

    .content {
      margin: 0 auto;
      background-color: white;
      font-family: 'Roboto', 'Helvetica Neue', sans-serif;
      font-size: 14px;
      line-height: 20px;
      color: rgba(0, 0, 0, 0.87);
      width: 100%;
      min-width: 500px;
      max-width: 1200px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12), 0 1px 1px rgba(0, 0, 0, 0.14), 0 2px 1px rgba(0, 0, 0, 0.02);
    }

    .header {
      width: 100%;
      margin: 20px 32px 0;
    }

    .logo {
      width: 124px;
      vertical-align: top;
      padding-top: 4px;
      padding-left: 0;
    }

    .logo--full {
      height: 24px;
    }

    .logo--icon {
      height: 40px;
      display: none;
    }

    .title {
      font-size: 20px;
      line-height: 23px;
      white-space: nowrap;
      text-align: center;
      margin-bottom: 4px;
      padding-right: 124px;
      color: rgba(0, 0, 0, 0.87);
    }

    .summary {
      padding: 16px;
      border: 1px solid rgba(0, 0, 0, 0.12);
      border-radius: 4px;
      margin: 8px 32px 4px;
    }

    .summary > table {
      width: 100%;
    }

    .summary__title {
      font-size: 16px;
      line-height: 23px;
      white-space: nowrap;
      color: rgba(0, 0, 0, 0.87);
      text-transform: capitalize;
    }

    .summary__subtitle {
      font-style: italic;
      color: rgba(0, 0, 0, 0.6);
    }

    .summary__caption {
      font-size: 12px;
      font-style: italic;
      color: rgba(0, 0, 0, 0.4);
    }

    .summary__label {
      line-height: 16px;
      color: rgba(0, 0, 0, 0.54);
      width: 100px;
      height: 20px;
    }

    .summary__value {
      padding-left: 8px;
    }

    .code {
      background-color: #F5F5F5;
      padding: 8px;
      font-family: Menlo, Consolas, Monaco, "Courier New", monospace;
    }

    .link {
      color: #1976D2 !important;
      cursor: pointer !important;
      text-decoration: none;
    }

    .footer {
      color: rgba(0, 0, 0, 0.38);
      font-size: 12px;
    }

    .footer td {
      height: 52px;
      background-color: #FAFAFA;
      padding: 0 24px;
    }

    .footer a {
      color: rgba(0, 0, 0, 0.38) !important;
      border-bottom: 1px solid rgba(0, 0, 0, 0.38);
      text-decoration: none;
    }

    .footer__padding {
      height: 32px;
    }

    .text-caption {
      font-size: 12px;
      color: rgba(0, 0, 0, 0.6);
    }

    .text-green {
      color: #9CCC65;
    }

    .text-yellow {
      color: #FBC02D;
    }

    .text-orange {
      color: #FF9800;
    }

    .text-red {
      color: #EF5350;
    }

    .text-brown {
      color: #8D6E63;
    }

    .text-blue {
      color: #42A5F5;
    }

    .text-purple {
      color: #AB47BC;
    }

    .bg-green {
      background-color: #9CCC65;
    }

    .bg-yellow {
      background-color: #FDD835;
    }

    .bg-orange {
      background-color: #FF9800;
    }

    .bg-red {
      background-color: #EF5350;
    }

    .bg-brown {
      background-color: #8D6E63;
    }

    .bg-blue {
      background-color: #42A5F5;
    }

    .bg-purple {
      background-color: #AB47BC;
    }

    .border-green {
      border-color: #9CCC65;
    }

    .border-yellow {
      border-color: #FDD835;
    }

    .border-orange {
      border-color: #FF9800;
    }

    .border-red {
      border-color: #EF5350;
    }

    {{>extra_css}}

    @media screen and (max-width: 600px) {
      .background__cell {
        padding: 0;
      }

      .content {
        border-width: 16px 16px 8px;
        font-size: 16px;
      }

      .logo {
        width: 44px;
        padding-top: 5px;
      }

      .logo--full {
        display: none;
      }

      .logo--icon {
        display: block;
      }
    }

    /* Remove space around the email design. */
    html,
    body {
      margin: 0 auto !important;
      padding: 0 !important;
      height: 100% !important;
      width: 100% !important;
    }

    /* Stop Outlook resizing small text. */
    * {
      -ms-text-size-adjust: 100%;
    }

    /* Stop Outlook from adding extra spacing to tables. */
    table,
    td {
      mso-table-lspace: 0pt !important;
      mso-table-rspace: 0pt !important;
    }

    /* Use a better rendering method when resizing images in Outlook IE. */
    img {
      -ms-interpolation-mode: bicubic;
    }
  </style>
</head>
<body>

<!-- BACKGROUND -->
<table role="presentation"
       cellpadding="32"
       cellspacing="0"
       border="0"
       class="background">
  <tr>
    <td class="background__cell">
      <!-- CONTENT -->
      <table role="presentation"
             cellpadding="2"
             cellspacing="0"
             border="0"
             class="content">

        <!-- HEADER -->
        <tr>
          <td colspan="2">
            <table role="presentation"
                   cellpadding="2"
                   cellspacing="0"
                   border="0"
                   class="header">
              <tr>
                <!-- LOGO -->
                <td class="logo">
                  <!-- for regular screens -->
                  <img
                    src="https://dk-support-external.s3.amazonaws.com/support/dk_logo_horizontal.png"
                    alt="DataKitchen Logo"
                    height="24"
                    class="logo--full">

                  <!-- for smaller screens -->
                  <!--[if !mso]><!-->
                  <img
                    src="https://dk-support-external.s3.amazonaws.com/support/dk_logo.png"
                    alt="DataKitchen Logo"
                    height="40"
                    class="logo--icon">
                  <!--<![endif]-->
                </td>
                <!-- TITLE -->
                <td class="title">{{>title}}</td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td colspan="2" style="white-space: nowrap">
            <!-- MAIN CONTENT -->
            {{>main_content}}
          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td colspan="2"
              class="footer__padding"></td>
        </tr>
        <tr class="footer">
          <td>
            <a href="https://docs.datakitchen.io/articles/#!dataops-testgen-help/introduction-to-dataops-testgen"
               target="_blank">TestGen Help</a>
          </td>
          <td align="right">
            <a href="https://datakitchen.io"
               target="_blank"
               title="DataKitchen website">datakitchen.io</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""
