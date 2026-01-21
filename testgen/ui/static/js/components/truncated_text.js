/**
 * @import { TooltipPosition } from './tooltip.js';
 *
 * @typedef TruncatedTextOptions
 * @type {object}
 * @property {number} max
 * @property {string?} class
 * @property {TooltipPosition?} tooltipPosition
 */
import van from '../van.min.js';
import { withTooltip } from './tooltip.js';
import { caseInsensitiveSort } from '../display_utils.js';

const { div, span, i } = van.tags;

/**
 * @param {TruncatedTextOptions} options
 * @param {string[]} children
 */
const TruncatedText = ({ max, ...options }, ...children) => {
    const sortedChildren = [...children.sort((a, b) => a.length - b.length)];
    const tooltipText = children.sort(caseInsensitiveSort).join(', ');

    return div(
        { class: () => `${options.class ?? ''}`, style: 'position: relative;' },
        span(sortedChildren.slice(0, max).join(', ')),
        sortedChildren.length > max
            ? withTooltip(
                i({class: 'text-caption'}, ` + ${sortedChildren.length - max} more`),
                {
                    text: tooltipText,
                    position: options.tooltipPosition,
                }
            )
            : '',
    );
};

export { TruncatedText };
