/**
 * @typedef Properties
 * @type {object}
 * @property {number?} size
 * @property {string?} classes
 */
import { getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';

const { span } = van.tags;
const DEFAULT_SIZE = 16;

const Spinner = (/** @type Properties */ props = {}) => {
    loadStylesheet('spinner', stylesheet);

    return span({
        class: () => `tg-spinner ${getValue(props.classes) ?? ''}`,
        style: () => {
            const size = getValue(props.size) || DEFAULT_SIZE;
            return `width: ${size}px; height: ${size}px;`;
        },
        role: 'status',
        'aria-label': 'Loading',
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-spinner {
    display: inline-block;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: 50%;
    animation: tg-spin 0.6s linear infinite;
    flex-shrink: 0;
}

@keyframes tg-spin {
    to { transform: rotate(360deg); }
}
`);

export { Spinner };
