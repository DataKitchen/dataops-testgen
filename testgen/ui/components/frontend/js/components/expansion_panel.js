/**
 * @typedef Options
 * @type {object}
 * @property {string} title
 * @property {string?} testId
 */

import van from '../van.min.js';
import { loadStylesheet } from '../utils.js';
import { Icon } from './icon.js';

const { div, span } = van.tags;

/**
 * 
 * @param  {Options} options
 * @param  {...HTMLElement} children 
 */
const ExpansionPanel = (options, ...children) => {
    loadStylesheet('expansion-panel', stylesheet);

    const expanded = van.state(false);
    const icon = van.derive(() => expanded.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down');
    const expansionClass = van.derive(() => expanded.val ? '' : 'collapsed');

    return div(
        { class: () => `tg-expansion-panel ${expansionClass.val}`, 'data-testid': options.testId ?? '' },
        div(
            {
                class: 'tg-expansion-panel--title flex-row fx-justify-space-between clickable',
                'data-testid': 'expansion-panel-trigger',
                onclick: () => expanded.val = !expanded.val,
            },
            span({}, options.title),
            Icon({}, icon),
        ),
        div(
            { class: 'tg-expansion-panel--content mt-4' },
            ...children,
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-expansion-panel {
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 12px;
}

.tg-expansion-panel--title:hover {
    color: var(--primary-color);
}

.tg-expansion-panel--title:hover i.tg-icon {
    color: var(--primary-color) !important;
}

.tg-expansion-panel.collapsed > .tg-expansion-panel--content {
    height: 0;
    display: none;
}
`);

export { ExpansionPanel };
