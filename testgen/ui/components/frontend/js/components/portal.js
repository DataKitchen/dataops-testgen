/**
 * Container for any floating elements anchored to another element.
 * 
 * NOTE: Ensure options is an object and turn individual properties into van.state
 * if dynamic updates are needed.
 * 
 * @typedef Options
 * @type {object}
 * @property {string} target
 * @property {boolean} opened
 * @property {(string|undefined)} style
 * @property {(string|undefined)} class
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';

const { div } = van.tags;

const Portal = (/** @type Options */ options, ...args) => {
    const { target } = getValue(options);
    const id = `${target}-portal`;

    window.testgen.portals[id] = { domId: id, targetId: target, opened: options.opened };

    return () => {
        if (!getValue(options.opened)) {
            return '';
        }

        const anchor = document.getElementById(target);
        const anchorRect = anchor.getBoundingClientRect();
        const top = anchorRect.top + anchorRect.height;
        const left = anchorRect.left;
        const minWidth = anchorRect.width;

        return div(
            {
                id,
                class: getValue(options.class) ?? '',
                style: `position: absolute; z-index: 99; min-width: ${minWidth}px; top: ${top}px; left: ${left}px; ${getValue(options.style)}`,
            },
            ...args,
        );
    };
};

export { Portal };