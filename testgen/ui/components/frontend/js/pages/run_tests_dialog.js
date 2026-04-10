/**
 * @typedef TestSuiteOption
 * @type {object}
 * @property {string} value
 * @property {string} label
 *
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * @property {boolean?} show_link
 *
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {TestSuiteOption[]} test_suites
 * @property {string?} default_test_suite_id
 * @property {Result?} result
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Code } from '/app/static/js/components/code.js';
import { ExpanderToggle } from '/app/static/js/components/expander_toggle.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Select } from '/app/static/js/components/select.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';

const { div, span, strong } = van.tags;

const RunTestsDialog = (/** @type Properties */ props) => {
    const { emit } = props;
    loadStylesheet('run-tests-dialog', stylesheet);

    const dialogProp = getValue(props.dialog);
    const dialogOpen = van.state(dialogProp?.open === true);

    const testSuites = getValue(props.test_suites) ?? [];
    const defaultId = getValue(props.default_test_suite_id);
    const selectedId = van.state(defaultId ?? (testSuites.length === 1 ? testSuites[0].value : null));
    const selectedTestSuite = van.derive(() => testSuites.find(ts => ts.value === selectedId.val) ?? null);

    const showCLI = van.state(false);

    const content = div(
        { class: 'flex-column fx-gap-3 run-tests--wrapper' },
        testSuites.length !== 1
            ? Select({
                label: 'Test Suite',
                value: selectedId,
                options: testSuites,
                onChange: (value) => { selectedId.val = value; },
                portalClass: 'run-tests--select',
            })
            : () => span('Run tests for the test suite ', strong({}, selectedTestSuite.val?.label ?? ''), '?'),
        () => selectedTestSuite.val
            ? div(
                ExpanderToggle({
                    expandLabel: 'Show CLI command',
                    collapseLabel: 'Collapse',
                    onExpand: () => showCLI.val = true,
                    onCollapse: () => showCLI.val = false,
                }),
                Code({ class: () => showCLI.val ? '' : 'hidden' }, `testgen run-tests --test-suite-id ${selectedTestSuite.val.value}`),
            )
            : div({ style: 'margin: auto;' }, 'Select a test suite to run.'),
        () => {
            const result = getValue(props.result) ?? {};
            return result.message
                ? Alert({ type: result.success ? 'success' : 'error' }, span(result.message))
                : '';
        },
        () => !getValue(props.result)
            ? div(
                { class: 'flex-row fx-justify-space-between mt-3' },
                div(
                    { class: 'flex-row fx-gap-1' },
                    Icon({ size: 16 }, 'info'),
                    span({ class: 'text-caption' }, ' Test execution will be performed in a background process.'),
                ),
                Button({
                    label: 'Run Tests',
                    type: 'stroked',
                    color: 'primary',
                    width: 'auto',
                    style: 'width: auto;',
                    disabled: van.derive(() => !selectedTestSuite.val),
                    onclick: () => emit('RunTestsConfirmed', {
                        payload: {
                            test_suite_id: selectedTestSuite.val?.value,
                            test_suite_name: selectedTestSuite.val?.label,
                        },
                    }),
                }),
            )
            : '',
        () => getValue(props.result)?.show_link
            ? Button({
                type: 'stroked',
                color: 'primary',
                label: 'Go to Test Runs',
                style: 'width: auto; margin-left: auto; margin-top: 12px;',
                icon: 'chevron_right',
                onclick: () => emit('GoToTestRunsClicked', {
                    payload: {
                        project_code: getValue(props.project_code),
                        test_suite_id: selectedTestSuite.val?.value,
                    },
                }),
            })
            : '',
    );

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Run Tests');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: () => { dialogOpen.val = false; emit('CloseClicked', {}); },
                width: '32rem',
            },
            content,
        );
    }
    return content;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.run-tests--wrapper {
    min-height: 120px;
}

.run-tests--select {
    max-height: 200px !important;
}
`);

export { RunTestsDialog };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, RunTestsDialog(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
