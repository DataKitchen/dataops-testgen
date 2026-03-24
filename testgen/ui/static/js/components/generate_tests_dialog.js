/**
 * @typedef RefreshWarning
 * @type {object}
 * @property {number} test_ct
 * @property {number} unlocked_test_ct
 * @property {number} unlocked_edits_ct
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
 * @property {string?} default_generation_set
 * @property {RefreshWarning?} refresh_warning
 * @property {string?} lock_result
 * @property {Result?} result
 * @property {Function?} onClose
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Code } from '/app/static/js/components/code.js';
import { ExpanderToggle } from '/app/static/js/components/expander_toggle.js';
import { Select } from '/app/static/js/components/select.js';
import { emitEvent, getValue, loadStylesheet } from '/app/static/js/utils.js';

const { div, span, strong } = van.tags;

const GenerateTestsDialog = (/** @type Properties */ props) => {
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
        else emitEvent('CloseClicked', {});
    };

    const testSuiteId = getValue(props.test_suite_id);
    const testSuiteName = getValue(props.test_suite_name);
    const generationSets = getValue(props.generation_sets) ?? [];
    const defaultSet = getValue(props.default_generation_set) ?? (generationSets[0] ?? '');
    const selectedSet = van.state(defaultSet);

    const showCLI = van.state(false);

    const content = div(
        { class: 'flex-column fx-gap-3 generate-tests--wrapper' },
        generationSets.length > 0
            ? Select({
                label: 'Generation Set',
                value: selectedSet,
                allowNull: false,
                options: generationSets.map(s => ({ value: s, label: s })),
                onChange: (value) => { selectedSet.val = value; },
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
            return div(
                { class: 'flex-column fx-gap-2' },
                Alert(
                    { type: 'warn' },
                    div(message),
                    div({ class: 'mt-1' }, `Generating tests now will overwrite unlocked tests subject to auto-generation based on the latest profiling.`),
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
                                    onclick: () => emitEvent('LockEditedTests', {}),
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
        ExpanderToggle({
            expandLabel: 'Show CLI command',
            collapseLabel: 'Collapse',
            onExpand: () => showCLI.val = true,
            onCollapse: () => showCLI.val = false,
        }),
        () => Code({ class: showCLI.val ? '' : 'hidden' }, `testgen run-test-generation --test-suite-id ${testSuiteId} --generation-set '${selectedSet.val}'`),
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
                    onclick: () => emitEvent('GenerateTestsConfirmed', {
                        payload: {
                            test_suite_id: testSuiteId,
                            generation_set: selectedSet.val,
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
