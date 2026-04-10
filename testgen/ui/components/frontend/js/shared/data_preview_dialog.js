import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Table } from '/app/static/js/components/table.js';

const { div, span } = van.tags;

/**
 * Shared dialog for displaying a data preview from a target database.
 *
 * @param {object} props
 * @param {object} props.previewData - reactive state: set to data object to open, null to close
 *   Shape: { title, columns?, rows?, status?, message? }
 * @param {function} props.onClose - called when dialog is closed
 */
const DataPreviewDialog = (props) => {
    const emit = props.emit;
    loadStylesheet('data-preview-dialog', stylesheet);
    const open = van.state(false);
    const data = van.state(null);

    van.derive(() => {
        const raw = getValue(props.previewData) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        props.onClose?.();
    };

    const title = van.derive(() => data.val?.title ?? 'Data Preview');

    return Dialog(
        { title, open, onClose, width: '70rem' },
        () => {
            const d = data.val;
            if (!d) return '';

            if (d.status === 'ND' || d.status === 'NA') {
                return div({ class: 'tg-dp--info-msg' }, d.message);
            }
            if (d.status === 'ERR') {
                return div({ class: 'tg-dp--error-msg' }, d.message);
            }

            if (d.rows?.length) {
                const columns = d.columns.map(name => ({ name, label: name, overflow: 'hidden', align: 'left' }));
                const tableRows = van.state(d.rows.map(row => {
                    const obj = {};
                    d.columns.forEach((col, i) => {
                        const v = row[i];
                        if (v === null || v === undefined) {
                            obj[col] = span({ class: 'tg-dp--null' }, 'NULL');
                        } else if (v === '') {
                            obj[col] = span({ class: 'tg-dp--empty' }, 'EMPTY');
                        } else {
                            obj[col] = v;
                        }
                    });
                    return obj;
                }));
                return div(
                    { style: 'margin-bottom: 12px' },
                    Table({ emit, columns, highDensity: true, uppercaseHeader: false, height: '500px' }, tableRows),
                );
            }

            return div({ class: 'tg-dp--info-msg' }, 'No data available.');
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-dp--info-msg {
    padding: 8px 12px;
    background: var(--blue-light, #e3f2fd);
    border-radius: 4px;
    color: var(--primary-text-color);
    font-size: 14px;
}
.tg-dp--error-msg {
    padding: 8px 12px;
    background: var(--red-light, #ffebee);
    border-radius: 4px;
    color: var(--red, #c62828);
    font-size: 14px;
}
.tg-dp--null,
.tg-dp--empty {
    color: var(--disabled-text-color);
    font-style: italic;
}
`);

export { DataPreviewDialog };
