/**
 * @typedef Properties
 * @type {object}
 * @property {Array} columns
 * @property {Function?} onClose
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { ColumnSelector } from '/app/static/js/components/explorer_column_selector.js';
import { getValue } from '/app/static/js/utils.js';

const { div } = van.tags;

const ColumnSelectorDialog = (/** @type Properties */ props) => {
    const emit = props.emit;
    const dialogProp = getValue(props.dialog);
    const externalOpen = dialogProp?.open;
    const isVanState = externalOpen != null && typeof externalOpen === 'object' && 'val' in externalOpen;
    const dialogOpen = isVanState ? externalOpen : van.state(dialogProp?.open === true);
    if (!isVanState) {
        van.derive(() => { dialogOpen.val = getValue(props.dialog)?.open === true; });
    }

    const handleClose = () => {
        dialogOpen.val = false;
        if (typeof props.onClose === 'function') props.onClose();
        else emit('CloseClicked', {});
    };

    const content = div({ style: 'height: 400px;' }, ColumnSelector(props));

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Select Columns');
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

export { ColumnSelectorDialog };
