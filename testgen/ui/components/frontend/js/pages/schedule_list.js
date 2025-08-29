/**
 * @import {CronSample} from '../components/crontab_input.js'
 * 
 * @typedef Schedule
 * @type {object}
 * @property {string} argValue
 * @property {string} cronExpr
 * @property {string} cronTz
 * @property {string[]} sample
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Results
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * 
 * @typedef Properties
 * @type {object}
 * @property {Schedule[]} items
 * @property {Permissions} permissions
 * @property {string} arg_label
 * @property {import('../components/select.js').Option[]} arg_values
 * @property {CronSample?} sample
 * @property {Results?} results
 */
import van from '../van.min.js';
import { Button } from '../components/button.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { withTooltip } from '../components/tooltip.js';
import { ExpansionPanel } from '../components/expansion_panel.js';
import { Select } from '../components/select.js';
import { CrontabInput } from '../components/crontab_input.js';
import { timezones } from '../values.js';
import { Alert } from '../components/alert.js';

const minHeight = 380;
const { div, span, i } = van.tags;

const ScheduleList = (/** @type Properties */ props) => {
    loadStylesheet('schedule-list', stylesheet);

    window.testgen.isPage = true;

    const scheduleItems = van.derive(() => {
        let items = [];
        try {
            items = JSON.parse(getValue(props.items));
        } catch (e) {
            console.log(e)
        }
        Streamlit.setFrameHeight(Math.max(minHeight, 100 * items.length || 150));
        return items;
    });

    const newScheduleForm = {
        argValue: van.state(''),
        timezone: van.state(Intl.DateTimeFormat().resolvedOptions().timeZone),
        expression: van.state(null),
    };
    const cronEditorValue = van.derive(() => ({
        timezone: newScheduleForm.timezone.val,
        expression: newScheduleForm.expression.val,
    }));

    const columns = ['40%', '50%', '10%'];
    const domId = 'schedules-table';

    return div(
        { id: domId, class: 'flex-column fx-gap-2', style: 'height: 100%; overflow-y: auto;' },
        ExpansionPanel(
            {title: 'Add Schedule', testId: 'scheduler-cron-editor'},
            div(
                { class: 'flex-row fx-gap-2' },
                () => Select({
                    label: getValue(props.arg_label),
                    options: props.arg_values,
                    value: newScheduleForm.argValue,
                    style: 'flex: 1;',
                    onChange: (value) => newScheduleForm.argValue.val = value,
                    portalClass: 'short-select-portal',
                }),
                () => Select({
                    label: 'Timezone',
                    options: timezones.map(tz_ => ({label: tz_, value: tz_})),
                    value: newScheduleForm.timezone,
                    allowNull: false,
                    onChange: (value) => {
                        newScheduleForm.timezone.val = value;
                        if (newScheduleForm.expression.val && newScheduleForm.timezone.val) {
                            emitEvent('GetCronSample', {payload: {cron_expr: newScheduleForm.expression.val, tz: newScheduleForm.timezone.val}});
                        }
                    },
                    portalClass: 'short-select-portal',
                }),
                CrontabInput({
                    class: 'fx-flex',
                    sample: props.sample,
                    value: cronEditorValue,
                    onChange: (value) => {
                        newScheduleForm.expression.val = value;
                        if (newScheduleForm.expression.val && newScheduleForm.timezone.val) {
                            emitEvent('GetCronSample', {payload: {cron_expr: newScheduleForm.expression.val, tz: newScheduleForm.timezone.val}});
                        }
                    },
                }),
            ),
            div(
                { class: 'flex-row fx-justify-content-flex-end mt-3' },
                Button({
                    type: 'stroked',
                    label: 'Add Schedule',
                    width: '150px',
                    onclick: () => emitEvent('AddSchedule', {payload: {
                        arg_value: newScheduleForm.argValue.val,
                        cron_expr: newScheduleForm.expression.val,
                        cron_tz: newScheduleForm.timezone.val,
                    }}),
                }),
            ),
            () => {
                const results = getValue(props.results);
                if (!results) {
                    return '';
                }

                if (results.success) {
                    newScheduleForm.argValue.val = '';
                    newScheduleForm.expression.val = null;
                    newScheduleForm.timezone.val = Intl.DateTimeFormat().resolvedOptions().timeZone;
                }

                return Alert({
                    type: results.success ? 'success' : 'error',
                    class: 'mt-3',
                    closeable: true,
                }, results.message);
            },
        ),
        div(
            { class: 'table fx-flex' },
            div(
                { class: 'table-header flex-row' },
                span(
                    { style: `flex: ${columns[0]}` },
                    getValue(props.arg_label),
                ),
                span(
                    { style: `flex: ${columns[1]}` },
                    'Cron Expression | Timezone',
                ),
                span(
                    { style: `flex: ${columns[2]}` },
                    'Actions',
                ),
            ),
            () => scheduleItems.val?.length 
                ? div(
                    scheduleItems.val.map(item => ScheduleListItem(item, columns, getValue(props.permissions))),
                ) 
                : div({ class: 'mt-5 mb-3 ml-3 text-secondary', style: 'text-align: center;' }, 'No schedules defined yet.'),
        ),
    );
}

const ScheduleListItem = (
    /** @type Schedule */ item,
    /** @type string[] */ columns,
    /** @type Permissions */ permissions,
) => {
    return div(
        { class: 'table-row flex-row' },
        div(
            { style: `flex: ${columns[0]}` },
            div(item.argValue),
        ),
        div(
            { class: 'flex-row', style: `flex: ${columns[1]}` },
            div(
                div(
                    { style: 'font-family: \'Roboto Mono\', monospace; font-size: 12px' },
                    item.cronExpr,
                    withTooltip(
                        i(
                            {
                                class: 'material-symbols-rounded text-secondary ml-1',
                                style: 'position: relative; font-size: 16px;',
                            },
                            'info',
                        ),
                        {
                            text: [
                                div({class: 'text-center mb-1'}, item.readableExpr),
                                div({class: 'text-left'}, "Next runs:"),
                                ...item.sample?.map(v => div({class: 'text-left'}, v))
                            ],
                        },
                    ),
                ),
                div(
                    { class: 'text-caption mt-1' },
                    item.cronTz,
                ),
            ),
        ),
        div(
            { style: `flex: ${columns[2]}` },
            permissions.can_edit ? Button({
                type: 'stroked',
                label: 'Delete',
                style: 'width: auto; height: 32px;',
                onclick: () => emitEvent('DeleteSchedule', { payload: item }),
            }) : null,
        ),
    );
}


const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.short-select-portal {
    max-height: 250px !important;
}
`);

export { ScheduleList };
