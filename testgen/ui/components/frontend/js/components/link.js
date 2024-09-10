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
 * @property {string?} style
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const { a, div, i, span } = van.tags;

const Link = (/** @type Properties */ props) => {
    Streamlit.setFrameHeight(props.height?.val || 24);

    if (!window.testgen.loadedStylesheets.link) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.link = true;
    }

    return a(
        {
            class: `tg-link ${props.underline.val ? 'tg-link--underline' : ''}`,
            style: props.style,
            onclick: () => navigate(props.href.val, props.params.val),
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
        {class: `material-symbols-rounded tg-link--icon tg-link--icon-${position}`, style: `font-size: ${size.val}px;`},
        icon,
    );
};

function navigate(href, params) {
    Streamlit.sendData({ href, params });
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
