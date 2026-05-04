/**
 * @import { MonitorSuite, Schedule } from '/app/static/js/components/monitor_settings_form.js';
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
 * @property {{ open: boolean, title: string }?} dialog
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Icon } from '/app/static/js/components/icon.js';
import { MonitorSettingsForm } from '/app/static/js/components/monitor_settings_form.js';
import { getValue } from '/app/static/js/utils.js';

const { div, span } = van.tags;

/**
 *
 * @param {Properties} props
 * @returns
 */
const EditMonitorSettings = (props) => {
    const emit = props.emit;
    const dialogOpen = van.state(false);
    van.derive(() => {
        const d = getValue(props.dialog);
        if (d?.open) dialogOpen.val = true;
        else dialogOpen.val = false;
    });

    const updatedSchedule = van.state(null);
    const updatedMonitorSuite = van.state(null);
    const formState = van.state({dirty: false, valid: false});

    // Deferred mount: form is created once when data arrives, stays stable
    // across prop updates (cron sample etc.), and is cleared on dialog close
    // so a fresh form is created next time.
    const formContainer = div();
    let formMounted = false;

    van.derive(() => {
        const tableGroup = getValue(props.table_group);
        if (tableGroup && !formMounted) {
            formMounted = true;
            const monitorSuite = getValue(props.monitor_suite);
            van.add(formContainer,
                div(
                    { class: 'flex-row fx-gap-1 mb-5 text-large' },
                    span({ class: 'text-secondary' }, 'Table Group:'),
                    span(tableGroup.table_groups_name),
                ),
                MonitorSettingsForm(
                    { emit,
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
                    !monitorSuite?.id
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
                            emit('SaveSettingsClicked', { payload });
                        },
                    }),
                ),
            );
        } else if (!tableGroup && formMounted) {
            formMounted = false;
            formContainer.replaceChildren();
        }
    });

    const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? '');
    return Dialog(
        {
            title: dialogTitle,
            open: dialogOpen,
            onClose: () => { dialogOpen.val = false; emit('CloseSettingsDialog', {}); },
            width: '55rem',
        },
        formContainer,
    );
};

export { EditMonitorSettings };
