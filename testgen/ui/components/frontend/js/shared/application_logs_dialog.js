import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Input } from '/app/static/js/components/input.js';
import { Button } from '/app/static/js/components/button.js';

const { a, div, label, pre, small, span } = van.tags;

/**
 * Dialog for viewing application logs.
 *
 * @param {object} props
 * @param {object} props.logsData - reactive state: { log_content, log_file_name, date }
 * @param {function} props.onClose
 * @param {function} props.onDateChanged - (dateString) => void
 * @param {function} props.onRefresh - () => void
 */
const ApplicationLogsDialog = (props) => {
    loadStylesheet('application-logs-dialog', stylesheet);

    const open = van.state(false);
    const data = van.state(null);
    const filterText = van.state('');

    van.derive(() => {
        const raw = getValue(props.logsData) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        filterText.val = '';
        props.onClose?.();
    };

    const filteredContent = van.derive(() => {
        const d = data.val;
        if (!d?.log_content) return '';

        const filter = filterText.val.toLowerCase();
        if (!filter) return d.log_content;

        return d.log_content
            .split('\n')
            .filter(line => line.toLowerCase().includes(filter))
            .join('\n');
    });

    const downloadFile = () => {
        const d = data.val;
        if (!d) return;
        const content = filteredContent.val;
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = d.log_file_name || 'application.log';
        anchor.click();
        URL.revokeObjectURL(url);
    };

    return Dialog(
        { title: 'Application Logs', open, onClose, width: '60rem' },
        () => {
            const d = data.val;
            if (!d) return '';

            return div(
                { class: 'tg-logs flex-column fx-gap-3' },
                div(
                    { class: 'flex-row fx-gap-3 fx-align-flex-end' },
                    div(
                        { class: 'flex-column', style: 'flex: 1' },
                        label({ class: 'text-caption' }, 'Log Date'),
                        van.tags.input({
                            type: 'date',
                            class: 'tg-logs--date-input',
                            value: d.date || '',
                            onchange: (e) => props.onDateChanged?.(e.target.value),
                        }),
                    ),
                    div(
                        { class: 'flex-column', style: 'flex: 1' },
                        Input({
                            label: 'Filter by Text',
                            value: filterText,
                            oninput: (e) => { filterText.val = e.target.value; },
                        }),
                    ),
                    div(
                        Button({
                            label: 'Refresh',
                            type: 'stroked',
                            onclick: () => props.onRefresh?.(),
                        }),
                    ),
                ),
                small({ class: 'text-caption' }, () => `Log File: ${d.log_file_name || 'N/A'}`),
                pre({ class: 'tg-logs--content' }, () => filteredContent.val || 'No log data available.'),
                div(
                    { style: 'margin-left: auto' },
                    Button({
                        label: 'Download',
                        icon: 'download',
                        type: 'stroked',
                        onclick: downloadFile,
                    }),
                ),
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-logs--date-input {
    padding: 6px 8px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-size: 14px;
    background: var(--dk-card-background);
    color: var(--primary-text-color);
}
.tg-logs--content {
    background: var(--app-background-color);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 12px;
    font-size: 12px;
    line-height: 1.5;
    max-height: 400px;
    overflow: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
}
`);

export { ApplicationLogsDialog };
