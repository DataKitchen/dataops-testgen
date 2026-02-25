/**
* @typedef Properties
* @type {object}
* @property {string} content
* @property {string?} style
*/
import van from '../van.min.js';
import { loadStylesheet } from '../utils.js';

const { span } = van.tags;

const Caption = (/** @type Properties */ props) => {
    loadStylesheet('caption', stylesheet);

   return span(
       { class: 'tg-caption', style: props.style },
       props.content
   );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-caption {
    color: var(--caption-text-color);
    font-size: 14px;
}
`);

export { Caption };
