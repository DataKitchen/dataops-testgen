/**
 * @typedef Properties
 * @type {object}
 * @property {string} table_name
 * @property {string} script
 * @property {Function?} onClose
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Code } from '/app/static/js/components/code.js';
import { emitEvent, getValue } from '/app/static/js/utils.js';

const { div, span } = van.tags;

const TableCreateScriptDialog = (/** @type Properties */ props) => {
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

    const content = div(
        { class: 'flex-column fx-gap-2' },
        div(
            span({ class: 'text-secondary text-caption' }, 'Table: '),
            span({ style: 'font-weight: 500;' }, () => getValue(props.table_name)),
        ),
        () => Code({}, getValue(props.script) ?? ''),
    );

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Table CREATE Script');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: handleClose,
                width: '55rem',
            },
            content,
        );
    }
    return content;
};

export { TableCreateScriptDialog };
