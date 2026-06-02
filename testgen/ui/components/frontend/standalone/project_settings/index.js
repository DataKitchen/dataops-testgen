/**
 * @import {VanState} from '/app/static/js/van.min.js';
 */
import van from '/app/static/js/van.min.js';
import { Card } from '/app/static/js/components/card.js';
import { Input } from '/app/static/js/components/input.js';
import { Button } from '/app/static/js/components/button.js';
import { numberBetween, required } from '/app/static/js/form_validators.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { CrontabInput } from '/app/static/js/components/crontab_input.js';
import { Select } from '/app/static/js/components/select.js';
import { timezones } from '/app/static/js/values.js';
import { formatTimestamp } from '/app/static/js/display_utils.js';
import { createEmitter, debounce, getValue, isEqual } from '/app/static/js/utils.js';

const { div, span } = van.tags;

/**
 * @typedef ObsTestResults
 * @type {object}
 * @property {boolean} successful
 * @property {string} message
 * @property {string?} details
 *
 * @typedef Properties
 * @type {object}
 * @property {VanState<string>} name
 * @property {VanState<boolean>} use_dq_score_weights
 * @property {VanState<string?>} observability_api_url
 * @property {VanState<string?>} observability_api_key
 * @property {VanState<ObsTestResults?>} observability_test_results
 * @property {VanState<boolean>} data_retention_enabled
 * @property {VanState<number>} data_retention_days
 * @property {VanState<string>} retention_cron_expr
 * @property {VanState<string>} retention_cron_tz
 * @property {VanState<object?>} retention_cron_sample
 * @property {VanState<string?>} retention_last_run
 * @property {VanState<{profiling_count: number, test_count: number}?>} retention_preview
 *
 * @param {Properties} props
 */
