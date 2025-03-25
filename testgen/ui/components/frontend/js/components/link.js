/**
 * @typedef Properties
 * @type {object}
 * @property {string} href
 * @property {object} params
 * @property {string} label
 * @property {boolean} open_new
 * @property {boolean} underline
 * @property {string?} left_icon
 * @property {number?} left_icon_size
 * @property {string?} right_icon
 * @property {number?} right_icon_size
 * @property {number?} height
 * @property {number?} width
 * @property {string?} style
 * @property {string?} class
 * @property {string?} tooltip
 * @property {string?} tooltipPosition
 * @property {boolean?} disabled
 */
import { emitEvent, enforceElementWidth, getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const { a, div, i, span } = van.tags;

const Link = (/** @type Properties */ props) => {
    loadStylesheet('link', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(getValue(props.height) || 24);
        const width = getValue(props.width);
        if (width) {
            enforceElementWidth(window.frameElement, width);
        }
        if (props.tooltip) {
            window.frameElement.parentElement.setAttribute('data-tooltip', props.tooltip.val);
            window.frameElement.parentElement.setAttribute('data-tooltip-position', props.tooltipPosition.val);
        }
    }

    const href = getValue(props.href);
    const params = getValue(props.params) ?? {};
    const open_new = !!getValue(props.open_new);
    const showTooltip = van.state(false);

    return a(
        {
            class: `tg-link
                ${getValue(props.underline) ? 'tg-link--underline' : ''}
                ${getValue(props.disabled) ? 'disabled' : ''}
                ${getValue(props.class) ?? ''}`,
            style: props.style,
            href: `/${href}${getQueryFromParams(params)}`,
            target: open_new ? '_blank' : '',
            onclick: open_new ? null : (event) => {
                event.preventDefault();
                event.stopPropagation();
                emitEvent('LinkClicked', { href, params });
            },
            onmouseenter: props.tooltip ? (() => showTooltip.val = true) : undefined,
            onmouseleave: props.tooltip ? (() => showTooltip.val = false) : undefined,
        },
        () => getValue(props.tooltip) ? Tooltip({
            text: props.tooltip,
            show: showTooltip,
            position: props.tooltipPosition,
        }) : '',
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
        {class: `material-symbols-rounded tg-link--icon tg-link--icon-${position}`, style: `font-size: ${getValue(size) || 20}px;`},
        icon,
    );
};

function getQueryFromParams(/** @type object */ params) {
    const query = Object.entries(params).reduce((query, [ key, value ]) => {
        if (key && value) {
            return `${query}${query ? '&' : ''}${key}=${value}`;
        }
        return query;
    }, '');
    return query ? `?${query}` : '';
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

    .tg-link.disabled {
        pointer-events: none;
        cursor: not-allowed;
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
