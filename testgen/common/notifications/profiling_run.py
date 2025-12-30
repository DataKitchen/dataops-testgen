import logging
from urllib.parse import quote

from sqlalchemy import select

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.notification_settings import (
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
)
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.project import Project
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.table_group import TableGroup
from testgen.common.notifications.notifications import BaseNotificationTemplate
from testgen.utils import log_and_swallow_exception

LOG = logging.getLogger("testgen")


class ProfilingRunEmailTemplate(BaseNotificationTemplate):

    def get_subject_template(self) -> str:
        return (
            "[TestGen] Profiling Run {{format_status profiling_run.status}}: {{table_groups_name}}"
            "{{#if issue_count}}"
            ' | {{format_number issue_count}} hygiene {{pluralize issue_count "issue" "issues"}}'
            "{{/if}}"
        )

    def get_title_template(self):
        return """
          TestGen Profiling Run - <span class="
          {{#if (eq profiling_run.status 'Error')}} text-red {{/if}}
          {{#if (eq profiling_run.status 'Cancelled')}} text-purple {{/if}}
          ">{{format_status profiling_run.status}}</span>
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
                  <td class="summary__value">{{project_name}}</td>
                  <td class="summary__label">Schema</td>
                  <td class="summary__value">{{table_group_schema}}</td>
                  <td align="right">
                    <a class="link" href="{{profiling_run.results_url}}" target="_blank">View results on TestGen &gt;</a>
                  </td>

                </tr>
                <tr>
                  <td class="summary__label">Table Group</td>
                  <td class="summary__value"><b>{{table_groups_name}}</b>   </td>
                  <td class="summary__label">Tables</td>
                  <td class="summary__value">{{format_number profiling_run.table_ct}}</td>
                </tr>
                <tr>
                  <td class="summary__label">Start Time</td>
                  <td class="summary__value">{{format_dt profiling_run.start_time}}</td>
                  <td class="summary__label">Columns</td>
                  <td class="summary__value">{{format_number profiling_run.column_ct}}</td>
                </tr>
                <tr>
                  <td class="summary__label">Duration</td>
                  <td class="summary__value">{{format_duration profiling_run.start_time profiling_run.end_time}}</td>
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
                  <td class="summary__title">Issues Summary</td>
                  {{#if (eq profiling_run.status 'Complete')}}
                  <td align="right">
                    <a class="link" href="{{profiling_run.issues_url}}" target="_blank">View {{format_number issue_count}} issues &gt;</a>
                  </td>
                  {{/if}}
                </tr>
                <tr>
                  <td class="summary__subtitle">
                    {{#if (eq profiling_run.status 'Complete')}}
                        {{#if (eq notification_trigger 'on_changes')}}
                            Profiling run detected new hygiene issues.
                        {{/if}}
                        {{#if (eq notification_trigger 'always')}}
                            {{#if issue_count}}
                                Profiling run detected hygiene issues.
                            {{/if}}
                        {{/if}}
                    {{/if}}
                    {{#if (eq profiling_run.status 'Error')}}
                        Profiling encountered an error.
                    {{/if}}
                    {{#if (eq profiling_run.status 'Cancelled')}}
                        Profiling run was canceled.
                    {{/if}}
                  </td>
                </tr>
                {{#if (eq profiling_run.status 'Complete')}}
                <tr>
                  <td colspan="2" style="padding-top: 12px; padding-bottom: 12px;">
                    <table cellspacing="0" cellpadding="0">
                      <tr class="tg-summary-header">
                        <td colspan="3">Hygiene Issues</td>
                        <td colspan="2">Potential PII (Risk)</td>
                      </tr>
                      <tr class="tg-summary-counts">
                        {{#each hygiene_issues_summary}}
                        <td class="
                            {{#if (eq priority 'Definite')}} border-red {{/if}}
                            {{#if (eq priority 'Likely')}} border-orange {{/if}}
                            {{#if (eq priority 'Possible')}} border-yellow {{/if}}
                            {{#if (eq priority 'High')}} border-red {{/if}}
                            {{#if (eq priority 'Moderate')}} border-orange {{/if}}
                        "
                        {{#if (eq priority 'Possible')}} style="padding-right: 80px;" {{/if}}
                        >
                          <div class="tg-summary-counts-label">{{priority}}</div>
                          <div class="tg-summary-counts-count">{{format_number count.active}}</div>
                        </td>
                        {{/each}}
                      </tr>
                    </table>
                  </td>
                </tr>
                {{/if}}
                {{#if (eq profiling_run.status 'Error')}}
                <tr>
                  <td><div class="code">{{profiling_run.log_message}}</div></td>
                </tr>
                {{/if}}
              </table>
            </div>
            {{#each hygiene_issues_summary}}
              {{>result_table .}}
            {{/each}}
        """

    def get_result_table_template(self):
        return """
          {{#if count.total}}
          <div class="summary" style="padding-left: 4px;">
            <table
              role="presentation"
              cellpadding="2"
              cellspacing="0"
              border="0">
              <tr>
                <td></td>
                <td colspan="2" class="summary__title
                {{#if (eq priority 'Definite')}} text-red {{/if}}
                {{#if (eq priority 'Likely')}} text-orange {{/if}}
                {{#if (eq priority 'Possible')}} text-yellow {{/if}}
                {{#if (eq priority 'High')}} text-red {{/if}}
                {{#if (eq priority 'Moderate')}} text-orange {{/if}}
                ">{{label}}</td>
                <td colspan="2" align="right">
                  <a class="link" href="{{url}}" target="_blank">
                    View {{format_number count.total}} {{label}} &gt;
                  </a>
                </td>
              </tr>
              {{#if (len issues)}}
              <tr class="text-caption">
                <td></td>
                <td>Table</td>
                <td>Columns</td>
                <td>Issue</td>
                <td>Details</td>
              </tr>
              {{#each issues}}
                <tr>
                  <td style="width: 4px;">{{#if is_new}}<span class="text-purple">&#9679;</span>{{/if}}</td>
                  <td>{{truncate 30 table_name}}</td>
                  <td>{{truncate 30 column_name}}</code></td>
                  <td>{{issue_name}}</td>
                  <td style="word-break: break-all;">{{truncate 50 detail}}</td>
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
                  indicates new issues
                </td>
              </tr>
              {{/if}}
            </table>
          </div>
          {{/if}}
        """

    def get_extra_css_template(self) -> str:
        return """
          .tg-summary-header td  {
            padding: 10px 0 10px 0;
            font-size: 14px;
            text-color: rgba(0, 0, 0, 0.54);
          }
          .tg-summary-counts td {
            height: 32px;
            border-left-width: 4px;
            border-left-style: solid;
            padding-left: 8px;
            padding-right: 24px;
            line-height: 1.2;
          }
          .tg-summary-counts-label {
            font-size: 12px;
            text-color: rgba(0, 0, 0, 0.54);
          }
          .tg-summary-counts-count {
            font-size: 16px;
          }
        """