const ProjectSettings = (props) => {
    const { emit } = props;
    // Persisted values are reactive: after a Save, the props update with the
    // newly-stored values and these derives recompute, letting
    // `showRetentionConfirmation` settle back to a clean state.
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const persistedRetentionEnabled = van.derive(() => props.data_retention_enabled.val ?? false);
    const persistedRetentionDays = van.derive(() => props.data_retention_days.val ?? 180);
    const persistedRetentionCron = van.derive(() => props.retention_cron_expr.val ?? '0 1 * * *');
    const persistedRetentionTz = van.derive(() => props.retention_cron_tz.val ?? browserTz);
    const /** @type Properties */ form = {
        name: van.state(props.name.rawVal ?? ''),
        use_dq_score_weights: van.state(props.use_dq_score_weights.rawVal ?? true),
        observability_api_key: van.state(props.observability_api_key.rawVal ?? ''),
        observability_api_url: van.state(props.observability_api_url.rawVal ?? ''),
        data_retention_enabled: van.state(persistedRetentionEnabled.val),
        data_retention_days: van.state(persistedRetentionDays.val),
        retention_cron_expr: van.state(persistedRetentionCron.val),
        retention_cron_tz: van.state(persistedRetentionTz.val),
    };
    const formValidity = {
        name: van.state(!!form.name.rawVal),
        observability_api_key: van.state(true),
        observability_api_url: van.state(true),
        data_retention_days: van.state(Number.isFinite(form.data_retention_days.rawVal)),
    };
    const saveDisabled = van.derive(() => !formValidity.name.val
        || !formValidity.observability_api_url.val
        || !formValidity.observability_api_key.val
        || (form.data_retention_enabled.val && !formValidity.data_retention_days.val));
    const testObservabilityDisabled = van.derive(() => form.observability_api_url.val.length <= 0 || form.observability_api_key.val.length <= 0);
    const retentionCronEditorValue = van.derive(() => {
        if (form.retention_cron_expr.val && form.retention_cron_tz.val && form.data_retention_enabled.val) {
            emit('GetCronSample', {
                payload: { cron_expr: form.retention_cron_expr.val, tz: form.retention_cron_tz.val },
            });
        }
        return {
            timezone: form.retention_cron_tz.val,
            expression: form.retention_cron_expr.val,
        };
    });
    // True when the form would enlarge the next cleanup's delete set —
    // turning retention on, or shortening the retention period of a project
    // that already has it on. Both cases warrant a delete-preview confirmation
    // before saving.
    const showRetentionConfirmation = van.derive(() => {
        if (!form.data_retention_enabled.val) return false;
        if (!persistedRetentionEnabled.val) return true;
        return form.data_retention_days.val < persistedRetentionDays.val;
    });
    // Debounce so rapid days edits collapse to a single round-trip.
    const previewPending = van.state(false);
    const emitPreviewRequest = debounce((days) => {
        emit('GetRetentionPreview', { payload: { retention_days: days } });
    }, 300);
    van.derive(() => {
        if (showRetentionConfirmation.val && formValidity.data_retention_days.val) {
            previewPending.val = true;
            emitPreviewRequest(form.data_retention_days.val);
        }
    });
    van.derive(() => {
        if (getValue(props.retention_preview) !== null && getValue(props.retention_preview) !== undefined) {
            previewPending.val = false;
        }
    });

    return div(
        { class: 'flex-column fx-gap-3' },
        div(
            { class: 'flex-column fx-gap-1', style: 'max-width: 700px;' },
            span({ class: 'body m' }, 'Project Info'),
            Card({
                class: 'mb-0',
                border: true,
                content: div(
                    { class: 'flex-column fx-gap-3'},
                    Input({
                        label: 'Project Name',
                        value: form.name,
                        validators: [ required ],
                        onChange: (value, validity) => {
                            form.name.val = value;
                            formValidity.name.val = validity.valid;
                        },
                    }),
                    Checkbox({
                        label: 'Use weighted data quality scoring',
                        checked: form.use_dq_score_weights,
                        help: 'When enabled, data quality scores weight tables and columns by their semantic importance. Dimension tables and key columns receive higher weights.',
                        onChange: (checked) => { form.use_dq_score_weights.val = checked; },
                    }),
                ),
            }),
        ),
        div(
            { class: 'flex-column fx-gap-1', style: 'max-width: 700px;' },
            span({ class: 'body m' }, 'Observability Integration'),
            Card({
                class: 'mb-0',
                border: true,
                content: div(
                    { class: 'flex-column fx-gap-3'},
                    Input({
                        label: 'API URL',
                        value: form.observability_api_url,
                        onChange: (value, validity) => {
                            form.observability_api_url.val = value;
                            formValidity.observability_api_url.val = validity.valid;
                        },
                    }),
                    Input({
                        label: 'API Key',
                        value: form.observability_api_key,
                        onChange: (value, validity) => {
                            form.observability_api_key.val = value;
                            formValidity.observability_api_key.val = validity.valid;
                        },
                    }),
                    div(
                        { class: 'flex-row' },
                        Button({
                            type: 'stroked',
                            color: 'basic',
                            label: 'Test Observability Connection',
                            width: 'auto',
                            disabled: testObservabilityDisabled,
                            onclick: () => emit('TestObservabilityClicked', {
                                payload: {
                                    observability_api_url: form.observability_api_url.rawVal,
                                    observability_api_key: form.observability_api_key.rawVal,
                                },
                            }),
                        }),
                    ),
                    () => {
                        const results = getValue(props.observability_test_results) ?? {};
                        return Object.keys(results).length > 0
                            ? Alert(
                                { type: results.successful ? 'success' : 'error' },
                                div(
                                    { class: 'flex-column' },
                                    span(results.message),
                                    results.details ? span(results.details) : '',
                                ),
                            )
                            : '';
                    },
                ),
            }),
        ),
        div(
            { class: 'flex-column fx-gap-1', style: 'max-width: 700px;' },
            span({ class: 'body m' }, 'Data Retention'),
            Card({
                class: 'mb-0',
                border: true,
                content: div(
                    { class: 'flex-column fx-gap-3' },
                    Checkbox({
                        label: 'Automatically delete old profiling and test history',
                        checked: form.data_retention_enabled,
                        help: 'Old profiling and test runs are permanently deleted to keep the database from growing without bound. The most recent run in each test suite and table group is always kept.',
                        onChange: (checked) => { form.data_retention_enabled.val = checked; },
                    }),
                    () => form.data_retention_enabled.val
                        ? div(
                            { class: 'flex-column fx-gap-3' },
                            Input({
                                label: 'Delete history older than (days)',
                                value: form.data_retention_days,
                                type: 'number',
                                step: 1,
                                validators: [ required, numberBetween(30, 9999, 0) ],
                                onChange: (value, validity) => {
                                    form.data_retention_days.val = value === '' ? NaN : parseInt(value);
                                    formValidity.data_retention_days.val = validity.valid;
                                },
                            }),
                            () => {
                                const days = form.data_retention_days.val;
                                return days >= 30 && days < 60
                                    ? span(
                                        { class: 'text-caption', style: 'color: var(--purple);' },
                                        'Monitors perform better with more historical data — at least two months is recommended.',
                                    )
                                    : '';
                            },
                            div(
                                { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start' },
                                () => Select({
                                    label: 'Timezone',
                                    options: timezones.map((tz_) => ({ label: tz_, value: tz_ })),
                                    value: form.retention_cron_tz,
                                    allowNull: false,
                                    filterable: true,
                                    onChange: (value) => { form.retention_cron_tz.val = value; },
                                    portalClass: 'short-select-portal',
                                    style: 'flex: auto;',
                                }),
                                div(
                                    { style: 'flex: auto;' },
                                    CrontabInput({
                                        emit,
                                        name: 'data_retention_schedule',
                                        sample: props.retention_cron_sample,
                                        value: retentionCronEditorValue,
                                        modes: ['x_hours', 'x_days'],
                                        hideExpression: true,
                                        onChange: (value) => { form.retention_cron_expr.val = value; },
                                    }),
                                ),
                            ),
                            () => {
                                const lastRun = getValue(props.retention_last_run);
                                const sample = getValue(props.retention_cron_sample) ?? {};
                                const nextSample = (sample.samples ?? [])[0];
                                return div(
                                    { class: 'flex-column fx-gap-1 text-caption' },
                                    span(`Last cleanup ran: ${lastRun ? formatTimestamp(lastRun) : 'never'}`),
                                    nextSample ? span(`Next cleanup: ${nextSample}`) : '',
                                );
                            },
                            () => {
                                if (!showRetentionConfirmation.val) return '';
                                const preview = getValue(props.retention_preview);
                                const profilingCt = preview?.profiling_count ?? 0;
                                const testCt = preview?.test_count ?? 0;
                                const showing = preview !== null && preview !== undefined && !previewPending.val;
                                const message = !showing
                                    ? 'Calculating impact…'
                                    : `This will delete approximately ${profilingCt} profiling run${profilingCt === 1 ? '' : 's'} and ${testCt} test run${testCt === 1 ? '' : 's'} at the next cleanup. Deleted data cannot be recovered.`;
                                return Alert(
                                    { type: 'warn' },
                                    span(message),
                                );
                            },
                        )
                        : '',
                ),
            }),
        ),
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            Button({
                type: 'stroked',
                color: 'primary',
                label: 'Save',
                width: 'auto',
                disabled: saveDisabled,
                onclick: () => emit('SaveClicked', {
                    payload: Object.fromEntries(Object.entries(form).map(([fieldName, value]) => [fieldName, value.rawVal]))
                }),
            }),
        ),
    );
};

export default (component) => {
  const { data, setStateValue, setTriggerValue, parentElement } = component;

  let componentState = parentElement.state;
  if (componentState === undefined) {
    componentState = {};
    for (const [ key, value ] of Object.entries(data)) {
      componentState[key] = van.state(value);
    }

    parentElement.state = componentState;
    componentState.emit = createEmitter(setTriggerValue);
    van.add(parentElement, ProjectSettings(componentState));
  } else {
    for (const [ key, value ] of Object.entries(data)) {
      if (!isEqual(componentState[key].val, value)) {
        componentState[key].val = value;
      }
    }
  }

  return () => {
    parentElement.state = null;
  };
};
