/**
 * @import { TableGroupPreview } from '../components/table_group_test.js'
 * @import { Connection } from ''../components/connection_form.js'
 * @import { TableGroup } from ''../components/table_group_form.js'
 * 
 * @typedef WizardResult
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * @property {string?} table_group_id
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {TableGroup} table_group
 * @property {Connection[]} connections
 * @property {string[]?} steps
 * @property {boolean?} is_in_use
 * @property {TableGroupPreview?} table_group_preview
 * @property {WizardResult?} results
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { TableGroupForm } from '../components/table_group_form.js';
import { TableGroupTest } from '../components/table_group_test.js';
import { emitEvent, getValue, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Button } from '../components/button.js';
import { Alert } from '../components/alert.js';
import { Checkbox } from '../components/checkbox.js';
import { Icon } from '../components/icon.js';
import { Caption } from '../components/caption.js';

const { div, i, span, strong } = van.tags;
const stepsTitle = {
    tableGroup: 'Configure Table Group',
    testTableGroup: 'Preview Table Group',
    runProfiling: 'Run Profiling',
};
const lastStepCustonButtonText = {
    runProfiling: (state) => state ? 'Save & Run Profiling' : 'Save',
};
const defaultSteps = [
    'tableGroup',
    'testTableGroup',
];

/**
 * @param {Properties} props 
 */
const TableGroupWizard = (props) => {
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const steps =  props.steps?.val ?? defaultSteps;
    const stepsState = {
        tableGroup: van.state(props.table_group.val),
        testTableGroup: van.state(false),
        runProfiling: van.state(true),
    };
    const stepsValidity = {
        tableGroup: van.state(false),
        testTableGroup: van.state(false),
        runProfiling: van.state(true),
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
            const stepState = stepsState[stepKey];
            return lastStepCustonButtonText[stepKey]?.(stepState.val) ?? 'Save';
        }
        return 'Next';
    });

    van.derive(() => {
        const tableGroupPreview = getValue(props.table_group_preview);
        stepsValidity.testTableGroup.val = tableGroupPreview?.success ?? false;
        stepsState.testTableGroup.val = tableGroupPreview?.success ?? false;
    });

    const setStep = (stepIdx) => {
        currentStepIndex.val = stepIdx;
    };
    const saveTableGroup = () => {
        const payloadEntries = [
            ['tableGroup', 'table_group', stepsState.tableGroup.val],
            ['testTableGroup', 'table_group_verified', stepsState.testTableGroup.val],
            ['runProfiling', 'run_profiling', stepsState.runProfiling.val],
        ].filter(([stepKey,]) => steps.includes(stepKey)).map(([, eventKey, stepState]) => [eventKey, stepState]);

        const payload = Object.fromEntries(payloadEntries);
        emitEvent('SaveTableGroupClicked', { payload });
    };

    const domId = 'table-group-wizard-wrapper';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, class: 'tg-table-group-wizard flex-column fx-gap-3' },
        div(
            {},
            () => {
                const stepName = steps[currentStepIndex.val];
                const stepNumber = currentStepIndex.val + 1;
                return Caption({
                    content: `Step ${stepNumber} of ${steps.length}: ${stepsTitle[stepName]}`,
                });
            },
        ),
        WizardStep(0, currentStepIndex, () => {
            currentStepIndex.val;

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
            const tableGroup = stepsState.tableGroup.rawVal;

            if (currentStepIndex.val === 1) {
                props.table_group_preview.val = undefined;
                stepsValidity.testTableGroup.val = false;
                stepsState.testTableGroup.val = false;

                emitEvent('PreviewTableGroupClicked', { payload: {table_group: tableGroup} });
            }

            return TableGroupTest(
                tableGroup.table_group_schema ?? '--',
                props.table_group_preview,
                {
                    onVerifyAcess: () => {
                        emitEvent('PreviewTableGroupClicked', {
                            payload: {
                                table_group: stepsState.tableGroup.rawVal,
                                verify_access: true,
                            },
                        });
                    }
                }
            );
        }),
        () => {
            const runProfiling = van.state(stepsState.runProfiling.rawVal);
            const results = getValue(props.results) ?? {};

            van.derive(() => {
                stepsState.runProfiling.val = runProfiling.val;
            });

            return WizardStep(2, currentStepIndex, () => {
                currentStepIndex.val;
    
                return RunProfilingStep(
                    stepsState.tableGroup.rawVal,
                    runProfiling,
                    results?.success ?? false,
                );
            });
        },
        div(
            { class: 'flex-column fx-gap-3' },
            () => {
                const results = getValue(props.results) ?? {};
                return Object.keys(results).length > 0
                    ? Alert({ type: results.success ? 'success' : 'error' }, span(results.message))
                    : '';
            },
            div(
                { class: 'flex-row' },
                () => {
                    const results = getValue(props.results);
    
                    if (currentStepIndex.val <= 0 || results?.success === true) {
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
                    const results = getValue(props.results);
                    const runProfiling = stepsState.runProfiling.val;
                    const stepKey = steps[currentStepIndex.val];
    
                    if (results && results.success && stepKey === 'runProfiling' && runProfiling) {
                        return Button({
                            type: 'stroked',
                            color: 'primary',
                            label: 'Go to Profiling Runs',
                            width: 'auto',
                            icon: 'chevron_right',
                            style: 'margin-left: auto;',
                            onclick: () => emitEvent('GoToProfilingRunsClicked', { payload: { table_group_id: results.table_group_id } }),
                        });
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
 * @param {boolean?} disabled
 * @returns 
 */
const RunProfilingStep = (tableGroup, runProfiling, disabled) => {
    return div(
        { class: 'flex-column fx-gap-3' },
        Checkbox({
            label: div(
                { class: 'flex-row'},
                span({ class: 'mr-1' }, 'Execute profiling for the table group'),
                strong(() => tableGroup.table_groups_name),
                span('?'),
            ),
            checked: runProfiling,
            disabled: disabled ?? false,
            onChange: (value) => runProfiling.val = value,
        }),
        div(
            { class: 'flex-row fx-gap-1' },
            Icon({}, 'info'),
            () => runProfiling.val
                ? i('Profiling will be performed in a background process.')
                : i('Profiling will be skipped. You can run this step later from the Profiling Runs page.'),
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
        { class: () => `flex-column fx-gap-3 ${hidden.val ? 'hidden' : ''}`},
        content,
    );
};

export { TableGroupWizard };
