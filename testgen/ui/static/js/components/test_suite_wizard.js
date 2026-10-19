/**
 * @import { ImportPreview } from './contract_import_preview.js'
 *
 * @typedef WizardTableGroup
 * @type {object}
 * @property {string} id
 * @property {string} name
 * @property {number?} profiled_at
 * @property {string[]} tables
 *
 * @typedef WizardLink
 * @type {object}
 * @property {string} label
 * @property {string} href
 * @property {object} params
 *
 * @typedef WizardRow
 * @type {object}
 * @property {('success' | 'skipped' | 'warning' | 'info')} icon
 * @property {string} text
 * @property {WizardLink?} link
 *
 * @typedef WizardResult
 * @type {object}
 * @property {boolean} success
 * @property {string?} message
 * @property {WizardRow[]?} rows
 *
 * @typedef AddWizard
 * @type {object}
 * @property {boolean} open
 * @property {Array<{value: string, label: string}>} table_groups
 * @property {string[]} generation_sets
 * @property {string[]} default_generation_sets
 * @property {number} max_file_bytes
 * @property {WizardTableGroup?} table_group
 * @property {(ImportPreview | {error: string, problems: string[]})?} file_preview
 * @property {WizardResult?} result
 *
 * @typedef Properties
 * @type {object}
 * @property {Function} emit
 * @property {object} wizard - VanJS state holding an AddWizard
 */
import van from '../van.min.js';
import { getValue, isEqual } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { sizeLimit } from '../form_validators.js';
import { Dialog } from './dialog.js';
import { Button } from './button.js';
import { Alert } from './alert.js';
import { Checkbox } from './checkbox.js';
import { Icon } from './icon.js';
import { Link } from './link.js';
import { Select } from './select.js';
import { RadioGroup } from './radio_group.js';
import { FileInput } from './file_input.js';
import { WizardProgressIndicator } from './wizard_progress_indicator.js';
import { TestSuiteFields, createTestSuiteFormState, testSuiteFormPayload } from './test_suite_form.js';
import { ContractTablePicker } from './contract_table_picker.js';
import { ContractImportPreview } from './contract_import_preview.js';

const { div, span } = van.tags;

const STEP_NAMES = ['testSuite', 'tests'];
const METADATA_SENTENCE = 'Metadata is generated from the data catalog. Editing the contract does not change the data catalog.';
const ROW_ICONS = { success: 'check_circle', skipped: 'do_not_disturb_on', warning: 'warning', info: 'info' };
const ROW_COLORS = { success: '--green', skipped: '--grey', warning: '--orange', info: '--blue' };

