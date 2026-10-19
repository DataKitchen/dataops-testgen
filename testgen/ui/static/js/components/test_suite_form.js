/**
 * @typedef TestSuiteFormState
 * @type {object}
 * @property {object} suiteType
 * @property {object} testSuiteName
 * @property {object} tableGroupId
 * @property {object} description
 * @property {object} severity
 * @property {object} exportToObservability
 * @property {object} dqScoreExclude
 * @property {object} deactivateInvalidTests
 * @property {object} componentKey
 * @property {object} componentType
 * @property {object} componentName
 *
 * @typedef TestSuiteFormValidity
 * @type {object}
 * @property {object} testSuiteName
 * @property {object} tableGroupId
 *
 * @typedef Properties
 * @type {object}
 * @property {TestSuiteFormState} state
 * @property {TestSuiteFormValidity} validity
 * @property {Array<{value: string, label: string}>} tableGroups
 * @property {('add' | 'edit')} mode
 * @property {function(string)?} onTableGroupChange
 * @property {function(string)?} onTypeChange
 */
import van from '/app/static/js/van.min.js';
import { loadStylesheet } from '/app/static/js/utils.js';
import { Input } from '/app/static/js/components/input.js';
import { Select } from '/app/static/js/components/select.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { RadioGroup } from '/app/static/js/components/radio_group.js';
import { ExpanderToggle } from '/app/static/js/components/expander_toggle.js';
import { required } from '/app/static/js/form_validators.js';

const { div } = van.tags;

const TestSuiteFields = (/** @type Properties */ props) => {
    loadStylesheet('test-suite-form', stylesheet);

    const { state, validity, tableGroups, mode, onTableGroupChange, onTypeChange } = props;
    const isEdit = mode === 'edit';
    const typeLabel = () => state.suiteType.val === 'contract' ? 'Contract' : 'Test Suite';
    const severityOptions = [
        { value: null, label: 'Inherit' },
        { value: 'Log', label: 'Log' },
        { value: 'Fail', label: 'Failed' },
        { value: 'Warning', label: 'Warning' },
    ];
    const showObservabilitySection = van.state(false);

    return div(
        { class: 'flex-column fx-gap-3' },
        RadioGroup({
            label: 'Type',
            options: [
                { label: 'Test suite', value: 'regular' },
                { label: 'Contract', value: 'contract' },
            ],
            value: state.suiteType,
            layout: 'inline',
            disabled: isEdit,
            onChange: (value) => {
                state.suiteType.val = value;
                onTypeChange?.(value);
            },
        }),
        div(
            { class: 'flex-row fx-gap-3' },
            Input({
                label: () => `${typeLabel()} Name`,
                value: state.testSuiteName,
                disabled: isEdit,
                style: 'flex: 1;',
                validators: [required],
                onChange: (value, inputValidity) => {
                    state.testSuiteName.val = value;
                    validity.testSuiteName.val = inputValidity.valid;
                },
            }),
            Select({
                label: 'Table Group',
                value: state.tableGroupId,
                options: tableGroups,
                allowNull: false,
                required: true,
                disabled: isEdit,
                style: 'flex: 1;',
                // Select assigns state.tableGroupId itself and calls onChange from inside a derive that
                // reads it; writing it again here would unsubscribe that derive after the first pick.
                onChange: (value) => {
                    validity.tableGroupId.val = !!value;
                    onTableGroupChange?.(value);
                },
                portalClass: 'ts-form--select',
            }),
        ),
        div(
            { class: 'flex-row fx-gap-3' },
            Input({
                label: () => `${typeLabel()} Description`,
                value: state.description,
                style: 'flex: 1;',
                onChange: (value) => { state.description.val = value; },
            }),
            Select({
                label: 'Severity',
                value: state.severity,
                options: severityOptions,
                allowNull: false,
                style: 'flex: 1;',
                portalClass: 'ts-form--select',
            }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-gap-4' },
            Checkbox({
                name: 'export-to-observability',
                label: 'Export to Observability',
                checked: state.exportToObservability,
                onChange: (value) => { state.exportToObservability.val = value; },
            }),
            Checkbox({
                name: 'dq-score-exclude',
                label: 'Exclude from quality scoring',
                checked: state.dqScoreExclude,
                onChange: (value) => { state.dqScoreExclude.val = value; },
            }),
            () => state.suiteType.val === 'contract'
                ? ''
                : Checkbox({
                    name: 'deactivate-invalid-tests',
                    label: 'Automatically deactivate tests that fail validation',
                    help: 'At the start of each run, tests whose table or column is missing, or whose column type changed, are deactivated. Otherwise, these tests report an error on each run until the problem is fixed.',
                    checked: state.deactivateInvalidTests,
                    onChange: (value) => { state.deactivateInvalidTests.val = value; },
                }),
        ),
        ExpanderToggle({
            expandLabel: 'Observability overrides',
            collapseLabel: 'Observability overrides',
            labelPosition: 'left',
            onExpand: () => { showObservabilitySection.val = true; },
            onCollapse: () => { showObservabilitySection.val = false; },
        }),
        () => showObservabilitySection.val
            ? div(
                { class: 'flex-row fx-gap-3' },
                Input({
                    label: 'Component Key',
                    value: state.componentKey,
                    placeholder: 'Optional',
                    style: 'flex: 1;',
                    onChange: (value) => { state.componentKey.val = value; },
                }),
                Input({
                    label: 'Component Type',
                    value: state.componentType,
                    disabled: true,
                    style: 'flex: 1;',
                }),
                Input({
                    label: 'Component Name',
                    value: state.componentName,
                    placeholder: 'Optional',
                    style: 'flex: 1;',
                    onChange: (value) => { state.componentName.val = value; },
                }),
            )
            : '',
    );
};

const createTestSuiteFormState = (initial = {}) => ({
    suiteType: van.state(initial.suite_type ?? 'regular'),
    testSuiteName: van.state(initial.test_suite ?? ''),
    tableGroupId: van.state(initial.table_groups_id ?? null),
    description: van.state(initial.test_suite_description ?? ''),
    severity: van.state(initial.severity ?? null),
    exportToObservability: van.state(initial.export_to_observability ?? false),
    dqScoreExclude: van.state(initial.dq_score_exclude ?? false),
    deactivateInvalidTests: van.state(initial.deactivate_invalid_tests ?? false),
    componentKey: van.state(initial.component_key ?? ''),
    componentType: van.state(initial.component_type ?? 'dataset'),
    componentName: van.state(initial.component_name ?? ''),
});

const testSuiteFormPayload = (state) => ({
    suite_type: state.suiteType.val,
    test_suite: state.testSuiteName.val,
    table_groups_id: state.tableGroupId.val,
    test_suite_description: state.description.val,
    severity: state.severity.val,
    export_to_observability: state.exportToObservability.val,
    dq_score_exclude: state.dqScoreExclude.val,
    ...(state.suiteType.val === 'contract' ? {} : { deactivate_invalid_tests: state.deactivateInvalidTests.val }),
    component_key: state.componentKey.val,
    component_type: state.componentType.val,
    component_name: state.componentName.val,
});

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.ts-form--select {
    max-height: 220px !important;
}
`);

export { TestSuiteFields, createTestSuiteFormState, testSuiteFormPayload };
