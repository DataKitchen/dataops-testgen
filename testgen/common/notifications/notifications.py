from datetime import datetime

from testgen.common.notifications.base import BaseEmailTemplate


class BaseNotificationTemplate(BaseEmailTemplate):

    def pluralize_helper(self, count: int, singular: str, plural: str):
        return singular if count == 1 else plural

    def format_dt_helper(self, dt: datetime):
        return dt.strftime("%b %d %I:%M %p")

    def truncate_helper(self, length: int, text: str):
        return text if len(text) <= length else f"{text[:length-1]}…"

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
      max-width: 800px;
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
      padding: 4px 16px 16px;
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
      text-align: center;
      color: rgba(0, 0, 0, 0.87);
      padding: 20px 0 5px 0;
    }

    .summary__subtitle {
        font-size: 12px;
        font-style: italic;
        color: rgba(0, 0, 0, 0.6);
        text-align: center;
        padding: 5px 0 15px 0;
    }

    .summary__title b {
      color: rgba(0, 0, 0, 0.30);
      padding: 0 5px;
    }

    .summary__label {
      line-height: 16px;
      color: rgba(0, 0, 0, 0.54);
      width: 100px;
      height: 20px;
    }

    .summary_section td {
      padding-top: 25px;
    }

    .summary__value_mono {
      padding-left: 8px;
      font-family: Menlo, Consolas, Monaco, "Courier New", monospace;
    }

    .summary__value {
      padding-left: 8px;
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
          <td>TestGen</td>
          <td align="right">
            <a href="http://datakitchen.io"
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
