import logging
from collections import defaultdict

from sqlalchemy import select

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.notification_settings import ScoreDropNotificationSettings
from testgen.common.models.project import Project
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.settings import PersistedSetting
from testgen.common.notifications.notifications import BaseNotificationTemplate
from testgen.utils import log_and_swallow_exception

LOG = logging.getLogger("testgen")


class ScoreDropEmailTemplate(BaseNotificationTemplate):

    def score_color_helper(self, score: float) -> str:
        if score >= 0.96:
            return "green"
        if score >= 0.91:
            return "yellow"
        if score >= 0.86:
            return "orange"
        return "red"

    def get_subject_template(self) -> str:
        return (
            "[TestGen] Quality Score Dropped: {{ definition.name }}"
            "{{#each diff}}{{#if notify}} | {{ label }}: {{ format_score current }}{{/if}}{{/each}}"
        )

    def get_title_template(self):
        return "Quality Score dropped below threshold"

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
                  <td align="right">
                    <a class="link" href="{{scorecard_url}}" target="_blank">View on TestGen &gt;</a>
                  </td>
                </tr>
                <tr>
                  <td class="summary__label">Scorecard</td>
                  <td class="summary__value"><b>{{definition.name}}</b></td>
                </tr>
                <tr>
                  <td class="summary__subtitle" colspan="2" style="padding-top: 8px; padding-bottom: 12px;">
                  {{#each diff}}
                  {{#if notify}}
                  <div>{{label}} score dropped below <u>{{threshold}}</u>.</div>
                  {{/if}}
                  {{/each}}
                  </td>
                </tr>
              </table>
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0"
                style="width: auto;">
                <tr>
                {{#each diff}}
                  <td width="100" height="100" class="score border-{{score_color current}}">
                      <div class="score__value">{{format_score current}}</div>
                      <div class="score__label">{{label}} Score</div>
                      {{#if decrease}}
                      <div class="text-red">&darr; {{format_score decrease}}</div>
                      {{/if}}
                      {{#if increase}}
                      <div class="text-green">&uarr; {{format_score increase}}</div>
                      {{/if}}
                  </td>
                  <td width="16"></td>
                {{/each}}
                </tr>
              </table>
            </div>"""

    def get_extra_css_template(self) -> str:
        return """
            .score {
              display: block;
              width: 100px;
              height: 100px;
              border-radius: 50%;
              border-width: 4px;
              border-style: solid;
              text-align: center;
              font-size: 14px;
            }

            .score__value {
              margin-top: 22px;
              margin-bottom: 2px;
              font-size: 18px;
            }

            .score__label {
              font-size: 14px;
              color: rgba(0, 0, 0, 0.6);
            }
        """


@log_and_swallow_exception
@with_database_session
def send_score_drop_notifications(notification_data: list[tuple[ScoreDefinition, str, float, float]]):

    if not notification_data:
        return

    query = select(
        ScoreDropNotificationSettings,
        Project.project_name,
    ).join(
        Project, ScoreDropNotificationSettings.project_code == Project.project_code
    ).where(
        ScoreDropNotificationSettings.enabled.is_(True),
        ScoreDropNotificationSettings.score_definition_id.in_({d.id for d, *_ in notification_data}),
    )
    ns_per_score_id = defaultdict(list)
    project_name = None
    for (ns, project_name) in get_current_session().execute(query).fetchall():
        ns_per_score_id[ns.score_definition_id].append(ns)
        project_name = project_name

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
                    "decrease": max(diff[0] - diff[1], 0),
                    "increase": max(diff[1] - diff[0], 0),
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
                "project_name": project_name,
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
