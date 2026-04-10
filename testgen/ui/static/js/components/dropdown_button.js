/**
 * @typedef DropdownItem
 * @type {object}
 * @property {string} label
 * @property {() => void} onclick
 *
 * @typedef DropdownButtonProps
 * @type {object}
 * @property {string} icon
 * @property {string} label
 * @property {('normal' | 'small')?} buttonSize
 * @property {DropdownItem[] | (() => DropdownItem[])} items
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Portal } from '/app/static/js/components/portal.js';
import { getRandomId, loadStylesheet } from '/app/static/js/utils.js';

const { div } = van.tags;

/**
 * A button that opens a dropdown menu with a list of items.
 * @param {DropdownButtonProps} props
 */
const DropdownButton = (props) => {
    loadStylesheet('dropdown-button', stylesheet);

    const buttonId = `dropdown-btn-${getRandomId()}`;
    const menuOpen = van.state(false);

    return [
        Button({
            id: buttonId,
            type: 'stroked',
            color: 'basic',
            icon: props.icon,
            label: props.label,
            width: 'fit-content',
            style: 'background-color: var(--button-generic-background-color);',
            size: props.buttonSize,
            onclick: () => { menuOpen.val = !menuOpen.val; },
        }),
        Portal(
            { target: buttonId, opened: menuOpen, align: 'right' },
            () => {
                const items = typeof props.items === 'function' ? props.items() : props.items;
                return div(
                    { class: 'tg-dropdown-button--menu' },
                    ...items.map(item =>
                        div({
                            class: 'tg-dropdown-button--item',
                            style: item.separator ? 'border-top: var(--button-stroked-border);' : '',
                            onclick: () => { menuOpen.val = false; item.onclick(); },
                        }, item.label),
                    ),
                );
            },
        ),
    ];
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-dropdown-button--menu {
    border-radius: 8px;
    background: var(--dk-card-background);
    box-shadow: var(--portal-box-shadow);
    overflow: hidden;
}

.tg-dropdown-button--item {
    padding: 12px 16px;
    cursor: pointer;
    color: var(--primary-text-color);
}

.tg-dropdown-button--item:hover {
    background: var(--select-hover-background);
}
`);

export { DropdownButton };
