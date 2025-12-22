import logging
from collections import defaultdict

from sqlalchemy import select

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.notification_settings import ScoreDropNotificationSettings
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.settings import PersistedSetting
from testgen.common.notifications.notifications import BaseNotificationTemplate
from testgen.utils import log_and_swallow_exception

LOG = logging.getLogger("testgen")


class ScoreDropEmailTemplate(BaseNotificationTemplate):

    def get_subject_template(self) -> str:
        return (
            "[TestGen] Quality Score Dropped: {{ definition.name }}"
            "{{#each diff}}{{#if notify}} | {{ label }}: {{ format_score current }}{{/if}}{{/each}}"
        )

    def get_title_template(self):
        return "{{ definition.name }} Quality Score Dropped"

    def get_main_content_template(self):
        return """
            <div class="summary">
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                <tr>
                  <td colspan="2" align="right">
                    <a class="link" href="{{scorecard_url}}" target="_blank">View on TestGen &gt;</a>
                  </td>
                </tr>
                {{#each diff}}
                <tr>
                  <td class="summary__label">{{ label }} Score</td>
                  <td class="summary__value_score">
                    <span>{{ format_score prev }}</span>
                    <span style="font-size: 24px;">&rarr;</span>
                    <span>{{ format_score current }}</span>
                    <span class="threshold {{#if notify}}notify{{/if}}">&darr;{{ threshold }}</span>
                  </td>
                </tr>
                {{/each}}
              </table>
            </div>"""

    def get_extra_css_template(self) -> str:
        return """
            .summary__value_score span {
              padding-left: 8px;
              font-family: Menlo, Consolas, Monaco, "Courier New", monospace;
              font-size: 16px;
              white-space: pre;
          }

          .summary__value_score span.threshold {
              font-size: 12px;
              text-color: #CCC;
          }

          .summary__value_score span.notify {
              color: #F44;
          }


        """


@log_and_swallow_exception
@with_database_session
def send_score_drop_notifications(notification_data: list[tuple[ScoreDefinition, str, float, float]]):

    if not notification_data:
        return

    query = select(
        ScoreDropNotificationSettings
    ).where(
        ScoreDropNotificationSettings.enabled.is_(True),
        ScoreDropNotificationSettings.score_definition_id.in_({d.id for d, *_ in notification_data}),
    )
    ns_per_score_id = defaultdict(list)
    for ns in get_current_session().scalars(query):
        ns_per_score_id[ns.score_definition_id].append(ns)

    diff_per_score_id = defaultdict(list)
    for definition, *data in notification_data:
        diff_per_score_id[definition.id].append((definition, *data))

    for score_id in diff_per_score_id.keys() & ns_per_score_id.keys():
        score_diff = diff_per_score_id[score_id]
        definition = score_diff[0][0]
        diff_per_cat = {cat: (prev, curr) for _, cat, prev, curr in score_diff}

        for ns in ns_per_score_id[score_id]:

            threshold_by_cat = {
                "score": ns.total_score_threshold,
                "cde_score": ns.cde_score_threshold,
            }

            context_diff = [
                {
                    "category": cat,
                    "label": {"score": "Total", "cde_score": "CDE"}[cat],
                    "prev": diff[0],
                    "current": diff[1],
                    "threshold": threshold_by_cat[cat],
                    "notify": (
                        diff[0] > diff[1]
                        and threshold_by_cat[cat] is not None
                        and diff[1] * 100 < threshold_by_cat[cat]
                    ),
                }
                for cat, diff in diff_per_cat.items()
            ]

            if not any(d["notify"] for d in context_diff):
                continue

            context = {
                "definition": definition,
                "scorecard_url": "".join(
                    (
                        PersistedSetting.get("BASE_URL", ""),
                        "/quality-dashboard:score-details?definition_id=",
                        str(definition.id),
                    )
                ),
                "diff": context_diff,
            }

            try:
                ScoreDropEmailTemplate().send(ns.recipients, context)
            except Exception:
                LOG.exception("Failed sending test run email notifications")


@log_and_swallow_exception
def collect_score_notification_data(
        notification_data: list[tuple[ScoreDefinition, str, float, float]],
        definition: ScoreDefinition,
        fresh_score_card: dict,
) -> None:
    notification_data.extend(
        [
            (definition, r.category, r.score, fresh_score_card[r.category])
            for r in definition.results
            if r.category in ("score", "cde_score") and r.score is not None and fresh_score_card[r.category] is not None
        ]
    )
