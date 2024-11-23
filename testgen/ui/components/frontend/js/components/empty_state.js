/**
* @typedef Message
* @type {object}
* @property {string} line1
* @property {string} line2
*
* @typedef Link
* @type {object}
* @property {string} href
* @property {string} label
*
* @typedef Properties
* @type {object}
* @property {string} icon
* @property {string} label
* @property {Message} message
* @property {Link} link
*/
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { loadStylesheet } from '../utils.js';
import { Link } from './link.js';

const { i, span, strong } = van.tags;

const EmptyState = (/** @type Properties */ props) => {
    loadStylesheet('empty-state', stylesheet);

    return Card({
        class: 'tg-empty-state flex-column fx-align-flex-center',
        content: [
            span({ class: 'tg-empty-state--title mb-5' }, props.label),
            i({class: 'material-symbols-rounded mb-5'}, props.icon),
            strong({ class: 'mb-2' }, props.message.line1),
            span({ class: 'mb-5' }, props.message.line2),
            Link({
                class: 'tg-empty-state--link',
                right_icon: 'chevron_right',
                ...props.link,
            }),
        ],
    });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-empty-state {
    margin-top: 80px;
    border: 1px solid var(--border-color);
    padding: 112px 0px !important;
}

.tg-empty-state--title {
    font-size: 24px;
    color: var(--secondary-text-color);
}

.tg-empty-state > i {
    font-size: 60px;
    color: var(--disabled-text-color);
}

.tg-empty-state > .tg-empty-state--link {
    margin: auto;
    border-radius: 4px;
    border: var(--button-stroked-border);
    padding: 8px 8px 8px 16px;
    color: var(--primary-color);
}
`);

export { EmptyState };
