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
    let pressHandler = null;
    let pressTarget = null;

    const close = () => { options.opened.val = false; };

    window.testgen.portals[id] = { domId: id, targetId: target, opened: options.opened, close };

    // Side-effect derive: manages close loop and outside-click handler.
    // Kept free of van.add / DOM creation to avoid corrupting VanJS dependency tracking.
    van.derive(() => {
        const isOpen = getValue(options.opened);

        if (!isOpen) {
            if (outsideClickHandler) {
                document.removeEventListener('click', outsideClickHandler, true);
                document.removeEventListener('mousedown', pressHandler, true);
                outsideClickHandler = null;
                pressHandler = null;
                pressTarget = null;
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
            // A drag that starts inside (e.g. selecting text in a search input) and ends outside fires
            // its click outside. A press that started inside is never an outside click.
            pressHandler = (event) => { pressTarget = event.target; };
            outsideClickHandler = (event) => {
                const anchor = document.getElementById(target);
                const portalEl = document.getElementById(id);
                const isInside = (el) => portalEl?.contains(el)
                    || anchor?.contains(el)
                    || isClickInsideChildPortal(el, id, portalEl);
                const startedInside = pressTarget && isInside(pressTarget);
                pressTarget = null;
                if (startedInside || isInside(event.target)) return;
                close();
            };
            document.addEventListener('mousedown', pressHandler, true);
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
                'data-testid': 'portal',
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
        if (node.classList.contains(STREAMLIT_DIALOG_CLASS) || node.classList.contains('tg-dialog-overlay')) return true;
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
