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
 * @property {(string|undefined)} style
 * @property {(string|undefined)} class
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';

const { div } = van.tags;

const Portal = (/** @type Options */ options, ...args) => {
    const { target, targetRelative, align = 'left' } = getValue(options);
    const id = `${target}-portal`;

    window.testgen.portals[id] = { domId: id, targetId: target, opened: options.opened };

    return () => {
        if (!getValue(options.opened)) {
            return '';
        }

        const anchor = document.getElementById(target);
        const anchorRect = anchor.getBoundingClientRect();
        const top = (targetRelative ? 0 : anchorRect.top) + anchorRect.height;
        const left = targetRelative ? 0 : anchorRect.left;
        const right = targetRelative ? 0 : (window.innerWidth - anchorRect.right);
        const minWidth = anchorRect.width;

        return div(
            {
                id,
                class: getValue(options.class) ?? '',
                style: `position: absolute;
                    z-index: 99;
                    min-width: ${minWidth}px;
                    top: ${top}px;
                    ${align === 'left' ? `left: ${left}px;` : `right: ${right}px;`}
                    ${getValue(options.style)}`,
            },
            ...args,
        );
    };
};

export { Portal };