@log_and_swallow_exception
@with_database_session
def send_profiling_run_notifications(profiling_run: ProfilingRun, result_list_ct=20):
    notifications = list(
        ProfilingRunNotificationSettings.select(enabled=True, table_group_id=profiling_run.table_groups_id)
    )
    if not notifications:
        return

    previous_run = profiling_run.get_previous()
    issues = list(
        HygieneIssue.select_with_diff(
            profiling_run.id,
            previous_run.id if previous_run else None,
            limit=result_list_ct,
        )
    )

    triggers = {ProfilingRunNotificationTrigger.always}
    if profiling_run.status in ("Error", "Cancelled") or {None, True} & {is_new for _, is_new in issues}:
        triggers.add(ProfilingRunNotificationTrigger.on_changes)

    notifications = [ns for ns in notifications if ns.trigger in triggers]
    if not notifications:
        return

    profiling_run_issues_url = "".join(
        (PersistedSetting.get("BASE_URL", ""), "/profiling-runs:hygiene?run_id=", str(profiling_run.id))
    )

    hygiene_issues_summary = []
    counts = HygieneIssue.select_count_by_priority(profiling_run.id)
    for priority, likelihood, label in (
            ("Definite", "Definite", "definite issues"),
            ("Likely", "Likely", "likely issues"),
            ("Possible", "Possible", "possible issues"),
            ("High", "Potential PII", "potential PII - high risk"),
            ("Moderate", "Potential PII", "potential PII - moderate risk"),
    ):
        context_issues = [
            {
                "is_new": is_new,
                "detail": issue.detail,
                "table_name": issue.table_name,
                "column_name": issue.column_name,
                "issue_name": issue.type_.name,
            }
            for issue, is_new in issues
            if issue.priority == priority
        ]

        hygiene_issues_summary.append(
            {
                "label": label,
                "priority": priority,
                "url": f"{profiling_run_issues_url}&likelihood={quote(likelihood)}",
                "count": counts[priority],
                "issues": context_issues,
                "truncated": counts[priority].active - len(context_issues),
            }
        )

    labels_query = (
        select(Project.project_name, TableGroup.table_groups_name, TableGroup.table_group_schema)
        .select_from(TableGroup)
        .join(Project)
        .where(TableGroup.id == profiling_run.table_groups_id)
    )
    context = {
        "profiling_run": {
            "id": str(profiling_run.id),
            "issues_url": profiling_run_issues_url,
            "results_url": "".join(
                (PersistedSetting.get("BASE_URL", ""), "/profiling-runs:results?run_id=", str(profiling_run.id))
            ),
            "start_time": profiling_run.profiling_starttime,
            "end_time": profiling_run.profiling_endtime,
            "status": profiling_run.status,
            "log_message": profiling_run.log_message,
            "table_ct": profiling_run.table_ct,
            "column_ct": profiling_run.column_ct,
        },
        "issue_count": sum(c.total for c in counts.values()),
        "hygiene_issues_summary": hygiene_issues_summary,
        **dict(get_current_session().execute(labels_query).one()),
    }

    for ns in notifications:
        try:
            ProfilingRunEmailTemplate().send(
                ns.recipients, {**context, "notification_trigger": ns.trigger.value}
            )
        except Exception:
            LOG.exception("Failed sending test run email notifications")
