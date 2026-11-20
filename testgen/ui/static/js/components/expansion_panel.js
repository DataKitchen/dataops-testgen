/**
 * @typedef Options
 * @type {object}
 * @property {string} title
 * @property {bool} expanded
 * @property {string?} summary - the panel's values, shown beside the title while the panel is collapsed
 * @property {string?} help - what the panel is for, shown in place of an empty summary while the panel is collapsed
 * @property {string?} description - longer explanation shown below the title while the panel is expanded
 * @property {boolean?} invalid - replaces the summary with an error notice while the panel is collapsed
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
    div(
      { class: 'flex-row fx-gap-3 fx-align-flex-center' },
      span({}, options.title),
      () => {
        if (expanded.val) {
          return '';
        }
        if (getValue(options.invalid)) {
          return span({ class: 'text-caption text-error', 'data-testid': 'expansion-panel-summary' }, 'Contains errors');
        }
        const summary = getValue(options.summary);
        if (summary) {
          return span({ class: 'text-small text-secondary', 'data-testid': 'expansion-panel-summary' }, summary);
        }
        const help = getValue(options.help);
        return help ? span({ class: 'tg-expansion-panel--help text-caption', 'data-testid': 'expansion-panel-help' }, help) : '';
      },
    ),
    Icon({}, () => expanded.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down'),
  );

  const descriptionDiv = options.description
    ? div(
      {
        class: 'text-small text-secondary mt-1',
        style: () => expanded.val ? '' : 'display:none',
        'data-testid': 'expansion-panel-description',
      },
      options.description,
    )
    : '';

  const contentDiv = div(
    { class: 'tg-expansion-panel--content mt-4', style: () => expanded.val ? '' : 'display:none' },
    ...children,
  );

  titleDiv.addEventListener('click', () => {
    expanded.val = !expanded.val;
  });

  return div(
    { class: 'tg-expansion-panel', 'data-testid': 'expansion-panel' },
    titleDiv,
    descriptionDiv,
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

.tg-expansion-panel--help {
    font-style: italic;
}

.tg-expansion-panel--title:hover {
    color: var(--primary-color);
}

.tg-expansion-panel--title:hover i.tg-icon {
    color: var(--primary-color) !important;
}
`);

export { ExpansionPanel };
