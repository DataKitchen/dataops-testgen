/**
 * @typedef WizardResult
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * @property {string} table_group_id
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {string} connection_id
 * @property {WizardResult?} results
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { TableGroupForm } from '../components/table_group_form.js';
import { emitEvent, getValue, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Button } from '../components/button.js';
import { Alert } from '../components/alert.js';
import { Checkbox } from '../components/checkbox.js';
import { Icon } from '../components/icon.js';

const { div, i, span, strong } = van.tags;

/**
 * @param {Properties} props 
 */
const TableGroupWizard = (props) => {
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const steps = [
        'tableGroup',
        'runProfiling',
    ];
    const stepsState = {
        tableGroup: van.state({}),
        runProfiling: van.state(true),
    };
    const stepsValidity = {
        tableGroup: van.state(false),
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
            return stepsState.runProfiling.val ? 'Save & Run Profiling' : 'Finish Setup';
        }
        return 'Next';
    });
    const setStep = (stepIdx) => {
        currentStepIndex.val = stepIdx;
    };
    const saveTableGroup = () => {
        const payload = {
            table_group: stepsState.tableGroup.val,
            run_profiling: stepsState.runProfiling.val,
        };
        emitEvent('SaveTableGroupClicked', { payload });
    };

    const domId = 'table-group-wizard-wrapper';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, class: 'tg-table-group-wizard flex-column fx-gap-3' },
        WizardStep(0, currentStepIndex, () => {
            currentStepIndex.val;

            return TableGroupForm({
                tableGroup: stepsState.tableGroup.rawVal,
                onChange: (updatedTableGroup, state) => {
                    stepsState.tableGroup.val = updatedTableGroup;
                    stepsValidity.tableGroup.val = state.valid;
                },
            });
        }),
        () => {
            const results = getValue(props.results);
            const runProfiling = van.state(stepsState.runProfiling.rawVal);

            van.derive(() => {
                stepsState.runProfiling.val = runProfiling.val;
            });

            return WizardStep(1, currentStepIndex, () => {
                currentStepIndex.val;
    
                return RunProfilingStep(
                    stepsState.tableGroup.rawVal,
                    runProfiling,
                    results,
                );
            });
        },
        div(
            { class: 'tg-table-group-wizard--footer flex-row' },
            () => currentStepIndex.val > 0
                ? Button({
                    label: 'Previous',
                    type: 'stroked',
                    color: 'basic',
                    width: 'auto',
                    style: 'margin-right: auto; min-width: 200px;',
                    onclick: () => setStep(currentStepIndex.val - 1),
                })
                : '',
            () => {
                const results = getValue(props.results);
                const runProfiling = stepsState.runProfiling.val;

                if (results && results.success && runProfiling) {
                    return Button({
                        type: 'stroked',
                        color: 'primary',
                        label: 'Go to Profiling Runs',
                        width: 'auto',
                        icon: 'chevron_right',
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
    );
};

/**
 * @param {object} tableGroup 
 * @param {boolean} runProfiling 
 * @param {WizardResult} result
 * @returns 
 */
const RunProfilingStep = (tableGroup, runProfiling, results) => {
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
            onChange: (value) => runProfiling.val = value,
        }),
        div(
            { class: 'flex-row fx-gap-1' },
            Icon({}, 'info'),
            () => runProfiling.val
                ? i('Profiling will be performed in a background process.')
                : i('Profiling will be skipped. You can run this step later from the Profiling Runs page.'),
        ),
        () => {
            const results_ = getValue(results) ?? {};
            return Object.keys(results_).length > 0
                ? Alert({ type: results_.success ? 'success' : 'error' }, span(results_.message))
                : '';
        },
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
        { class: () => hidden.val ? 'hidden' : ''},
        content,
    );
};

export { TableGroupWizard };
