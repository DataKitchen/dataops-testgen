// Code modified from vanjs-ui
// https://www.npmjs.com/package/vanjs-ui
// https://cdn.jsdelivr.net/npm/vanjs-ui@0.10.0/dist/van-ui.nomodule.js

/**
 * @typedef Properties
 * @type {object}
 * @property {string} text
 * @property {boolean} show
 * @property {('top-left' | 'top' | 'top-right' | 'right' | 'bottom-right' | 'bottom' | 'bottom-left' | 'left')?} position
 * @property {number} width
 * @property {string?} style
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span } = van.tags;
const defaultPosition = 'top';

const Tooltip = (/** @type Properties */ props) => {
    loadStylesheet('tooltip', stylesheet);

    return span(
        {
            class: () => `tg-tooltip ${getValue(props.position) || defaultPosition} ${getValue(props.show) ? '' : 'hidden'}`,
            style: () => `opacity: ${getValue(props.show) ? 1 : 0}; max-width: ${getValue(props.width) || '400'}px; ${getValue(props.style) ?? ''}`,
        },
        props.text,
        div({ class: 'tg-tooltip--triangle' }),
    );
};

const withTooltip = (/** @type HTMLElement */ component, /** @type Properties */ tooltipProps) => {
    const showTooltip = van.state(false);
    const tooltip = Tooltip({ ...tooltipProps, show: showTooltip });

    component.onmouseenter = () => showTooltip.val = true;
    component.onmouseleave = () => showTooltip.val = false;
    component.appendChild(tooltip);

    return component;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tooltip {
    width: max-content;
    position: absolute;
    z-index: 1;
    border-radius: 4px;
    background-color: var(--tooltip-color);
    padding: 4px 8px;
    color: var(--tooltip-text-color);
    font-size: 13px;
    font-family: 'Roboto', 'Helvetica Neue', sans-serif;
    text-align: center;
    text-wrap: wrap;
    transition: opacity 0.3s;
}

.tg-tooltip--triangle {
    width: 0;
    height: 0;
    position: absolute;
    border: solid transparent;
}

.tg-tooltip.top-left {
    right: 50%;
    bottom: 125%;
    transform: translateX(20px);
}
.top-left .tg-tooltip--triangle {
    bottom: -5px;
    right: 20px;
    margin-right: -5px;
    border-width: 5px 5px 0;
    border-top-color: var(--tooltip-color);
}

.tg-tooltip.top {
    left: 50%;
    bottom: 125%;
    transform: translateX(-50%);
}
.top .tg-tooltip--triangle {
    bottom: -5px;
    left: 50%;
    margin-left: -5px;
    border-width: 5px 5px 0;
    border-top-color: var(--tooltip-color);
}

.tg-tooltip.top-right {
    left: 50%;
    bottom: 125%;
    transform: translateX(-20px);
}
.top-right .tg-tooltip--triangle {
    bottom: -5px;
    left: 20px;
    margin-left: -5px;
    border-width: 5px 5px 0;
    border-top-color: var(--tooltip-color);
}

.tg-tooltip.right {
    left: 125%;
}
.right .tg-tooltip--triangle {
    top: 50%;
    left: -5px;
    margin-top: -5px;
    border-width: 5px 5px 5px 0;
    border-right-color: var(--tooltip-color);
}

.tg-tooltip.bottom-right {
    left: 50%;
    top: 125%;
    transform: translateX(-20px);
}
.bottom-right .tg-tooltip--triangle {
    top: -5px;
    left: 20px;
    margin-left: -5px;
    border-width: 0 5px 5px;
    border-bottom-color: var(--tooltip-color);
}

.tg-tooltip.bottom {
    top: 125%;
    left: 50%;
    transform: translateX(-50%);
}
.bottom .tg-tooltip--triangle {
    top: -5px;
    left: 50%;
    margin-left: -5px;
    border-width: 0 5px 5px;
    border-bottom-color: var(--tooltip-color);
}

.tg-tooltip.bottom-left {
    right: 50%;
    top: 125%;
    transform: translateX(20px);
}
.bottom-left .tg-tooltip--triangle {
    top: -5px;
    right: 20px;
    margin-right: -5px;
    border-width: 0 5px 5px;
    border-bottom-color: var(--tooltip-color);
}

.tg-tooltip.left {
    right: 125%;
}
.left .tg-tooltip--triangle {
    top: 50%;
    right: -5px;
    margin-top: -5px;
    border-width: 5px 0 5px 5px;
    border-left-color: var(--tooltip-color);
}
`);

export { Tooltip, withTooltip };
