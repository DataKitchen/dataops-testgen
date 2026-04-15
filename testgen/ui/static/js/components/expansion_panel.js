/**
 * @typedef Options
 * @type {object}
 * @property {string} title
 * @property {string?} testId
 * @property {bool} expanded
 */

import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { Icon } from './icon.js';

const { div, span } = van.tags;

/**
 *
 * @param  {Options} options
 * @param  {...HTMLElement} children
 */
const ExpansionPanel = (options, ...children) => {
  loadStylesheet('expansion-panel', stylesheet);

  const expanded = van.state(getValue(options.expanded) ?? false);
  if (options.expanded?.val !== undefined) {
    van.derive(() => {
      expanded.val = getValue(options.expanded);
    });
  }

  const titleDiv = div(
    {
      class: 'tg-expansion-panel--title flex-row fx-justify-space-between clickable',
      'data-testid': 'expansion-panel-trigger',
    },
    span({}, options.title),
    Icon({}, () => expanded.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down'),
  );

  const contentDiv = div(
    { class: 'tg-expansion-panel--content mt-4', style: () => expanded.val ? '' : 'display:none' },
    ...children,
  );

  titleDiv.addEventListener('click', () => {
    expanded.val = !expanded.val;
  });

  return div(
    { class: 'tg-expansion-panel', 'data-testid': options.testId ?? '' },
    titleDiv,
    contentDiv,
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
`);

export { ExpansionPanel };
