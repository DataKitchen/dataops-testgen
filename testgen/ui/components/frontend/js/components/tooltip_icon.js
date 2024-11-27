/**
 * @typedef Properties
 * @type {object}
 * @property {string} icon
 * @property {number?} iconSize
 * @property {string} tooltip
 * @property {('top-left' | 'top' | 'top-right' | 'right' | 'bottom-right' | 'bottom' | 'bottom-left' | 'left')?} tooltipPosition
 * @property {string} classes
 */
import { getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';
import { Tooltip } from './tooltip.js';

const { i } = van.tags;
const defaultIconSize = 20;

const TooltipIcon = (/** @type Properties */ props) => {
    loadStylesheet('tooltipIcon', stylesheet);
    const showTooltip = van.state(false);

    return i(
        {
            class: () => `material-symbols-rounded tg-tooltip-icon text-secondary ${getValue(props.classes)}`,
            style: () => `font-size: ${getValue(props.iconSize) || defaultIconSize}px;`,
            onmouseenter: () => showTooltip.val = true,
            onmouseleave: () => showTooltip.val = false,
        },
        props.icon,
        Tooltip({
            text: props.tooltip,
            show: showTooltip,
            position: props.tooltipPosition,
        }),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tooltip-icon {
    position: relative;
    cursor: default;
}
`);

export { TooltipIcon };
