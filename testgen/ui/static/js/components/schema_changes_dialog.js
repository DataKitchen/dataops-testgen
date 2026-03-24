/**
 * @typedef Properties
 * @type {object}
 * @property {number} window_start
 * @property {number} window_end
 * @property {object[]?} data_structure_logs
 * @property {Function?} onClose
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { SchemaChangesList } from '/app/static/js/components/schema_changes_list.js';
import { emitEvent, getValue } from '/app/static/js/utils.js';

const { div } = van.tags;

const SchemaChangesDialog = (/** @type Properties */ props) => {
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

    const content = div(SchemaChangesList(props));

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Schema Changes');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: handleClose,
                width: '30rem',
            },
            content,
        );
    }
    return content;
};

export { SchemaChangesDialog };
