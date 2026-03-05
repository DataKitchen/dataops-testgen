/**
 * @typedef DialogProps
 * @type {object}
 * @property {(string | import('../van.min.js').State<string>)} title - Dialog title
 * @property {import('../van.min.js').State<boolean>} open - Reactive open state
 * @property {Function} onClose - Called when the dialog is closed (backdrop click or X button)
 * @property {string} [width] - CSS width value, default '30rem'
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { button, div, i, span } = van.tags;

/**
 * A dialog component that mimics Streamlit's dialog visual style.
 * Opens as a fixed-position overlay covering the full viewport so it
 * works from within any V2 component container, regardless of depth.
 *
 * Usage:
 *   const open = van.state(false);
 *
 *   Dialog(
 *       { title: 'Confirm', open, onClose: () => open.val = false },
 *       div('Are you sure?'),
 *       Button({ label: 'Confirm', onclick: () => { doThing(); open.val = false; } }),
 *   )
 *
 * @param {DialogProps} props
 * @param {...(Element | string)} children - Content rendered in the dialog body
 */
const Dialog = ({ title, open, onClose, width = '30rem' }, ...children) => {
    loadStylesheet('dialog', stylesheet);

    return div(
        {
            class: 'tg-dialog-overlay',
            style: () => open.val ? '' : 'display: none',
            onclick: () => onClose(),
        },
        div(
            {
                class: 'tg-dialog',
                role: 'dialog',
                'aria-modal': 'true',
                tabindex: '-1',
                style: () => `width: ${getValue(width)}`,
                onclick: (e) => e.stopPropagation(),
            },
            div(
                { class: 'tg-dialog-header' },
                span({ class: 'tg-dialog-title' }, title),
            ),
            div({ class: 'tg-dialog-content' }, ...children),
            button(
                {
                    class: 'tg-dialog-close',
                    'aria-label': 'Close',
                    onclick: () => onClose(),
                },
                i({ class: 'material-symbols-rounded' }, 'close'),
            ),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-dialog-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(49, 51, 63, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
}

.tg-dialog {
    position: relative;
    background: var(--portal-background, white);
    border-radius: 8px;
    box-shadow: var(--portal-box-shadow, 0 4px 32px rgba(0, 0, 0, 0.25));
    max-width: calc(100vw - 2rem);
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.tg-dialog-header {
    padding: 1.5rem 3.5rem 0.75rem 1.5rem;
    font-size: 1.5rem;
    font-weight: 600;
    line-height: 1.5;
    display: flex;
    align-items: center;
    flex-shrink: 0;
}

.tg-dialog-content {
    padding: 0.75rem 1.5rem 1.5rem;
    overflow-y: auto;
    color: var(--primary-text-color);
}

.tg-dialog-close {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    padding: 0;
    border: none;
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    color: var(--secondary-text-color);
    transition: background 200ms;
}

.tg-dialog-close:hover {
    background: rgba(0, 0, 0, 0.08);
}

.tg-dialog-close .material-symbols-rounded {
    font-size: 18px;
    line-height: 18px;
}
`);

export { Dialog };
