/**
 * @typedef Options
 * @type {object}
 * @property {string?} id
 * @property {string?} testId
 * @property {string?} class
 * @property {string?} language - Language for syntax highlighting (e.g. 'sql', 'html'). Omit for no highlighting.
 */

import hljs from '../highlight.min.js';
import van from '../van.min.js';
import { getRandomId, loadStylesheet } from '../utils.js';
import { Icon } from './icon.js';

const { div, pre, code } = van.tags;

/**
 *
 * @param  {Options} options
 * @param  {...HTMLElement} children
 */
const Code = (options, ...children) => {
    loadStylesheet('code', stylesheet);

    const domId = options.id ?? `code-snippet-${getRandomId()}`;
    const language = options.language;
    const codeClass = language ? `language-${language}` : 'nohighlight';

    const codeEl = code(
        { class: codeClass },
        ...children,
    );

    const el = div(
        { id: domId, class: `tg-code ${options.class ?? ''}`, 'data-testid': options.testId ?? '' },
        pre({}, codeEl),
        Icon(
            {
                classes: 'tg-code--copy',
                onclick: () => {
                    const content = codeEl.textContent || codeEl.innerText;
                    if (content) {
                        navigator.clipboard.writeText(content.trim());
                    }
                },
            },
            'content_copy',
        ),
    );

    if (language) {
        requestAnimationFrame(() => {
            if (codeEl.isConnected && hljs) {
                hljs.highlightElement(codeEl);
            }
        });
    }

    return el;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-code {
    position: relative;
    overflow-y: auto;
}
.tg-code pre {
    margin: 0;
    overflow-x: auto;
}
.tg-code--copy {
    position: absolute;
    top: 6px;
    right: 6px;
    cursor: pointer;
    opacity: 0.4;
    transition: opacity 0.2s;
}
.tg-code:hover .tg-code--copy {
    opacity: 1;
}
`);

export { Code };
