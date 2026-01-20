/**
 * @import { MonitorSuite, Schedule } from '../components/monitor_settings_form.js';
 * @import { CronSample } from '../types.js';
 * 
 * @typedef TableGroup
 * @type {object}
 * @property {string} id
 * @property {string} connection_id
 * @property {string} table_groups_name
 * @property {string} monitor_test_suite_id
 * @property {string} last_complete_profile_run_id
 * 
 * @typedef Properties
 * @type {object}
 * @property {TableGroup} table_group
 * @property {Schedule} schedule
 * @property {MonitorSuite} monitor_suite
 * @property {CronSample?} cron_sample
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Button } from '../components/button.js';
import { Icon } from '../components/icon.js';
import { MonitorSettingsForm } from '../components/monitor_settings_form.js';
import { emitEvent, getRandomId, getValue, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';

const { div, span } = van.tags;

/**
 * 
 * @param {Properties} props 
 * @returns 
 */
const EditMonitorSettings = (props) => {
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const domId = `edit-monitor-settings-${getRandomId()}`;
    const tableGroup = getValue(props.table_group);

    const schedule = getValue(props.schedule);
    const updatedSchedule = van.state(schedule);

    const monitorSuite = getValue(props.monitor_suite);
    const updatedMonitorSuite = van.state(monitorSuite);

    const formState = van.state({dirty: false, valid: false});

    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId },
        div(
            { class: 'flex-row fx-gap-1 mb-5 text-large' },
            span({ class: 'text-secondary' }, 'Table Group:'),
            span(tableGroup.table_groups_name),
        ),
        MonitorSettingsForm(
            {
                schedule: props.schedule,
                monitorSuite: props.monitor_suite,
                cronSample: props.cron_sample,
                onChange: (schedule, monitorSuite, state) => {
                    formState.val = state;
                    updatedSchedule.val = schedule;
                    updatedMonitorSuite.val = monitorSuite;
                },
            },
        ),
        div(
            { class: 'flex-row fx-justify-space-between fx-gap-3 mt-4' },
            !monitorSuite.id 
                ? div(
                    { class: 'flex-row fx-gap-1' },
                    Icon({ size: 16 }, 'info'),
                    span(
                        { class: 'text-caption' },
                        tableGroup.last_complete_profile_run_id
                            ? 'Monitors will be configured based on latest profiling and run periodically on schedule.'
                            : 'Monitors will be configured after first profiling and run periodically on schedule.'
                    ),
                )
                : span({}),
            Button({
                label: 'Save',
                color: 'primary',
                type: 'flat',
                width: 'auto',
                disabled: () => !formState.val.dirty || !formState.val.valid,
                onclick: () => {
                    const payload = {
                        schedule: updatedSchedule.val,
                        monitor_suite: updatedMonitorSuite.val,
                    };
                    emitEvent('SaveSettingsClicked', { payload });
                },
            }),
        ),
    );
};

export { EditMonitorSettings };
