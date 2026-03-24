import van from '/app/static/js/van.min.js';
import { getValue } from '/app/static/js/utils.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { ColumnProfilingResults } from '../data_profiling/column_profiling_results.js';

/**
 * Shared dialog for displaying column profiling results.
 *
 * @param {object} props
 * @param {object} props.profilingColumn - reactive state: set to column data to open, null to close
 * @param {function} props.onClose - called when dialog is closed
 * @param {string} [props.width='52rem']
 * @param {string} [props.testId]
 */
const ProfilingResultsDialog = (props) => {
    const open = van.state(false);
    const columnData = van.state(null);

    van.derive(() => {
        const raw = getValue(props.profilingColumn) ?? null;
        columnData.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        props.onClose?.();
    };

    const columnJson = van.derive(() => columnData.val ? JSON.stringify(columnData.val) : null);

    return Dialog(
        { title: 'Column Profiling Results', open, onClose, width: props.width || '52rem', testId: props.testId },
        () => columnJson.val ? ColumnProfilingResults({ column: columnJson }) : '',
    );
};

export { ProfilingResultsDialog };
