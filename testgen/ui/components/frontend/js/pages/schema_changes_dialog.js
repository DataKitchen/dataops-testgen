/**
 * @typedef Properties
 * @type {object}
 * @property {number} window_start
 * @property {number} window_end
 * @property {object[]?} data_structure_logs
 * @property {{ open: boolean, title: string }?} dialog
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { SchemaChangesList } from '/app/static/js/components/schema_changes_list.js';
import { emitEvent, getValue } from '/app/static/js/utils.js';

const { div } = van.tags;

const SchemaChangesDialog = (/** @type Properties */ props) => {
    const dialogOpen = van.state(false);
    van.derive(() => {
        const d = getValue(props.dialog);
        if (d?.open) dialogOpen.val = true;
        else dialogOpen.val = false;
    });

    // SchemaChangesList reads props non-reactively, so defer creation
    // until data is available. Clear on close for fresh content next time.
    const contentContainer = div();
    let contentMounted = false;

    van.derive(() => {
        const logs = getValue(props.data_structure_logs);
        if (logs && !contentMounted) {
            contentMounted = true;
            van.add(contentContainer, SchemaChangesList(props));
        } else if (!logs && contentMounted) {
            contentMounted = false;
            contentContainer.replaceChildren();
        }
    });

    const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Schema Changes');
    return Dialog(
        {
            title: dialogTitle,
            open: dialogOpen,
            onClose: () => { dialogOpen.val = false; emitEvent('CloseSchemaChangesDialog', {}); },
            width: '30rem',
        },
        contentContainer,
    );
};

export { SchemaChangesDialog };
