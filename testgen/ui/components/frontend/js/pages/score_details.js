/**
 * @import { Score } from '/app/static/js/components/score_card.js';
 *
 * @typedef Dimension
 * @type {object}
 * @property {string} label
 * @property {number} score
 *
 * @typedef ResultSet
 * @type {object}
 * @property {Array<string>} columns
 * @property {Array<object>} items
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {('table_name' | 'column_name' | 'semantic_data_type' | 'dq_dimension')} category
 * @property {('score' | 'cde_score')} score_type
 * @property {any} drilldown
 * @property {Score} score
 * @property {ResultSet?} breakdown
 * @property {ResultSet?} issues
 * @property {Permissions} permissions
 * @property {object?} notifications_dialog
 */
import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { ScoreCard } from '/app/static/js/components/score_card.js';
import { ScoreHistory } from '/app/static/js/components/score_history.js';
import { ScoreLegend } from '/app/static/js/components/score_legend.js';
import { ScoreBreakdown } from '/app/static/js/components/score_breakdown.js';
import { IssuesTable } from '/app/static/js/components/score_issues.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { NotificationSettings } from '/app/static/js/components/notification_settings.js';
import { ProfilingResultsDialog } from '../shared/profiling_results_dialog.js';

const { b, div, i } = van.tags;

const ScoreDetails = (/** @type {Properties} */ props) => {
    loadStylesheet('score-details', stylesheet);

    const deleteDialogOpen = van.state(false);
    const notificationsDialogOpen = van.state(false);

    const smtpConfigured = van.derive(() => getValue(props.notifications_dialog)?.smtp_configured ?? false)
    const event = van.derive(() => getValue(props.notifications_dialog)?.event)
    const items = van.derive(() => getValue(props.notifications_dialog)?.items ?? [])
    const permissions = van.derive(() => getValue(props.notifications_dialog)?.permissions ?? { can_edit: false })
    const scopeLabel = van.derive(() => getValue(props.notifications_dialog)?.scope_label)
    const scopeOptions = van.derive(() => getValue(props.notifications_dialog)?.scope_options ?? [])
    const triggerOptions = van.derive(() => getValue(props.notifications_dialog)?.trigger_options ?? [])
    const cdeEnabled = van.derive(() => getValue(props.notifications_dialog)?.cde_enabled ?? false)
    const totalEnabled = van.derive(() => getValue(props.notifications_dialog)?.total_enabled ?? false)
    const result = van.derive(() => getValue(props.notifications_dialog)?.result)

    van.derive(() => { if (getValue(props.notifications_dialog)?.open === true) notificationsDialogOpen.val = true; });

    return div(
        { 'data-testid': 'score-details', class: 'tg-score-details flex-column' },
        ScoreLegend(),
        div(
            { class: 'flex-row fx-flex-wrap fx-gap-4 mb-4 mt-4'},
            ScoreCard(
                props.score,
                () => {
                    const score = getValue(props.score);
                    return getValue(props.permissions)?.can_edit ?? false ? div(
                        { class: 'flex-row tg-test-suites--card-actions' },
                        Button({ type: 'icon', icon: 'notifications', tooltip: 'Configure Notifications', onclick: () => emitEvent('EditNotifications', {}) }),
                        Button({ type: 'icon', icon: 'edit', tooltip: 'Edit Scorecard', onclick: () => emitEvent('LinkClicked', { href: 'quality-dashboard:explorer', params: { definition_id: score.id, project_code: score.project_code } }) }),
                        Button({ type: 'icon', icon: 'delete', tooltip: 'Delete Scorecard', onclick: () => { deleteDialogOpen.val = true; } }),
                    ) : '';
                },
            ),
            () => {
                const score = getValue(props.score);
                const history = getValue(props.score).history;
                return history?.length > 0
                    ? ScoreHistory({style: 'min-height: 216px; flex: 610px 0 1;', showRefresh: getValue(props.permissions)?.can_edit ?? false, score}, ...history)
                    : null;
            },
        ),
        () => {
            const issuesValue = getValue(props.issues);
            return (
                (issuesValue && getValue(props.drilldown))
                ? IssuesTable(
                    issuesValue?.items,
                    issuesValue?.columns,
                    getValue(props.score),
                    getValue(props.score_type),
                    getValue(props.category),
                    getValue(props.drilldown),
                    (project_code, name, score_type, category) => emitEvent('LinkClicked', { href: 'quality-dashboard:score-details', params: { definition_id: getValue(props.score).id, project_code, score_type, category } }),
                )
                : ScoreBreakdown(
                    props.score,
                    props.breakdown,
                    props.category,
                    props.score_type,
                    (project_code, name, score_type, category, drilldown) => emitEvent(
                        'LinkClicked',
                        { href: 'quality-dashboard:score-details', params: { definition_id: getValue(props.score).id, project_code, score_type, category, drilldown }
                    }),
                )
            );
        },
        Dialog(
            { title: 'Delete Scorecard', open: deleteDialogOpen, onClose: () => deleteDialogOpen.val = false },
            div(
                { class: 'flex-column fx-gap-4' },
                () => {
                    const score = getValue(props.score);
                    return div('Are you sure you want to delete the scorecard ', b(score.name), '?');
                },
                div(
                    { class: 'flex-row fx-justify-flex-end' },
                    Button({
                        label: 'Delete',
                        color: 'warn',
                        type: 'flat',
                        onclick: () => {
                            emitEvent('DeleteScoreConfirmed', { payload: getValue(props.score).id });
                            deleteDialogOpen.val = false;
                        },
                    }),
                ),
            ),
        ),
        Dialog(
            {
                title: 'Scorecard Notifications',
                open: notificationsDialogOpen,
                onClose: () => {
                    notificationsDialogOpen.val = false;
                    emitEvent('NotificationsDialogClosed', {})
                },
                width: '65rem',
            },
            NotificationSettings({
                smtp_configured: smtpConfigured,
                event: event,
                items: items,
                permissions: permissions,
                scope_label: scopeLabel,
                scope_options: scopeOptions,
                trigger_options: triggerOptions,
                cde_enabled: cdeEnabled,
                total_enabled: totalEnabled,
                result: result,
            }),
        ),
        ProfilingResultsDialog({
            profilingColumn: props.profiling_column,
            onClose: () => emitEvent('ProfilingResultsDialogClosed', {}),
        }),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-details {
    min-height: 900px;
}
`);

export { ScoreDetails };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, ScoreDetails(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        parentElement.state = null;
        Streamlit.disableV2(setTriggerValue);
    };
};
