/**
 * A date field using the browser's own date picker. Its value is a `YYYY-MM-DD` string, empty when no date is
 * chosen.
 *
 * Takes every property `Input` does, except `type`.
 */
import { loadStylesheet } from '../utils.js';
import { Input } from './input.js';

const DateInput = (/** @type import('./input.js').Properties */ props) => {
    loadStylesheet('date-input', stylesheet);
    return Input({ ...props, type: 'date', class: `tg-date-input ${props.class ?? ''}` });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-date-input input {
    color-scheme: light;
}

@media (prefers-color-scheme: dark) {
    .tg-date-input input {
        color-scheme: dark;
    }
}
`);

export { DateInput };
