/**
 * @typedef Properties
 * @type {object}
 * @property {string} href
 * @property {object} params
 * @property {string} label
 * @property {boolean} underline
 * @property {string?} left_icon
 * @property {number?} left_icon_size
 * @property {string?} right_icon
 * @property {number?} right_icon_size
 * @property {number?} height
 * @property {number?} width
 * @property {string?} style
 */
import { enforceElementWidth, loadStylesheet } from '../utils.js';
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const { a, div, i, span } = van.tags;

const Link = (/** @type Properties */ props) => {
    loadStylesheet('link', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(props.height?.val || 24);
        if (props.width?.val) {
            enforceElementWidth(window.frameElement, props.width.val);
        }
    }

    return a(
        {
            class: `tg-link ${props.underline?.val ? 'tg-link--underline' : ''}`,
            style: props.style,
            onclick: () => emitEvent(props.href.val, props.params.val),
        },
        div(
            {class: 'tg-link--wrapper'},
            props.left_icon ? LinkIcon(props.left_icon, props.left_icon_size, 'left') : undefined,
            span({class: 'tg-link--text'}, props.label),
            props.right_icon ? LinkIcon(props.right_icon, props.right_icon_size, 'right') : undefined,
        ),
    );
};

const LinkIcon = (
    /** @type string */icon,
    /** @type number */size,
    /** @type string */position,
) => {
    return i(
        {class: `material-symbols-rounded tg-link--icon tg-link--icon-${position}`, style: `font-size: ${size?.val || 20}px;`},
        icon,
    );
};

function emitEvent(href, params) {
    Streamlit.sendData({ event: 'LinkClicked', href, params });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
    .tg-link {
        width: fit-content;
        display: flex;
        flex-direction: column;
        text-decoration: unset !important;
        color: var(--link-color);
        cursor: pointer;
    }

    .tg-link .tg-link--wrapper {
        display: flex;
        align-items: center;
    }

    .tg-link.tg-link--underline::after {
        content: "";
        height: 0;
        width: 0;
        border-top: 1px solid #1976d2;  /* pseudo elements do not inherit variables */
        transition: width 50ms linear;
    }

    .tg-link.tg-link--underline:hover::after {
        width: 100%;
    }
`);

export { Link };
