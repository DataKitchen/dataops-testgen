/**
 * @typedef Properties
 * @type {object}
 * @property {object?} title
 * @property {object} content
 * @property {object?} actionContent
 * @property {boolean?} border
 * @property {string?} id
 * @property {string?} class
 * @property {string?} testId
 */
import { loadStylesheet } from '../utils.js';
import van from '../van.min.js';

const { div, h3 } = van.tags;

const Card = (/** @type Properties */ props) => {
    loadStylesheet('card', stylesheet);

    return div(
        { class: `tg-card mb-4 ${props.border ? 'tg-card-border' : ''} ${props.class}`, id: props.id ?? '', 'data-testid': props.testId ?? '' },
        () =>
            props.title || props.actionContent ?
            div(
                { class: 'flex-row fx-justify-space-between fx-align-flex-start fx-gap-4' },
                () => 
                    props.title ?
                    h3(
                        { class: 'tg-card--title' },
                        props.title,
                    ) :
                    '',
                props.actionContent,
            ) :
            '',
        props.content,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-card {
    border-radius: 8px;
    background-color: var(--dk-card-background);
    padding: 16px;
}

.tg-card-border {
    border: 1px solid var(--border-color);
}

.tg-card--title {
    margin: 0 0 16px;
    color: var(--secondary-text-color);
    font-size: 16px;
    font-weight: 500;
    text-transform: capitalize;
}
`);

export { Card };
