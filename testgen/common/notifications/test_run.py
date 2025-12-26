import logging

from sqlalchemy import case, literal, select

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.notification_settings import TestRunNotificationSettings, TestRunNotificationTrigger
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import TestResult, TestResultStatus
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.notifications import BaseNotificationTemplate
from testgen.utils import log_and_swallow_exception

LOG = logging.getLogger("testgen")


class TestRunEmailTemplate(BaseNotificationTemplate):

    def get_subject_template(self) -> str:
        return (
            "[TestGen] Test Run {{format_status test_run.status}}: {{test_run.test_suite}}"
            "{{#with test_run}}"
            '{{#if failed_ct}} | {{format_number failed_ct}} {{pluralize failed_ct "failure" "failures"}}{{/if}}'
            '{{#if warning_ct}} | {{format_number warning_ct}} {{pluralize warning_ct "warning" "warnings"}}{{/if}}'
            '{{#if error_ct}} | {{format_number error_ct}} {{pluralize error_ct "error" "errors"}}{{/if}}'
            "{{/with}}"
        )

    def get_title_template(self):
        return """
          TestGen Test Run - <span class="
          {{#if (eq test_run.status 'Error')}} text-red {{/if}}
          {{#if (eq test_run.status 'Cancelled')}} text-purple {{/if}}
          ">{{format_status test_run.status}}</span>
        """

    def get_main_content_template(self):
        return """
            <div class="summary">
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                <tr>
                  <td class="summary__label">Project</td>
                  <td class="summary__value">{{test_run.project_name}}</td>
                </tr>
                <tr>
                  <td class="summary__label">Table Group</td>
                  <td class="summary__value">{{test_run.table_groups_name}}</td>
                </tr>
                <tr>
                  <td class="summary__label">Test Suite</td>
                  <td class="summary__value"><b>{{test_run.test_suite}}</b></td>
                </tr>
                <tr>
                  <td class="summary__label">Start Time</td>
                  <td class="summary__value">{{format_dt test_run.test_starttime}}</td>
                </tr>
                <tr>
                  <td class="summary__label">Duration</td>
                  <td class="summary__value">{{format_duration test_run.test_starttime test_run.test_endtime}}</td>
                </tr>
              </table>
            </div>
            <div class="summary">
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                <tr>
                  <td class="summary__title">Results Summary</td>
                  {{#if (eq test_run.status 'Complete')}}
                  <td align="right">
                    <a class="link" href="{{test_run_url}}" target="_blank">View on TestGen &gt;</a>
                  </td>
                  {{/if}}
                </tr>
                <tr>
                  <td class="summary__subtitle">
                    {{#if (eq test_run.status 'Complete')}}
                        {{#if (eq notification_trigger 'on_changes')}}
                            Test run has new failures, warnings, or errors.
                        {{/if}}
                        {{#if (eq notification_trigger 'on_failures')}}
                            Test run has failures or errors.
                        {{/if}}
                        {{#if (eq notification_trigger 'on_warnings')}}
                            Test run has failures, warnings, or errors.
                        {{/if}}
                    {{/if}}
                    {{#if (eq test_run.status 'Error')}}
                        Test execution encountered an error.
                    {{/if}}
                    {{#if (eq test_run.status 'Cancelled')}}
                        Test run was canceled.
                    {{/if}}
                  </td>
                </tr>
                {{#if (eq test_run.status 'Complete')}}
                <tr>
                  <td colspan="2" style="padding-top: 12px; padding-bottom: 12px;">
                    <table cellspacing="0" cellpadding="0" class="tg-summary-bar">
                      <tr>
                        <td class="bg-green" style="width: {{percentage test_run.passed_ct test_run.test_ct}}%;">&nbsp;</td>
                        <td class="bg-yellow" style="width: {{percentage test_run.warning_ct test_run.test_ct}}%;">&nbsp;</td>
                        <td class="bg-red" style="width: {{percentage test_run.failed_ct test_run.test_ct}}%;">&nbsp;</td>
                        <td class="bg-brown" style="width: {{percentage test_run.error_ct test_run.test_ct}}%;">&nbsp;</td>
                        <td class="bg-blue" style="width: {{percentage test_run.log_ct test_run.test_ct}}%;">&nbsp;</td>
                      </tr>
                    </table>
                    <div class="tg-summary-bar--caption">
                      <span class="tg-summary-bar--legend">
                        <span class="tg-summary-bar--legend-dot text-green">&#9679;</span>
                        Passed: {{format_number test_run.passed_ct}}
                      </span>
                      <span class="tg-summary-bar--legend">
                        <span class="tg-summary-bar--legend-dot text-yellow">&#9679;</span>
                        Warning: {{format_number test_run.warning_ct}}
                      </span>
                      <span class="tg-summary-bar--legend">
                        <span class="tg-summary-bar--legend-dot text-red">&#9679;</span>
                        Failed: {{format_number test_run.failed_ct}}
                      </span>
                      <span class="tg-summary-bar--legend">
                        <span class="tg-summary-bar--legend-dot text-brown">&#9679;</span>
                        Error: {{format_number test_run.error_ct}}
                      </span>
                      <span class="tg-summary-bar--legend">
                        <span class="tg-summary-bar--legend-dot text-blue">&#9679;</span>
                        Log: {{format_number test_run.log_ct}}
                      </span>
                    </div>
                  </td>
                </tr>
                {{/if}}
                {{#if (eq test_run.status 'Error')}}
                <tr>
                  <td><div class="code">{{test_run.log_message}}</div></td>
                </tr>
                {{/if}}
              </table>
            </div>
            {{#each test_result_summary}}
              {{>result_table .}}
            {{/each}}
        """

    def get_result_table_template(self):
        return """
          {{#if total}}
          <div class="summary" style="padding-left: 4px;">
            <table
              role="presentation"
              cellpadding="2"
              cellspacing="0"
              border="0">
              <tr>
                <td></td>
                <td colspan="2" class="summary__title
                {{#if (eq status 'Failed')}} text-red {{/if}}
                {{#if (eq status 'Warning')}} text-orange {{/if}}
                {{#if (eq status 'Error')}} text-brown {{/if}}
                ">{{label}}</td>
                <td colspan="2" align="right">
                  <a class="link" href="{{test_run_url}}&status={{status}}" target="_blank">
                    View {{format_number total}} {{label}} &gt;
                  </a>
                </td>
              </tr>
              <tr class="text-caption">
                <td></td>
                <td>Table</td>
                <td>Columns/Focus</td>
                <td>Test Type</td>
                <td>Details</td>
              </tr>
              {{#each result_list}}
                <tr>
                  <td style="width: 4px;">{{#if is_new}}<span class="text-purple">&#9679;</span>{{/if}}</td>
                  <td>{{truncate 30 table_name}}</td>
                  <td>{{truncate 30 column_names}}</code></td>
                  <td>{{test_type}}</td>
                  <td style="word-break: break-all;">{{truncate 50 message}}</td>
                </tr>
              {{/each}}
              <tr>
                <td></td>
                <td colspan="2" class="summary__caption">
                  {{#if truncated}}
                  + {{truncated}} more
                  {{/if}}
                </td>
                <td colspan="2" align="right" class="summary__caption">
                  <span class="text-purple" style="margin-right: 4px; font-style: normal;">&#9679;</span>
                  indicates new {{label}}
                </td>
              </tr>
            </table>
          </div>
          {{/if}}
        """

    def get_extra_css_template(self) -> str:
        return """
          .tg-summary-bar {
            width: 350px;
            border-radius: 4px;
            overflow: hidden;
          }

          .tg-summary-bar td {
            height: 10px;
            padding: 0;
            line-height: 10px;
            font-size: 0;
          }

          .tg-summary-bar--caption {
            margin-top: 4px;
            color: var(--caption-text-color);
            font-size: 13px;
            font-style: italic;
            line-height: 1;
          }

          .tg-summary-bar--legend {
            width: auto;
            margin-right: 8px;
          }

          .tg-summary-bar--legend-dot {
            margin-right: 2px;
            font-style: normal;
          }
        """


