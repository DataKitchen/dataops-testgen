/**
 * Container for any floating elements anchored to another element.
 *
 * NOTE: Ensure options is an object and turn individual properties into van.state
 * if dynamic updates are needed.
 * 
 * @typedef Options
 * @type {object}
 * @property {string} target
 * @property {boolean?} targetRelative
 * @property {boolean} opened
 * @property {'left' | 'right'} align
 * @property {('top' | 'bottom')?} position
 * @property {(string|undefined)} style
 * @property {(string|undefined)} class
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';

const { div } = van.tags;

const Portal = (/** @type Options */ options, ...args) => {
    const { target, targetRelative, align = 'left', position = 'bottom' } = getValue(options);
    const id = `${target}-portal`;

    window.testgen.portals[id] = { domId: id, targetId: target, opened: options.opened };

    return () => {
        if (!getValue(options.opened)) {
            return '';
        }

        const anchor = document.getElementById(target);
        return div(
            {
                id,
                class: getValue(options.class) ?? '',
                style: `position: absolute;
                    z-index: 99;
                    ${position === 'bottom' ? calculateBottomPosition(anchor, align, targetRelative) : calculateTopPosition(anchor, align, targetRelative)}
                    ${getValue(options.style)}`,
            },
            ...args,
        );
    };
};

function calculateTopPosition(anchor, align, targetRelative) {
    const anchorRect = anchor.getBoundingClientRect();
    const bottom = (targetRelative ? anchorRect.height : anchorRect.top);
    const left = targetRelative ? 0 : anchorRect.left;
    const right = targetRelative ? 0 : (window.innerWidth - anchorRect.right);

    return `min-width: ${anchorRect.width}px; bottom: ${bottom}px; ${align === 'left' ? `left: ${left}px;` : `right: ${right}px;`}`;
}

function calculateBottomPosition(anchor, align, targetRelative) {
    const anchorRect = anchor.getBoundingClientRect();
    const top = (targetRelative ? 0 : anchorRect.top) + anchorRect.height;
    const left = targetRelative ? 0 : anchorRect.left;
    const right = targetRelative ? 0 : (window.innerWidth - anchorRect.right);

    return `min-width: ${anchorRect.width}px; top: ${top}px; ${align === 'left' ? `left: ${left}px;` : `right: ${right}px;`}`;
}

export { Portal };