const TestSuiteWizard = (/** @type Properties */ props) => {
    const { emit } = props;
    const initial = props.wizard.rawVal;

    // Python sends a fresh dict on every rerun; these only change when the content does.
    const wizardPart = (pick) => {
        const part = van.state(null);
        van.derive(() => {
            const next = pick(getValue(props.wizard)) ?? null;
            if (!isEqual(next, part.rawVal)) {
                part.val = next;
            }
        });
        return part;
    };
    const tableGroup = wizardPart((wizard) => wizard?.table_group);
    const filePreview = wizardPart((wizard) => wizard?.file_preview);
    const result = wizardPart((wizard) => wizard?.result);

    const form = createTestSuiteFormState({ table_groups_id: initial.table_group?.id });
    const validity = {
        testSuiteName: van.state(false),
        tableGroupId: van.state(!!initial.table_group?.id),
    };
    const step = van.state(0);
    const generate = van.state(false);
    const generationSets = van.state([...initial.default_generation_sets]);
    const startFrom = van.state('tables');
    const tableNames = van.state([]);
    const deleteConfirmed = van.state(false);
    const fileValue = van.state(null);

    const profiled = van.derive(() => !!tableGroup.val?.profiled_at);
    const isComplete = van.derive(() => result.val?.success === true);

    const resetTestsStep = (isProfiled) => {
        generate.val = isProfiled;
        generationSets.val = [...initial.default_generation_sets];
        startFrom.val = 'tables';
        tableNames.val = [];
        fileValue.val = null;
        deleteConfirmed.val = false;
    };
    van.derive(() => resetTestsStep(!!tableGroup.val?.profiled_at));

    const stepValid = [
        van.derive(() => validity.testSuiteName.val && validity.tableGroupId.val),
        van.derive(() => {
            if (form.suiteType.val === 'regular') {
                return !generate.val || generationSets.val.length > 0;
            }
            if (startFrom.val === 'tables') {
                return tableNames.val.length > 0;
            }
            const preview = filePreview.val;
            return !!preview && !preview.error && (!preview.summary?.delete || deleteConfirmed.val);
        }),
    ];

    const open = van.state(true);
    const close = () => {
        open.val = false;
        emit('WizardClosed', {});
    };

    const setStep = (index) => {
        step.val = index;
        document.activeElement?.blur();
    };

    const addTestSuite = () => emit('AddTestSuiteConfirmed', { payload: {
        ...testSuiteFormPayload(form),
        tests: form.suiteType.val === 'regular'
            ? { generate: generate.val, generation_sets: generate.val ? generationSets.val : [] }
            : startFrom.val === 'tables'
                ? { start_from: 'tables', table_names: tableNames.val }
                : { start_from: 'file' },
    } });

    const WizardStep = (index, content) => div(
        {
            class: () => `flex-column fx-gap-3 ${step.val !== index || isComplete.val ? 'hidden' : ''}`,
            'data-testid': `wizard-step-${STEP_NAMES[index]}`,
        },
        content,
    );

    const testSuiteStep = TestSuiteFields({
        state: form,
        validity,
        tableGroups: initial.table_groups,
        mode: 'add',
        onTableGroupChange: (id) => emit('WizardTableGroupSelected', { payload: { table_group_id: id } }),
        onTypeChange: () => {
            resetTestsStep(profiled.rawVal);
            emit('ContractFileCleared', {});
        },
    });

    const regularTestsStep = () => div(
        { class: 'flex-column fx-gap-3' },
        Checkbox({
            name: 'generate-tests',
            label: () => `Generate tests for the test suite ${form.testSuiteName.val}`,
            checked: generate,
            disabled: () => !profiled.val,
            onChange: (value) => generate.val = value,
        }),
        () => generate.val
            ? Select({
                label: 'Generation Sets',
                value: generationSets,
                multiSelect: true,
                required: true,
                options: initial.generation_sets.map((name) => ({ label: name, value: name })),
                onChange: (value) => generationSets.val = value,
            })
            : '',
        InfoCaption(() => {
            const group = tableGroup.val;
            if (!group) {
                return '';
            }
            if (!profiled.val) {
                return `${group.name} has not been profiled, so tests cannot be generated yet. Run profiling, then generate tests on the Test Suites page.`;
            }
            if (!generate.val) {
                return 'Test generation will be skipped. You can generate tests later on the Test Suites page.';
            }
            return `Tests are generated from the latest profiling run of ${group.name}, ${formatTimestamp(group.profiled_at)}.`;
        }),
    );

    const contractFromTables = () => {
        // The filterable Select reads its selection label while it is built, so building it here would make
        // this binding rebuild the picker, and close its options, on every pick. Rebuild on new tables only.
        let picker = null;
        let pickerTables = null;
        return div(
            { class: 'flex-column fx-gap-3' },
            () => {
                const tables = tableGroup.val?.tables ?? [];
                if (!picker || tables !== pickerTables) {
                    pickerTables = tables;
                    picker = ContractTablePicker({ tables, selected: tableNames });
                }
                return picker;
            },
            InfoCaption(() => {
                const group = tableGroup.val;
                if (!group) {
                    return '';
                }
                if (profiled.val) {
                    return `Tests are generated from the latest profiling run, ${formatTimestamp(group.profiled_at)}. ${METADATA_SENTENCE}`;
                }
                return `${group.name} has not been profiled, so no quality tests will be generated. ${METADATA_SENTENCE} Run profiling, then generate tests on the Test Suites page.`;
            }),
        );
    };

    const contractFromFile = () => div(
        { class: 'flex-column fx-gap-3' },
        FileInput({
            label: 'ODCS contract file',
            name: 'contract-file',
            // Read without subscribing: FileInput reads its value while it is built, and a subscription would
            // remount it empty whenever onChange below writes fileValue, losing a validation error.
            value: fileValue.rawVal,
            validators: [sizeLimit(initial.max_file_bytes)],
            onChange: (value, state) => {
                // FileInput replays onChange on mount with the value it was given.
                if (value === fileValue.val) {
                    return;
                }
                const hadFile = !!fileValue.val;
                const accepted = value?.content && state?.valid !== false ? value : null;
                fileValue.val = accepted;
                deleteConfirmed.val = false;
                if (accepted) {
                    emit('ContractFileUploaded', { payload: {
                        table_group_id: form.tableGroupId.val,
                        file: { name: accepted.name, size: accepted.size, content: accepted.content },
                    } });
                } else if (hadFile) {
                    emit('ContractFileCleared', {});
                }
            },
        }),
        ContractImportPreview({ preview: filePreview, deleteConfirmed }),
    );

    const contractTestsStep = () => div(
        { class: 'flex-column fx-gap-3' },
        RadioGroup({
            label: 'Start from',
            options: [
                { label: 'Table group', value: 'tables' },
                { label: 'ODCS file', value: 'file' },
            ],
            value: startFrom,
            layout: 'inline',
            onChange: (value) => {
                startFrom.val = value;
                if (value === 'tables') {
                    fileValue.val = null;
                    deleteConfirmed.val = false;
                    emit('ContractFileCleared', {});
                } else {
                    tableNames.val = [];
                }
            },
        }),
        () => startFrom.val === 'tables' ? contractFromTables() : contractFromFile(),
    );

    const successPanel = () => div(
        { class: 'flex-column' },
        div(
            { class: 'flex-column fx-gap-4 mb-4 p-5 border border-radius-2', 'data-testid': 'wizard-success-panel' },
            (result.val.rows ?? []).map((row) => div(
                { class: 'flex-row fx-gap-2' },
                Icon({ style: `color: var(${ROW_COLORS[row.icon]});` }, ROW_ICONS[row.icon]),
                div(
                    { class: 'flex-row fx-flex-wrap fx-gap-1' },
                    span(row.text),
                    row.link
                        ? Link({
                            emit,
                            open_new: true,
                            label: row.link.label,
                            href: row.link.href,
                            params: row.link.params,
                            right_icon: 'open_in_new',
                            right_icon_size: 13,
                        })
                        : '',
                ),
            )),
        ),
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            Button({ label: 'Close', type: 'stroked', color: 'primary', width: 'auto', onclick: close }),
        ),
    );

    const footer = div(
        { class: () => `flex-column fx-gap-3 mt-4 ${isComplete.val ? 'hidden' : ''}` },
        () => result.val?.success === false
            ? Alert({ type: 'error' }, span(result.val.message))
            : '',
        div(
            { class: 'flex-row' },
            () => step.val > 0
                ? Button({
                    label: 'Previous',
                    type: 'stroked',
                    color: 'basic',
                    width: 'auto',
                    style: 'margin-right: auto; min-width: 200px;',
                    onclick: () => setStep(step.val - 1),
                })
                : '',
            () => {
                const isLast = step.val === STEP_NAMES.length - 1;
                return Button({
                    label: isLast ? 'Add' : 'Next',
                    type: isLast ? 'flat' : 'stroked',
                    color: 'primary',
                    width: 'auto',
                    style: 'margin-left: auto; min-width: 200px;',
                    disabled: () => !stepValid[step.val].val,
                    onclick: () => isLast ? addTestSuite() : setStep(step.val + 1),
                });
            },
        ),
    );

    return Dialog(
        { title: 'Add Test Suite', open, onClose: close, width: '50rem' },
        div(
            { class: 'flex-column' },
            () => isComplete.val
                ? ''
                : WizardProgressIndicator(
                    [
                        { index: 0, title: 'Test Suite', skipped: false, includedSteps: [STEP_NAMES[0]] },
                        {
                            index: 1,
                            title: 'Tests',
                            skipped: form.suiteType.val === 'regular' && !generate.val,
                            includedSteps: [STEP_NAMES[1]],
                        },
                    ],
                    { index: step.val, name: STEP_NAMES[step.val] },
                    (name) => {
                        const index = STEP_NAMES.indexOf(name);
                        if (index < step.val) {
                            setStep(index);
                        }
                    },
                ),
            WizardStep(0, testSuiteStep),
            WizardStep(1, () => form.suiteType.val === 'regular' ? regularTestsStep() : contractTestsStep()),
            () => isComplete.val ? successPanel() : '',
            footer,
        ),
    );
};

const InfoCaption = (textFn) => () => {
    const text = textFn();
    return text
        ? div({ class: 'flex-row fx-gap-1' }, Icon({ size: 16 }, 'info'), span({ class: 'text-caption' }, text))
        : '';
};

export { TestSuiteWizard };