@log_and_swallow_exception
@with_database_session
def send_test_run_notifications(test_run: TestRun, result_list_ct=20, result_status_min=5):

    notifications = list(TestRunNotificationSettings.select(enabled=True, test_suite_id=test_run.test_suite_id))
    if not notifications:
        return

    changed_td_id_list = []
    if previous_run := test_run.get_previous():
        for _, status, td_id_list in TestResult.diff(previous_run.id, test_run.id):
            if status in (TestResultStatus.Failed, TestResultStatus.Warning, TestResultStatus.Error):
                changed_td_id_list.extend(td_id_list)

    triggers = {TestRunNotificationTrigger.always}
    if test_run.status in ("Error", "Cancelled"):
        triggers.update(TestRunNotificationTrigger)
    else:
        if test_run.error_ct + test_run.failed_ct:
            triggers.update({TestRunNotificationTrigger.on_failures, TestRunNotificationTrigger.on_warnings})
        elif test_run.warning_ct:
            triggers.add(TestRunNotificationTrigger.on_warnings)
        if changed_td_id_list:
            triggers.add(TestRunNotificationTrigger.on_changes)

    notifications = [ns for ns in notifications if ns.trigger in triggers]
    if not notifications:
        return

    result_list_by_status = {}
    summary_statuses = (
        (TestResultStatus.Failed, "failures"),
        (TestResultStatus.Warning, "warnings"),
        (TestResultStatus.Error, "errors"),
    )

    changed_case = case(
        (TestResult.test_definition_id.in_(changed_td_id_list), literal(True)),
        else_=literal(False),
    )
    result_count_by_status = {
        status: min(result_status_min, test_run.ct_by_status[status])
        for status, _ in summary_statuses
    }

    for status, _ in summary_statuses:
        result_count_by_status[status] += min(
            (
                result_list_ct - sum(result_count_by_status.values()),
                test_run.ct_by_status[status] - result_count_by_status[status],
            )
        )

        if not result_count_by_status[status]:
            continue

        query = (
            select(
                TestResult.table_name,
                TestResult.column_names,
                TestResult.message,
                changed_case.label("is_new"),
                TestType.test_name_short.label("test_type"),
            )
            .join(TestType, TestType.test_type == TestResult.test_type)
            .where(TestResult.test_run_id == test_run.id, TestResult.status == status)
            .order_by(changed_case.desc())
            .limit(result_count_by_status[status])
        )

        result_list_by_status[status] = [{**r} for r in get_current_session().execute(query)]

    tr_summary, = TestRun.select_summary(test_run_ids=[test_run.id])

    context = {
        "test_run": tr_summary,
        "test_run_url": "".join(
            (
                PersistedSetting.get("BASE_URL", ""),
                "/test-runs:results?run_id=",
                str(test_run.id),
            )
        ),
        "test_run_id": str(test_run.id),
        "test_result_summary": [
            {
                "status": status.value,
                "label": label,
                "total": test_run.ct_by_status[status],
                "truncated": test_run.ct_by_status[status] - len(result_list),
                "result_list": result_list,
            }
            for status, label in summary_statuses
            if (result_list := result_list_by_status.get(status, None))
        ]
    }

    for ns in notifications:
        try:
            TestRunEmailTemplate().send(
                ns.recipients, {**context, "notification_trigger": ns.trigger.value}
            )
        except Exception:
            LOG.exception("Failed sending test run email notifications")
