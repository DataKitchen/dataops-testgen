/**
 * @typedef Properties
 * @type {object}
 * @property {(string)} type
 * @property {(string|null)} color
 * @property {(string|null)} label
 * @property {(string|null)} icon
 * @property {(string|null)} tooltip
 * @property {(string|null)} tooltipPosition
 * @property {(Function|null)} onclick
 * @property {(bool)} disabled
 * @property {string?} style
 */
import { emitEvent, enforceElementWidth, getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Tooltip } from './tooltip.js';

const { button, i, span } = van.tags;
const BUTTON_TYPE = {
    BASIC: 'basic',
    FLAT: 'flat',
    ICON: 'icon',
    STROKED: 'stroked',
};
const BUTTON_COLOR = {
    BASIC: 'basic',
    PRIMARY: 'primary',
};


const Button = (/** @type Properties */ props) => {
    loadStylesheet('button', stylesheet);

    const buttonType = getValue(props.type);
    const width = getValue(props.width);
    const isIconOnly = buttonType === BUTTON_TYPE.ICON || (getValue(props.icon) && !getValue(props.label));
    
    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(40);
        if (isIconOnly) { // Force a 40px width for the parent iframe & handle window resizing
            enforceElementWidth(window.frameElement, 40);
        }

        if (width) {
            enforceElementWidth(window.frameElement, width);
        }
        if (props.tooltip) {
            window.frameElement.parentElement.setAttribute('data-tooltip', props.tooltip.val);
            window.frameElement.parentElement.setAttribute('data-tooltip-position', props.tooltipPosition.val);
        }
    }

    const onClickHandler = props.onclick || (() => emitEvent('ButtonClicked'));
    const showTooltip = van.state(false);

    return button(
        {
            class: `tg-button tg-${buttonType}-button tg-${getValue(props.color) ?? 'basic'}-button ${buttonType !== 'icon' && isIconOnly ? 'tg-icon-button' : ''}`,
            style: () => `width: ${isIconOnly ? '' : (width ?? '100%')}; ${getValue(props.style)}`,
            onclick: onClickHandler,
            disabled: props.disabled,
            onmouseenter: props.tooltip ? (() => showTooltip.val = true) : undefined,
            onmouseleave: props.tooltip ? (() => showTooltip.val = false) : undefined,
        },
        props.tooltip ? Tooltip({
            text: props.tooltip,
            show: showTooltip,
            position: props.tooltipPosition,
        }) : undefined,
        span({class: 'tg-button-focus-state-indicator'}, ''),
        props.icon ? i({class: 'material-symbols-rounded'}, props.icon) : undefined,
        !isIconOnly ? span(props.label) : undefined,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
button.tg-button {
    height: 40px;

    position: relative;

    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;

    outline: 0;
    border: unset;
    border-radius: 4px;
    padding: 8px 11px;

    cursor: pointer;

    font-size: 14px;
}

button.tg-button .tg-button-focus-state-indicator {
    border-radius: inherit;
    overflow: hidden;
}

button.tg-button .tg-button-focus-state-indicator::before {
    content: "";
    opacity: 0;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    position: absolute;
    pointer-events: none;
    border-radius: inherit;
}

button.tg-button.tg-stroked-button {
    border: var(--button-stroked-border);
}

button.tg-button.tg-icon-button {
    width: 40px;
}

button.tg-button:has(span) {
    padding: 8px 16px;
}

button.tg-button:not(.tg-icon-button):has(span):has(i) {
    padding-left: 12px;
}

button.tg-button[disabled] {
    color: var(--disabled-text-color);
    cursor: not-allowed;
}

button.tg-button > i {
    font-size: 18px;
}

button.tg-button > i:has(+ span) {
    margin-right: 8px;
}

button.tg-button:hover:not([disabled]) .tg-button-focus-state-indicator::before {
    opacity: var(--button-hover-state-opacity);
}


/* Basic button colors */
button.tg-button.tg-basic-button {
    color: var(--button-basic-text-color);
    background: var(--button-basic-background);
}

button.tg-button.tg-basic-button .tg-button-focus-state-indicator::before {
    background: var(--button-basic-hover-state-background);
}

button.tg-button.tg-basic-button.tg-flat-button {
    color: var(--button-basic-flat-text-color);
    background: var(--button-basic-flat-background);
}

button.tg-button.tg-basic-button.tg-stroked-button {
    color: var(--button-basic-stroked-text-color);
    background: var(--button-basic-stroked-background);
}
/* ... */

/* Primary button colors */
button.tg-button.tg-primary-button {
    color: var(--button-primary-text-color);
    background: var(--button-primary-background);
}

button.tg-button.tg-primary-button .tg-button-focus-state-indicator::before {
    background: var(--button-primary-hover-state-background);
}

button.tg-button.tg-primary-button.tg-flat-button {
    color: var(--button-primary-flat-text-color);
    background: var(--button-primary-flat-background);
}

button.tg-button.tg-primary-button.tg-stroked-button {
    color: var(--button-primary-stroked-text-color);
    background: var(--button-primary-stroked-background);
}
/* ... */
`);

export { Button };
