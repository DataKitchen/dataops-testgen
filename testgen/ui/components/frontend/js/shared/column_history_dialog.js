import van from '/app/static/js/van.min.js';
import { getValue } from '/app/static/js/utils.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { ColumnProfilingHistory } from '../data_profiling/column_profiling_history.js';

/**
 * Shared dialog for displaying column profiling history.
 *
 * @param {object} props
 * @param {object} props.historyData - reactive state: set to data object to open, null to close
 *   Shape: { table_name, column_name, profiling_runs, selected_item }
 * @param {function} props.onClose - called when dialog is closed
 * @param {function} props.onRunSelected - called when a profiling run is selected
 */
const ColumnHistoryDialog = (props) => {
    const open = van.state(false);
    const data = van.state(null);

    van.derive(() => {
        const raw = getValue(props.historyData) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        props.onClose?.();
    };

    const profilingRuns = van.derive(() => data.val?.profiling_runs ?? []);
    const selectedItem = van.derive(() => data.val?.selected_item ?? null);
    const title = van.derive(() => {
        const d = data.val;
        return d ? `Column History: ${d.table_name} > ${d.column_name}` : 'Column History';
    });

    return Dialog(
        { title, open, onClose, width: '60rem' },
        () => data.val
            ? ColumnProfilingHistory({
                profiling_runs: profilingRuns,
                selected_item: selectedItem,
                onRunSelected: props.onRunSelected,
            })
            : '',
    );
};

export { ColumnHistoryDialog };
