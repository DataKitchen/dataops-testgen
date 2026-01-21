/**
 * @import { TableGroupPreview } from '../components/table_group_test.js'
 * @import { Connection } from '../components/connection_form.js'
 * @import { TableGroup } from '../components/table_group_form.js'
 * @import { CronSample } from '../types.js'
 * 
 * @typedef WizardResult
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * @property {boolean} run_profiling
 * @property {boolean} generate_test_suite
 * @property {boolean} generate_monitor_suite
 * @property {string?} table_group_id
 * @property {string?} test_suite_id
 * @property {string?} table_group_name
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {TableGroup} table_group
 * @property {Connection[]} connections
 * @property {string[]?} steps
 * @property {boolean?} is_in_use
 * @property {TableGroupPreview?} table_group_preview
 * @property {CronSample?} standard_cron_sample
 * @property {CronSample?} monitor_cron_sample
 * @property {WizardResult?} results
 */
import van from '../van.min.js';
import { TableGroupForm } from '../components/table_group_form.js';
import { TableGroupTest } from '../components/table_group_test.js';
import { TableGroupStats } from '../components/table_group_stats.js';
import { emitEvent, getValue, isEqual } from '../utils.js';
import { Button } from '../components/button.js';
import { Alert } from '../components/alert.js';
import { Checkbox } from '../components/checkbox.js';
import { Icon } from '../components/icon.js';
import { Caption } from '../components/caption.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { CrontabInput } from '../components/crontab_input.js';
import { timezones } from '../values.js';
import { requiredIf } from '../form_validators.js';
import { MonitorSettingsForm } from '../components/monitor_settings_form.js';
import { Streamlit } from '../streamlit.js';

const { div, i, span, strong } = van.tags;
const stepsTitle = {
  tableGroup: 'Configure Table Group',
  testTableGroup: 'Preview Table Group',
  runProfiling: 'Run Profiling',
  testSuite: 'Generate and Run Tests',
  monitorSuite: 'Set up Monitors',
};
const lastStepCustomButtonText = {
  monitorSuite: (_, states) => states?.runProfiling?.val === true ? 'Save & Run' : 'Save',
};
const defaultSteps = [
  'tableGroup',
  'testTableGroup',
];

/**
 * @param {Properties} props 
 */
