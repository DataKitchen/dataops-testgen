/**
 * Container for any floating elements anchored to another element.
 * The portal element is appended to document.body so position: absolute
 * is document-relative, avoiding issues with positioned ancestors.
 *
 * NOTE: Ensure options is an object and turn individual properties into van.state
 * if dynamic updates are needed.
 *
 * @typedef Options
 * @type {object}
 * @property {string} target
 * @property {boolean} opened
 * @property {'left' | 'right'} align
 * @property {('top' | 'bottom')?} position
 * @property {(string|undefined)} style
 * @property {(string|undefined)} class
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';

const STREAMLIT_DIALOG_ZINDEX = 1000060;
const STREAMLIT_DIALOG_CLASS = 'stDialog';

const Portal = (/** @type Options */ options, ...args) => {
    const { target, align = 'left', position = 'bottom' } = getValue(options);
    const id = `${target}-portal`;
    let portalEl = null;
    let outsideClickHandler = null;

    const close = () => { options.opened.val = false; };

    window.testgen.portals[id] = { domId: id, targetId: target, opened: options.opened, close };

    van.derive(() => {
        const isOpen = getValue(options.opened);

        if (!isOpen) {
            portalEl?.remove();
            portalEl = null;
            if (outsideClickHandler) {
                document.removeEventListener('click', outsideClickHandler, true);
                outsideClickHandler = null;
            }
            return;
        }

        // Close other open portals before opening this one
        for (const p of Object.values(window.testgen.portals)) {
            if (p.domId !== id && getValue(p.opened)) {
                p.close();
            }
        }

        const anchor = document.getElementById(target);
        if (!anchor) return;

        const fixed = hasFixedAncestor(anchor);
        const fromDialog = hasStreamlitDialogAncestor(anchor);
        const zIndex = fromDialog ? (STREAMLIT_DIALOG_ZINDEX + 1) : 1001;
        const coords = position === 'bottom'
            ? calculateBottomPosition(anchor, align, fixed)
            : calculateTopPosition(anchor, align, fixed);

        if (!portalEl) {
            portalEl = document.createElement('div');
            document.body.appendChild(portalEl);
            van.add(portalEl, ...args);

            outsideClickHandler = (event) => {
                const anchor = document.getElementById(target);
                if (!portalEl?.contains(event.target) && !anchor?.contains(event.target)) {
                    close();
                }
            };
            document.addEventListener('click', outsideClickHandler, true);
        }

        portalEl.id = id;
        portalEl.className = getValue(options.class) ?? '';
        portalEl.style.cssText = `position: ${fixed ? 'fixed' : 'absolute'}; z-index: ${zIndex}; ${coords} ${getValue(options.style) ?? ''}`;
    });

    return '';
};

function hasFixedAncestor(el) {
    let node = el.parentElement;
    while (node && node !== document.body) {
        if (getComputedStyle(node).position === 'fixed') return true;
        node = node.parentElement;
    }
    return false;
}

function hasStreamlitDialogAncestor(el) {
    let node = el.parentElement;
    while (node && node !== document.body) {
        if (node.classList.contains(STREAMLIT_DIALOG_CLASS)) return true;
        node = node.parentElement;
    }
    return false;
}

function calculateBottomPosition(anchor, align, fixed = false) {
    const r = anchor.getBoundingClientRect();
    const top  = fixed ? r.bottom               : r.bottom + window.scrollY;
    const left = fixed ? r.left                 : r.left   + window.scrollX;
    const right = window.innerWidth - r.right;
    const constrain = fixed ? `max-height: calc(100vh - ${r.bottom}px - 8px); overflow-y: auto;` : '';
    return `min-width: ${r.width}px; top: ${top}px; ${constrain} ${align === 'left' ? `left: ${left}px;` : `right: ${right}px;`}`;
}

function calculateTopPosition(anchor, align, fixed = false) {
    const r = anchor.getBoundingClientRect();
    const bottom = fixed ? window.innerHeight - r.top : window.innerHeight - r.top + window.scrollY;
    const left   = fixed ? r.left                     : r.left + window.scrollX;
    const right  = window.innerWidth - r.right;
    const constrain = fixed ? `max-height: calc(${r.top}px - 8px); overflow-y: auto;` : '';
    return `min-width: ${r.width}px; bottom: ${bottom}px; ${constrain} ${align === 'left' ? `left: ${left}px;` : `right: ${right}px;`}`;
}

export { Portal };
