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

const { div } = van.tags;

const STREAMLIT_DIALOG_ZINDEX = 1000060;
const STREAMLIT_DIALOG_CLASS = 'stDialog';

const Portal = (/** @type Options */ options, ...args) => {
    const { target, align = 'left', position = 'bottom' } = getValue(options);
    const id = `${target}-portal`;
    let outsideClickHandler = null;

    const close = () => { options.opened.val = false; };

    window.testgen.portals[id] = { domId: id, targetId: target, opened: options.opened, close };

    // Side-effect derive: manages close loop and outside-click handler.
    // Kept free of van.add / DOM creation to avoid corrupting VanJS dependency tracking.
    van.derive(() => {
        const isOpen = getValue(options.opened);

        if (!isOpen) {
            if (outsideClickHandler) {
                document.removeEventListener('click', outsideClickHandler, true);
                outsideClickHandler = null;
            }
            return;
        }

        const anchor = document.getElementById(target);
        if (!anchor) return;

        // Close other open portals — skip parent portals that contain our anchor.
        const toClose = [];
        for (const p of Object.values(window.testgen.portals)) {
            if (p.domId !== id && p.opened?.rawVal) {
                const otherEl = document.getElementById(p.domId);
                if (otherEl?.contains(anchor)) continue;
                toClose.push(p);
            }
        }
        if (toClose.length) {
            queueMicrotask(() => toClose.forEach(p => { p.opened.val = false; }));
        }

        if (!outsideClickHandler) {
            outsideClickHandler = (event) => {
                const anchor = document.getElementById(target);
                const portalEl = document.getElementById(id);
                if (portalEl?.contains(event.target)) return;
                if (anchor?.contains(event.target)) return;
                if (isClickInsideChildPortal(event.target, id, portalEl)) return;
                close();
            };
            document.addEventListener('click', outsideClickHandler, true);
        }
    });

    // DOM rendering: a VanJS binding on document.body.
    // VanJS manages the element lifecycle natively — no manual createElement/remove.
    van.add(document.body, () => {
        if (!getValue(options.opened)) {
            return '';
        }

        const anchor = document.getElementById(target);
        if (!anchor) return '';

        const fixed = hasFixedAncestor(anchor);
        const fromDialog = hasStreamlitDialogAncestor(anchor);
        const parentPortalEl = getParentPortalElement(anchor, id);
        const zIndex = parentPortalEl
            ? (parseInt(parentPortalEl.style.zIndex) || 1001) + 1
            : fromDialog ? (STREAMLIT_DIALOG_ZINDEX + 1) : 1001;
        const coords = position === 'bottom'
            ? calculateBottomPosition(anchor, align, fixed)
            : calculateTopPosition(anchor, align, fixed);

        return div(
            {
                id,
                class: getValue(options.class) ?? '',
                style: `position: ${fixed ? 'fixed' : 'absolute'}; z-index: ${zIndex}; ${coords} ${getValue(options.style) ?? ''}`,
            },
            ...args,
        );
    });

    return '';
};

function getParentPortalElement(anchor, selfId) {
    for (const p of Object.values(window.testgen.portals)) {
        if (p.domId === selfId) continue;
        const el = document.getElementById(p.domId);
        if (el?.contains(anchor)) return el;
    }
    return null;
}

function isClickInsideChildPortal(target, selfId, selfPortalEl) {
    for (const p of Object.values(window.testgen.portals)) {
        if (p.domId === selfId) continue;
        const childEl = document.getElementById(p.domId);
        if (childEl?.contains(target)) {
            const childAnchor = document.getElementById(p.targetId);
            if (selfPortalEl?.contains(childAnchor)) return true;
        }
    }
    return false;
}

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
