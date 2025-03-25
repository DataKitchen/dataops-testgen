/**
 * @typedef Properties
 * @type {object}
 * @property {number?} size
 * @property {string} classes
 */
import { getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';

const { i } = van.tags;
const DEFAULT_SIZE = 20;

const Icon = (/** @type Properties */ props, /** @type string */ icon) => {
    loadStylesheet('icon', stylesheet);
    return i(
        {
            class: () => `material-symbols-rounded tg-icon text-secondary ${getValue(props.classes)}`,
            style: () => `font-size: ${getValue(props.size) || DEFAULT_SIZE}px;`,
            ...props,
        },
        icon,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-icon {
    position: relative;
    cursor: default;
}
`);

export { Icon };