const TableGroupWizard = (props) => {
  window.testgen.isPage = true;

  const steps = getValue(props.steps) ?? defaultSteps;
  const defaultTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const stepsState = {
    tableGroup: van.state(getValue(props.table_group)),
    testTableGroup: van.state(false),
    runProfiling: van.state(true),
    testSuite: van.state({
      generate: true,
      name: '',
      schedule: '0 0 * * *',
      timezone: defaultTimezone,
    }),
    monitorSuite: van.state({
      generate: true,
      monitor_lookback: 14,
      schedule: '0 */12 * * *',
      timezone: defaultTimezone,
      predict_sensitivity: 'medium',
      predict_min_lookback: 30,
      predict_exclude_weekends: false,
      predict_holiday_codes: undefined,
    }),
  };

  const stepsValidity = {
    tableGroup: van.state(false),
    testTableGroup: van.state(false),
    runProfiling: van.state(true),
    testSuite: van.state(true),
    monitorSuite: van.state(true),
  };
  const currentStepIndex = van.state(0);
  const currentStepIsInvalid = van.derive(() => {
    const stepKey = steps[currentStepIndex.val];
    return !stepsValidity[stepKey].val;
  });
  const nextButtonType = van.derive(() => {
    const isLastStep = currentStepIndex.val === steps.length - 1;
    return isLastStep ? 'flat' : 'stroked';
  });
  const nextButtonLabel = van.derive(() => {
    const isLastStep = currentStepIndex.val === steps.length - 1;
    if (isLastStep) {
      const stepKey = steps[currentStepIndex.val];
      return lastStepCustomButtonText[stepKey]?.(stepKey, stepsState) ?? 'Save';
    }
    return 'Next';
  });

  const tableGroupPreview = van.state(getValue(props.table_group_preview));
  const isComplete = van.derive(() => getValue(props.results)?.success === true);

  const setStep = (stepIdx) => {
    currentStepIndex.val = stepIdx;
  };
  const saveTableGroup = () => {
    const payloadEntries = [
      ['tableGroup', 'table_group', stepsState.tableGroup.val],
      ['testTableGroup', 'table_group_verified', stepsState.testTableGroup.val],
      ['runProfiling', 'run_profiling', stepsState.runProfiling.val],
      ['testSuite', 'standard_test_suite', stepsState.testSuite.val],
      ['monitorSuite', 'monitor_test_suite', stepsState.monitorSuite.val],
    ].filter(([stepKey,]) => steps.includes(stepKey)).map(([, eventKey, stepState]) => [eventKey, stepState]);

    const payload = Object.fromEntries(payloadEntries);
    emitEvent('SaveTableGroupClicked', { payload });
  };

  const domId = 'table-group-wizard-wrapper';

  return div(
    { id: domId, class: 'tg-table-group-wizard flex-column fx-gap-3' },
    div(
      {},
      () => {
        const stepName = steps[currentStepIndex.val];
        const stepNumber = currentStepIndex.val + 1;

        if (isComplete.val) {
          return '';
        }
        return Caption({
          content: `Step ${stepNumber} of ${steps.length}: ${stepsTitle[stepName]}`,
        });
      },
    ),
    WizardStep(0, currentStepIndex, () => {
      currentStepIndex.val;
      if (isComplete.val) {
        return '';
      }

      const connections = getValue(props.connections) ?? [];
      const tableGroup = stepsState.tableGroup.rawVal;

      return TableGroupForm({
        connections,
        tableGroup: tableGroup,
        showConnectionSelector: connections.length > 1,
        disableConnectionSelector: false,
        disableSchemaField: props.is_in_use ?? false,
        onChange: (updatedTableGroup, state) => {
          stepsState.tableGroup.val = updatedTableGroup;
          stepsValidity.tableGroup.val = state.valid;
        },
      });
    }),
    WizardStep(1, currentStepIndex, () => {
      if (isComplete.val) {
        return '';
      }

      const tableGroup = stepsState.tableGroup.rawVal;
      van.derive(() => {
        const renewedPreview = getValue(props.table_group_preview);
        if (currentStepIndex.rawVal === 1) {
          tableGroupPreview.val = renewedPreview;
          stepsValidity.testTableGroup.val = tableGroupPreview.rawVal?.success ?? false;
          stepsState.testTableGroup.val = tableGroupPreview.rawVal?.success ?? false;
        }
      });

      if (currentStepIndex.val === 1) {
        emitEvent('PreviewTableGroupClicked', { payload: { table_group: tableGroup } });
      }

      return TableGroupTest(
        tableGroupPreview,
        {
          onVerifyAcess: () => {
            emitEvent('PreviewTableGroupClicked', {
              payload: {
                table_group: stepsState.tableGroup.rawVal,
                verify_access: true,
              }
            });
          }
        }
      );
    }),
    () => {
      const runProfiling = van.state(stepsState.runProfiling.rawVal);
      van.derive(() => {
        stepsState.runProfiling.val = runProfiling.val;
      });

      return WizardStep(2, currentStepIndex, () => {
        currentStepIndex.val;

        if (isComplete.val) {
          return '';
        }

        return RunProfilingStep(
          stepsState.tableGroup.rawVal,
          runProfiling,
          tableGroupPreview,
        );
      });
    },
    () => {
      const testSuiteState = stepsState.testSuite.rawVal;
      const generateStandardTests = van.state(testSuiteState.generate);
      const testSuiteName = van.state(testSuiteState.name);
      const testSuiteSchedule = van.state(testSuiteState.schedule);
      const testSuiteScheduleTimezone = van.state(testSuiteState.timezone);
      const testSuiteCronSample = van.state({});
      const testSuiteCrontabEditorValue = van.derive(() => {
        if (testSuiteSchedule.val && testSuiteScheduleTimezone.val) {
            emitEvent('GetCronSampleAux', {payload: {cron_expr: testSuiteSchedule.val, tz: testSuiteScheduleTimezone.val}});
        }

        return {
          expression: testSuiteSchedule.val,
          timezone: testSuiteScheduleTimezone.val,
        };
      });

      van.derive(() => {
        stepsState.testSuite.val = {
          generate: generateStandardTests.val,
          name: testSuiteName.val,
          schedule: testSuiteSchedule.val,
          timezone: testSuiteScheduleTimezone.val,
        };
      });

      van.derive(() => {
        const sample = getValue(props.standard_cron_sample);
        testSuiteCronSample.val = sample;
      });

      return WizardStep(3, currentStepIndex, () => {
        if (currentStepIndex.val === 3) {
          emitEvent('GetCronSampleAux', {payload: {cron_expr: testSuiteSchedule.val, tz: testSuiteScheduleTimezone.val}});
        }

        if (isComplete.val) {
          return '';
        }

        const tableGroupName = stepsState.tableGroup.rawVal.table_groups_name;
        if (!stepsState.testSuite.rawVal.name) {
          testSuiteName.val = tableGroupName;
        }

        return div(
          { class: 'flex-column fx-gap-3' },
          Checkbox({
            label: div(
              { class: 'flex-row' },
              span({ class: 'mr-1' }, 'Generate and run tests for the table group'),
              strong(() => tableGroupName),
              span('?'),
            ),
            checked: generateStandardTests,
            disabled: false,
            onChange: (value) => generateStandardTests.val = value,
          }),
          () => generateStandardTests.val
            ? div(
              { class: 'flex-column fx-gap-4' },
              () => Input({
                label: 'Test Suite Name',
                value: testSuiteName,
                validators: [
                  requiredIf(() => generateStandardTests.val),
                ],
                onChange: (name, state) => {
                  testSuiteName.val = name;
                  stepsValidity.testSuite.val = state.valid && !!testSuiteScheduleTimezone.val && !!testSuiteSchedule.val;
                },
              }),
              div(
                { class: 'flex-column fx-gap-3 border border-radius-1 p-3', style: 'position: relative;' },
                Caption({content: 'Monitor Schedule', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),        
                div(
                    { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start monitor-settings-row' },
                    Select({
                        label: 'Timezone',
                        options: timezones.map(tz_ => ({label: tz_, value: tz_})),
                        value: testSuiteScheduleTimezone,
                        allowNull: false,
                        filterable: true,
                        style: 'flex: 1',
                        onChange: (value) => testSuiteScheduleTimezone.val = value,
                    }),
                    CrontabInput({
                      name: 'tg_test_suite_schedule',
                      value: testSuiteCrontabEditorValue,
                      modes: ['x_hours', 'x_days'],
                      sample: testSuiteCronSample,
                      class: 'fx-flex',
                      onChange: (value) => testSuiteSchedule.val = value,
                    }),
                ),
              ),
            )
            : span(),
          div(
            { class: 'flex-row fx-gap-1' },
            Icon({ size: 16 }, 'info'),
            span(
              { class: 'text-caption' },
              () => generateStandardTests.val
                ? 'Tests will be generated after profiling and run periodically on schedule.'
                : 'Test generation will be skipped. You can do this step later from the Test Suites page.',
            ),
          ),
        );
      });
    },
    () => {
      const monitorSuiteState = stepsState.monitorSuite.rawVal;
      const generateMonitorTests = van.state(monitorSuiteState.generate);
      const monitorSuiteLookback = van.state(monitorSuiteState.monitor_lookback);
      const monitorSuiteSchedule = van.state(monitorSuiteState.schedule);
      const monitorSuiteScheduleTimezone = van.state(monitorSuiteState.timezone);
      const monitorPredictSensitivity = van.state(monitorSuiteState.predict_sensitivity);
      const monitorPredictMinLookback = van.state(monitorSuiteState.predict_min_lookback);
      const monitorPredictExcludeWeekends = van.state(monitorSuiteState.predict_exclude_weekends);
      const monitorPredictHolidayCodes = van.state(monitorSuiteState.predict_holiday_codes);

      const monitorSuiteCronSample = van.state({});

      van.derive(() => {
        stepsState.monitorSuite.val = {
          generate: generateMonitorTests.val,
          monitor_lookback: monitorSuiteLookback.val,
          schedule: monitorSuiteSchedule.val,
          timezone: monitorSuiteScheduleTimezone.val,
          predict_sensitivity: monitorPredictSensitivity.val,
          predict_min_lookback: monitorPredictMinLookback.val,
          predict_exclude_weekends: monitorPredictExcludeWeekends.val,
          predict_holiday_codes: monitorPredictHolidayCodes.val,
        };
      });

      van.derive(() => {
        const sample = getValue(props.monitor_cron_sample);
        monitorSuiteCronSample.val = sample;
      });

      return WizardStep(4, currentStepIndex, () => {
        currentStepIndex.val;

        if (isComplete.val) {
          return '';
        }

        const tableGroupName = stepsState.tableGroup.rawVal.table_groups_name;

        return div(
          { class: 'flex-column fx-gap-3' },
          Checkbox({
            label: div(
              { class: 'flex-row' },
              span({ class: 'mr-1' }, 'Configure monitors for the table group'),
              strong(() => tableGroupName),
              span('?'),
            ),
            checked: generateMonitorTests,
            disabled: false,
            onChange: (value) => generateMonitorTests.val = value,
          }),
          () => generateMonitorTests.val
            ? MonitorSettingsForm({
              schedule: {
                active: true,
                cron_expr: monitorSuiteSchedule.rawVal,
                cron_tz: monitorSuiteScheduleTimezone.rawVal,
              },
              monitorSuite: {
                monitor_lookback: monitorSuiteLookback.rawVal,
                predict_sensitivity: monitorPredictSensitivity.rawVal,
                predict_min_lookback: monitorPredictMinLookback.rawVal,
                predict_exclude_weekends: monitorPredictExcludeWeekends.rawVal,
                predict_holiday_codes: monitorPredictHolidayCodes.rawVal,
              },
              cronSample: monitorSuiteCronSample,
              hideActiveCheckbox: true,
              onChange: (schedule, monitorTestSuite, formState) => {
                stepsValidity.monitorSuite.val = formState.valid;
                monitorSuiteLookback.val = monitorTestSuite.monitor_lookback;
                monitorSuiteSchedule.val = schedule.cron_expr;
                monitorSuiteScheduleTimezone.val = schedule.cron_tz;
                monitorPredictSensitivity.val = monitorTestSuite.predict_sensitivity;
                monitorPredictMinLookback.val = monitorTestSuite.predict_min_lookback;
                monitorPredictExcludeWeekends.val = monitorTestSuite.predict_exclude_weekends;
                monitorPredictHolidayCodes.val = monitorTestSuite.predict_holiday_codes;
              },
            })
            : span(),
          div(
            { class: 'flex-row fx-gap-1' },
            Icon({ size: 16 }, 'info'),
            span(
              { class: 'text-caption' },
              () => generateMonitorTests.val
                ? 'Monitors will be configured after profiling and run periodically on schedule.'
                : 'Monitor configuration will be skipped. You can do this step later from the Monitors page.',
            ),
          ),
        );
      });
    },
    () => {
      if (!isComplete.val) {
        return '';
      }

      const results = getValue(props.results);
      let message = '';
      if (results.run_profiling) {
        message = 'Profiling run started.';
        if (results.generate_test_suite) {
          message += ' Tests';
          if (results.generate_monitor_suite) {
            message += ' and';
          }
        }
        if (results.generate_monitor_suite) {
          message += ' Monitors';
        }
        if (results.generate_test_suite || results.generate_monitor_suite) {
          message += ' will be configured after profiling and run periodically on schedule.';
        }
      } else {
        message = 'Profiling was skipped.';
        if (results.generate_test_suite || results.generate_monitor_suite) {
          message += ' Run profiling manually to generate';
        }
        if (results.generate_test_suite) {
          message += ' Tests';
          if (results.generate_monitor_suite) {
            message += ' and';
          }
        }
        if (results.generate_monitor_suite) {
          message += ' Monitors.';
        }
      }

      return div(
        {class: ''},
        div(
          {class: 'flex-column'},
          div({}, span("Created table group "), strong(results.table_group_name), span(".")),
          div(
            { class: 'flex-row fx-gap-1 mb-4' },
            Icon({ size: 16 }, 'info'),
            span(
              { class: 'text-caption' },
              message
            ),
          ),

          div(
            {class: 'flex-row fx-justify-content-flex-end fx-gap-2'},
            results.run_profiling
              ? Button({
                type: 'stroked',
                color: 'primary',
                label: 'Go to Profiling Runs',
                width: 'auto',
                icon: 'chevron_right',
                onclick: () => emitEvent('GoToProfilingRunsClicked', { payload: { table_group_id: results.table_group_id } }),
              })
              : Button({
                type: 'stroked',
                color: 'primary',
                label: 'Run Profiling',
                width: 'auto',
                onclick: () => emitEvent('RunProfilingClicked', { payload: { table_group_id: results.table_group_id, test_suite_id: results.test_suite_id } }),
              }),
            (results.run_profiling && results.generate_test_suite)
              ? Button({
                type: 'stroked',
                color: 'primary',
                label: 'Go to Test Suites',
                width: 'auto',
                icon: 'chevron_right',
                onclick: () => emitEvent('GoToTestSuitesClicked', { payload: { table_group_id: results.table_group_id } }),
              })
              : '',
            (results.run_profiling && results.generate_monitor_suite)
              ? Button({
                type: 'stroked',
                color: 'primary',
                label: 'Go to Monitors',
                width: 'auto',
                icon: 'chevron_right',
                onclick: () => emitEvent('GoToMonitorsClicked', { payload: { table_group_id: results.table_group_id } }),
              })
              : '',
          ),
        )
      );
    },
    div(
      { class: 'flex-column fx-gap-3' },
      () => {
        const results = getValue(props.results) ?? {};
        return results?.success === false
          ? Alert({ type: 'error' }, span(results.message))
          : '';
      },
      div(
        { class: 'flex-row' },
        () => {
          const results = getValue(props.results);

          if (currentStepIndex.val <= 0 || isComplete.val) {
            return '';
          }

          return Button({
            label: 'Previous',
            type: 'stroked',
            color: 'basic',
            width: 'auto',
            style: 'margin-right: auto; min-width: 200px;',
            onclick: () => setStep(currentStepIndex.val - 1),
          });
        },
        () => {
          if (isComplete.val) {
            return '';
          }

          return Button({
            label: nextButtonLabel,
            type: nextButtonType,
            color: 'primary',
            width: 'auto',
            style: 'margin-left: auto; min-width: 200px;',
            disabled: currentStepIsInvalid,
            onclick: () => {
              if (currentStepIndex.val < steps.length - 1) {
                return setStep(currentStepIndex.val + 1);
              }

              saveTableGroup();
            },
          });
        },
      ),
    ),
  );
};

/**
 * @param {object} tableGroup 
 * @param {boolean} runProfiling 
 * @param {TableGroupPreview?} preview
 * @param {boolean?} disabled
 * @returns 
 */
const RunProfilingStep = (tableGroup, runProfiling, preview) => {
  return div(
    { class: 'flex-column fx-gap-3' },
    Checkbox({
      label: div(
        { class: 'flex-row' },
        span({ class: 'mr-1' }, 'Execute profiling for the table group'),
        strong(() => tableGroup.table_groups_name),
        span('?'),
      ),
      checked: runProfiling,
      disabled: false,
      onChange: (value) => runProfiling.val = value,
    }),
    () => runProfiling.val && preview.val
      ? TableGroupStats({ class: 'mt-1 mb-1' }, preview.val.stats)
      : '',
    div(
      { class: 'flex-row fx-gap-1' },
      Icon({ size: 16 }, 'info'),
      span(
        { class: 'text-caption' },
        () => runProfiling.val
          ? 'Profiling will be performed in a background process.'
          : 'Profiling will be skipped. You can run this step later from the Profiling Runs page.',
      ),
    ),
  );
};

/**
 * @param {number} index 
 * @param {number} currentIndex
 * @param {any} content
 */
const WizardStep = (index, currentIndex, content) => {
  const hidden = van.derive(() => getValue(currentIndex) !== getValue(index));

  return div(
    { class: () => `flex-column fx-gap-3 ${hidden.val ? 'hidden' : ''}` },
    content,
  );
};

export { TableGroupWizard };

export default (component) => {
  const { data, setStateValue, setTriggerValue, parentElement } = component;

  Streamlit.enableV2(setTriggerValue);

  let componentState = parentElement.state;
  if (componentState === undefined) {
    componentState = {};
    for (const [ key, value ] of Object.entries(data)) {
      componentState[key] = van.state(value);
    }

    parentElement.state = componentState;
    van.add(parentElement, TableGroupWizard(componentState));
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
