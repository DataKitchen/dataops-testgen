/**
 * @typedef GenerationSetOption
 * @type {object}
 * @property {string} value
 * @property {string} label
 * @property {string?} help
 *
 * @typedef Properties
 * @type {object}
 * @property {GenerationSetOption[]} options
 * @property {object} selected - VanJS state holding the selected set names
 * @property {(function(): boolean)?} disabled
 * @property {string?} label
 */
import van from '../van.min.js';
import { Checkbox } from './checkbox.js';

const { div } = van.tags;

const GenerationSetPicker = (/** @type Properties */ props) => {
    const toggle = (value, checked) => {
        const others = props.selected.rawVal.filter((name) => name !== value);
        props.selected.val = checked
            ? props.options.map((option) => option.value).filter((name) => name === value || others.includes(name))
            : others;
    };

    return div(
        { class: 'flex-column fx-gap-2', 'data-testid': 'generation-set-picker' },
        props.label === null ? '' : div({ class: 'text-caption' }, props.label ?? 'Generation Sets'),
        props.options.map(({ value, label, help }) => div(
            { class: 'flex-column fx-gap-1' },
            Checkbox({
                name: `generation-set-${value}`,
                label,
                checked: () => props.selected.val.includes(value),
                disabled: () => props.disabled?.() ?? false,
                onChange: (checked) => toggle(value, checked),
            }),
            help ? div({ class: 'text-secondary text-small pl-5' }, help) : '',
        )),
    );
};

export { GenerationSetPicker };
