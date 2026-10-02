// Code modified from vanjs-ui
// https://www.npmjs.com/package/vanjs-ui
// https://cdn.jsdelivr.net/npm/vanjs-ui@0.10.0/dist/van-ui.nomodule.js

/**
 * @typedef {'top-left' | 'top' | 'top-right' | 'right' | 'bottom-right' | 'bottom' | 'bottom-left' | 'left'} TooltipPosition
 *
 * @typedef Properties
 * @type {object}
 * @property {string} text
 * @property {boolean} show
 * @property {TooltipPosition?} position
 * @property {number} width
 * @property {string?} style
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span } = van.tags;
const defaultPosition = 'top';
const STREAMLIT_DIALOG_ZINDEX = 1000060;
const STREAMLIT_DIALOG_CLASS = 'stDialog';

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

const VIEWPORT_MARGIN = 8;

/**
 * How far to slide a tooltip horizontally so it stays inside the viewport, given where its left
 * edge would otherwise land. Never slides so far that the opposite edge goes out instead.
 */
const viewportShift = (leftEdge, width) => {
    const overflowRight = leftEdge + width - (window.innerWidth - VIEWPORT_MARGIN);
    if (overflowRight > 0) {
        return -Math.min(overflowRight, leftEdge - VIEWPORT_MARGIN);
    }
    const overflowLeft = VIEWPORT_MARGIN - leftEdge;
    return overflowLeft > 0 ? overflowLeft : 0;
};

const computeTooltipStyle = (rect, position, width = 0) => {
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const gap = 5;

    // `edge` is where the tooltip's left edge lands once `transform` has been applied, which is
    // what decides whether it clears the viewport.
    const variants = {
        'top':          { left: cx,         top: rect.top,    transform: `translateX(-50%) translateY(calc(-100% - ${gap}px))`, edge: cx - width / 2 },
        'top-left':     { left: cx + 20,    top: rect.top,    transform: `translateX(-100%) translateY(calc(-100% - ${gap}px))`, edge: cx + 20 - width },
        'top-right':    { left: cx - 20,    top: rect.top,    transform: `translateY(calc(-100% - ${gap}px))`, edge: cx - 20 },
        'bottom':       { left: cx,         top: rect.bottom, transform: `translateX(-50%) translateY(${gap}px)`, edge: cx - width / 2 },
        'bottom-left':  { left: cx + 20,    top: rect.bottom, transform: `translateX(-100%) translateY(${gap}px)`, edge: cx + 20 - width },
        'bottom-right': { left: cx - 20,    top: rect.bottom, transform: `translateY(${gap}px)`, edge: cx - 20 },
        'right':        { left: rect.right, top: cy,          transform: `translateX(${gap}px) translateY(-50%)`, edge: rect.right + gap },
        'left':         { left: rect.left,  top: cy,          transform: `translateX(calc(-100% - ${gap}px)) translateY(-50%)`, edge: rect.left - gap - width },
    };

    const { left, top, transform, edge } = variants[position] || variants['top'];
    const shift = width ? viewportShift(edge, width) : 0;
    const shifted = shift ? `${transform} translateX(${shift}px)` : transform;
    return `position: fixed; left: ${left}px; top: ${top}px; bottom: auto; right: auto; transform: ${shifted};`;
};

const withTooltip = (/** @type HTMLElement */ component, /** @type Properties */ tooltipProps) => {
    loadStylesheet('tooltip', stylesheet);

    const showTooltip = van.state(false);
    const positionStyle = van.state('');
    const zIndex = van.state(9999);

    const tooltipEl = span(
        {
            class: () => `tg-tooltip portal ${getValue(tooltipProps.position) || defaultPosition} ${showTooltip.val ? '' : 'hidden'}`,
            style: () => `opacity: ${showTooltip.val ? 1 : 0}; pointer-events: none; z-index: ${zIndex.val ?? 9999}; max-width: ${getValue(tooltipProps.width) || '400'}px; ${positionStyle.val}${getValue(tooltipProps.style) ?? ''}`,
        },
        tooltipProps.text,
        div({ class: 'tg-tooltip--triangle' }),
    );

    van.add(document.body, tooltipEl);

    requestAnimationFrame(() => {
        // The portal is on the body already, and the observer that cleans it up is set up below.
        // A component gone before this frame would leave it with neither.
        if (!component.isConnected) {
            tooltipEl.remove();
            return;
        }

        if (hasStreamlitDialogAncestor(component)) {
            zIndex.val = STREAMLIT_DIALOG_ZINDEX + 1;
        }

        const observer = new MutationObserver(() => {
            if (!component.isConnected) {
                tooltipEl.remove();
                observer.disconnect();
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    });

    // The tooltip is display:none until shown, so it has no width to measure. Uncover it just long
    // enough to read one, within the same frame, so nothing is painted in between.
    const measureWidth = () => {
        const wasHidden = tooltipEl.classList.contains('hidden');
        if (wasHidden) {
            tooltipEl.classList.remove('hidden');
        }
        const width = tooltipEl.offsetWidth;
        if (wasHidden) {
            tooltipEl.classList.add('hidden');
        }
        return width;
    };

    component.addEventListener('mouseenter', () => {
        if (getValue(tooltipProps.text)) {
            const position = getValue(tooltipProps.position) || defaultPosition;
            positionStyle.val = computeTooltipStyle(component.getBoundingClientRect(), position, measureWidth());
            showTooltip.val = true;
        }
    });
    component.addEventListener('mouseleave', () => {
        showTooltip.val = false;
    });

    return component;
};

function hasStreamlitDialogAncestor(el) {
    let node = el.parentElement;
    while (node && node !== document.body) {
        if (node.classList.contains(STREAMLIT_DIALOG_CLASS) || node.classList.contains('tg-dialog-overlay')) return true;
        node = node.parentElement;
    }
    return false;
}

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

.tg-tooltip.portal {
    position: fixed;
    z-index: 1000001;
    top: unset;
    bottom: unset;
    left: unset;
    right: unset;
    transform: unset;
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
