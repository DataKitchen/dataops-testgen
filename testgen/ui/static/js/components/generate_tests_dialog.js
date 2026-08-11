/**
 * @typedef RefreshWarning
 * @type {object}
 * @property {number} test_ct
 * @property {number} unlocked_test_ct
 * @property {number} unlocked_edits_ct
 * @property {Object.<string, number>} unlocked_counts_by_type
 *
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 *
 * @typedef Properties
 * @type {object}
 * @property {string} test_suite_id
 * @property {string} test_suite_name
 * @property {string[]} generation_sets
 * @property {string[]} selected_generation_sets
 * @property {Object.<string, string[]>} generation_set_test_types
 * @property {Object.<string, string[]>} overriding_test_types
 * @property {RefreshWarning?} refresh_warning
 * @property {string?} lock_result
 * @property {Result?} result
 * @property {Function?} onClose
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Select } from '/app/static/js/components/select.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';

const { div, span, strong } = van.tags;

const GenerateTestsDialog = (/** @type Properties */ props) => {
    const emit = props.emit;
    loadStylesheet('generate-tests-dialog', stylesheet);

    const dialogProp = getValue(props.dialog);
    const externalOpen = dialogProp?.open;
    const isVanState = externalOpen != null && typeof externalOpen === 'object' && 'val' in externalOpen;
    const dialogOpen = isVanState ? externalOpen : van.state(dialogProp?.open === true);
    if (!isVanState) {
        van.derive(() => { if (getValue(props.dialog)?.open === true) dialogOpen.val = true; });
    }

    const handleClose = () => {
        dialogOpen.val = false;
        if (typeof props.onClose === 'function') props.onClose();
        else emit('CloseClicked', {});
    };

    const testSuiteId = getValue(props.test_suite_id);
    const testSuiteName = getValue(props.test_suite_name);
    const generationSets = getValue(props.generation_sets) ?? [];
    const storedSets = getValue(props.selected_generation_sets) ?? [];
    const setMembers = getValue(props.generation_set_test_types) ?? {};
    const overridingTypes = getValue(props.overriding_test_types) ?? {};
    const selectedSets = van.state(storedSets.filter((s) => generationSets.includes(s)));
    const submitDisabled = van.derive(() => selectedSets.val.length === 0);

    const content = div(
        { class: 'flex-column fx-gap-3 generate-tests--wrapper' },
        generationSets.length > 0
            ? Select({
                label: 'Generation Sets',
                value: selectedSets,
                multiSelect: true,
                required: true,
                options: generationSets.map(s => ({ value: s, label: s })),
                portalClass: 'generate-tests--select',
            })
            : '',
        () => {
            const warning = getValue(props.refresh_warning);
            if (!warning || !warning.test_ct) return '';

            let message = '';
            if (warning.unlocked_edits_ct > 0) {
                message = 'Manual changes have been made to auto-generated tests in this test suite that have not been locked. ';
            } else if (warning.unlocked_test_ct > 0) {
                message = 'Auto-generated tests are present in this test suite that have not been locked. ';
            }

            const selected = selectedSets.val;
            const counts = warning.unlocked_counts_by_type ?? {};
            const generatedTypes = new Set(selected.flatMap(s => setMembers[s] ?? []));
            const addedTypes = new Set(
                selected.filter(s => !storedSets.includes(s)).flatMap(s => setMembers[s] ?? []),
            );

            // A test is dropped when no selected set generates its type, and also when a
            // newly selected set generates a type that overrides it. Whether an overriding
            // type lands on the same column depends on the profiling data, so the second
            // group is an upper bound and the total is reported as such.
            let uncoveredCount = 0;
            let overriddenCount = 0;
            for (const [testType, count] of Object.entries(counts)) {
                if (!generatedTypes.has(testType)) {
                    uncoveredCount += count;
                } else if ((overridingTypes[testType] ?? []).some(t => addedTypes.has(t))) {
                    overriddenCount += count;
                }
            }
            const doomedCount = uncoveredCount + overriddenCount;
            const removedSets = storedSets.filter(s => !selected.includes(s));

            let deselectionMessage = '';
            if (doomedCount > 0) {
                const testNoun = doomedCount === 1 ? 'test' : 'tests';
                if (overriddenCount > 0) {
                    deselectionMessage = `Up to ${doomedCount} unlocked auto-generated ${testNoun} will be deleted.`;
                } else {
                    deselectionMessage = removedSets.length > 0
                        ? `Deselecting ${removedSets.join(', ')} will delete ${doomedCount} unlocked auto-generated ${testNoun}.`
                        : `${doomedCount} unlocked auto-generated ${testNoun} ${doomedCount === 1 ? 'is' : 'are'} not covered by the selected generation sets and will be deleted.`;
                }
            }

            return div(
                { class: 'flex-column fx-gap-2' },
                Alert(
                    { type: 'warn' },
                    div(message),
                    div({ class: 'mt-1' }, `Generating tests now will overwrite unlocked tests subject to auto-generation based on the latest profiling.`),
                    deselectionMessage ? div({ class: 'mt-1' }, deselectionMessage) : '',
                    div({ class: 'mt-1 text-caption' }, `Auto-generated Tests: ${warning.test_ct}, Unlocked: ${warning.unlocked_test_ct}, Edited Unlocked: ${warning.unlocked_edits_ct}`),
                ),
                warning.unlocked_edits_ct > 0
                    ? div(
                        () => {
                            const lockResult = getValue(props.lock_result);
                            return lockResult
                                ? Alert({ type: 'success' }, span(lockResult))
                                : Button({
                                    type: 'stroked',
                                    label: 'Lock Edited Tests',
                                    width: 'auto',
                                    onclick: () => emit('LockEditedTests', {}),
                                });
                        },
                    )
                    : '',
            );
        },
        div(
            span('Execute test generation for the test suite '),
            strong({}, testSuiteName),
            span('?'),
        ),
        () => {
            const result = getValue(props.result) ?? {};
            return result.message
                ? Alert({ type: result.success ? 'success' : 'error' }, span(result.message))
                : '';
        },
        () => !getValue(props.result)
            ? div(
                { class: 'flex-row fx-justify-content-flex-end mt-3' },
                Button({
                    label: 'Generate Tests',
                    type: 'stroked',
                    color: 'primary',
                    width: 'auto',
                    style: 'width: auto;',
                    disabled: submitDisabled,
                    onclick: () => emit('GenerateTestsConfirmed', {
                        payload: {
                            test_suite_id: testSuiteId,
                            test_suite_name: testSuiteName,
                            generation_sets: selectedSets.val,
                        },
                    }),
                }),
            )
            : '',
    );

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Generate Tests');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: handleClose,
                width: '36rem',
            },
            content,
        );
    }
    return content;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.generate-tests--wrapper {
    min-height: 120px;
}

.generate-tests--select {
    max-height: 200px !important;
}
`);

export { GenerateTestsDialog };
