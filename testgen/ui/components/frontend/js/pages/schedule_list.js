/**
 * @typedef Schedule
 * @type {object}
 * @property {string} argValue
 * @property {string} cronExpr
 * @property {string} cronTz
 * @property {string[]} sample
 *
 * @typedef Properties
 * @type {object}
 * @property {Schedule[]} items
 * @property {Permissions} permissions
 * @property {string} argLabel
 */
import van from '../van.min.js';
import { Button } from '../components/button.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, resizeFrameHeightToElement } from '../utils.js';
import { withTooltip } from '../components/tooltip.js';


const { div, span, i, rawHTML } = van.tags;

const ScheduleList = (/** @type Properties */ props) => {
    window.testgen.isPage = false;

    const scheduleItems = van.derive(() => {
        let items = [];
        try {
            items = JSON.parse(getValue(props.items));
        } catch (e) {
            console.log(e)
        }
        Streamlit.setFrameHeight(100 * items.length);
        return items;
    });
    const columns = ['40%', '50%', '10%'];

    const tableId = 'profiling-schedules-table';
    resizeFrameHeightToElement(tableId);

    return div(
        { class: 'table', id: tableId },
        div(
            { class: 'table-header flex-row' },
            span(
                { style: `flex: ${columns[0]}` },
                getValue(props.argLabel),
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
        () => div(
            scheduleItems.val.map(item => ScheduleListItem(item, columns)),
        ),
    );
}

const ScheduleListItem = (
    /** @type Schedule */ item,
    /** @type string[] */ columns,
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
                        { text: [div("Sample triggering timestamps:"), ...item.sample?.map(v => div(v))] },
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
            Button({
                type: 'stroked',
                label: 'Delete',
                style: 'width: auto; height: 32px;',
                onclick: () => emitEvent('DeleteSchedule', { payload: item }),
            }),
        ),
    );
}

export { ScheduleList };
