/**
 * @typedef Options
 * @type {object}
 * @property {string?} id
 * @property {string?} testId
 * @property {string?} class
 */

import van from '../van.min.js';
import { getRandomId } from '../utils.js';
import { Icon } from './icon.js';

const { code } = van.tags;

/**
 * 
 * @param  {Options} options
 * @param  {...HTMLElement} children 
 */
const Code = (options, ...children) => {
    const domId = options.id ?? `code-snippet-${getRandomId()}`;
    const icon = 'content_copy';

    return code(
        { ...options, id: domId, class: options.class ?? '', 'data-testid': options.testId ?? '' },
        ...children,
        Icon(
            {
                classes: '',
                onclick: () => {
                    const parentElement = document.getElementById(domId);
                    const content = (parentElement.textContent || parentElement.innerText).replace(icon, '');
                    if (content) {
                        navigator.clipboard.writeText(content);
                    }
                },
            },
            'content_copy',
        ),
    );
};

export { Code };
