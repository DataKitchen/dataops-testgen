import logging

from sqlalchemy import case, literal, select

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.notification_settings import TestRunNotificationSettings, TestRunNotificationTrigger
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import TestResult, TestResultStatus
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.notifications import BaseNotificationTemplate

LOG = logging.getLogger("testgen")



class TestRunEmailTemplate(BaseNotificationTemplate):

    def get_subject_template(self) -> str:
        return (
            "[TestGen] Test Run {{test_run.status}}: {{test_run.test_suite}}"
            "{{#with test_run}}"
            '{{#if failed_ct}} | {{failed_ct}} {{pluralize failed_ct "failure" "failures"}}{{/if}}'
            '{{#if warning_ct}} | {{warning_ct}} {{pluralize warning_ct "warning" "warnings"}}{{/if}}'
            '{{#if error_ct}} | {{error_ct}} {{pluralize error_ct "error" "errors"}}{{/if}}'
            "{{/with}}"
        )

    def get_title_template(self):
        return "Test Run {{ test_run.status }}"

    def get_main_content_template(self):
        return """
            <div class="summary">
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                <tr>
                  <td colspan="4" class="summary__title">
                    {{ test_run.project_name }} <b>|</b>
                    {{ test_run.table_groups_name }} <b>|</b>
                    {{ test_run.test_suite }} <b>|</b>
                    Test Run <a
                      href="{{ test_run_url }}"
                      target="_blank">
                      {{truncate 8 test_run_id}}
                    </a>
                  </td>
                </tr>
                <tr>
                  <td colspan="4" class="summary__subtitle">
                    {{#if (eq test_run.status 'Complete')}}
                        {{#if (eq notification_trigger 'on_changes')}}
                            The test results from this run are different from the previous run.
                        {{/if}}
                        {{#if (eq notification_trigger 'on_failures')}}
                            There are failures or errors among the test results.
                        {{/if}}
                        {{#if (eq notification_trigger 'on_warnings')}}
                            There are failures, warnings or errors among the test results.
                        {{/if}}
                    {{/if}}
                    {{#if (eq test_run.status 'Error')}}
                        The test run did not complete successfully
                    {{/if}}
                    {{#if (eq test_run.status 'Cancelled')}}
                        The test run has been cancelled
                    {{/if}}
                  </td>
                </tr>
                <tr>
                  <td class="summary__label">Start Time</td>
                  <td class="summary__value">{{format_dt test_run.test_starttime}}</td>
                  {{#if (eq test_run.status 'Complete')}}
                  <td class="summary__label">Passed</td>
                  <td class="summary__value_mono">{{ test_run.passed_ct }}</td>
                  {{/if}}
                </tr>
                <tr>
                  <td class="summary__label">End Time</td>
                  <td class="summary__value">{{format_dt test_run.test_endtime}}</td>
                  {{#if (eq test_run.status 'Complete')}}
                  <td class="summary__label">Failed</td>
                  <td class="summary__value_mono">{{ test_run.failed_ct }}</td>
                  {{/if}}
                </tr>
                {{#if (eq test_run.status 'Complete')}}
                <tr>
                  <td class="summary__label"></td>
                  <td class="summary__value"></td>
                  <td class="summary__label">Warning</td>
                  <td class="summary__value_mono">{{ test_run.warning_ct }}</td>
                </tr>
                <tr>
                  <td class="summary__label"></td>
                  <td class="summary__value"></td>
                  <td class="summary__label">Error</td>
                  <td class="summary__value_mono">{{ test_run.error_ct }}</td>
                </tr>
                <tr>
                  <td class="summary__label">Score</td>
                  <td class="summary__value_mono">{{ test_run.dq_score_testing_decimal }}</td>
                  <td class="summary__label">Log</td>
                  <td class="summary__value_mono">{{ test_run.log_ct }}</td>
                </tr>
                <tr>
                  <td class="summary__label">Total Tests</td>
                  <td class="summary__value_mono">{{ test_run.test_ct }}</td>
                  <td class="summary__label">Dismissed</td>
                  <td class="summary__value_mono">{{ test_run.dismissed_ct }}</td>
                </tr>
                {{/if}}
              </table>
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                {{#each test_result_summary}}
                    {{>result_table .}}
                {{/each}}
              </table>
            </div>"""

    def get_result_table_template(self):
        return """
          {{#if length }}
            <tr class="summary_section">
              <td class="summary__label" colspan="2">{{label}}</td>
              <td class="summary__value" colspan="3" style="font-size: 8pt; text-align: right;">
                {{#if truncated}}
                Showing {{length}} out of {{total}} {{label}}
                {{/if}}
              </td>
            </tr>
            {{#each result_list}}
              <tr>
                <td>{{#if is_new}}<span style="color: red">&#9679;</span>{{/if}}</td>
                <td><code>{{table_name}}</code></td>
                <td><code>{{truncate 30 column_names}}</code></td>
                <td>{{test_type}}</td>
                <td style="word-break: break-all;">{{truncate 50 message}}</td>
              </tr>
            {{/each}}
          {{/if}}
        """


@with_database_session
def send_test_run_notifications(test_run: TestRun, result_list_ct=20, result_status_min=5):

    notifications = list(TestRunNotificationSettings.select(enabled=True, test_suite_id=test_run.test_suite_id))
    if not notifications:
        return

    changed_td_id_list = []
    triggers = {TestRunNotificationTrigger.always}

    if test_run.status in ("Error", "Cancelled"):
        triggers.update(TestRunNotificationTrigger)
    else:
        if previous_run := TestRun.get_previous(test_run):
            for _, status, td_id_list in TestResult.diff(previous_run.id, test_run.id):
                if status in (TestResultStatus.Failed, TestResultStatus.Warning, TestResultStatus.Error):
                    changed_td_id_list.extend(td_id_list)

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
        (TestResultStatus.Failed, "Failures"),
        (TestResultStatus.Warning, "Warnings"),
        (TestResultStatus.Error, "Errors"),
    )

    if test_run.status == "Complete":
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
                "length": len(result_list),
                "total": test_run.ct_by_status[status],
                "result_list": result_list,
                "truncated": len(result_list) < test_run.ct_by_status[status],
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
