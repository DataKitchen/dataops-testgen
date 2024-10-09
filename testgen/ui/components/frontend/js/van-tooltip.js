// Code modified from vanjs-ui
// https://www.npmjs.com/package/vanjs-ui
// https://cdn.jsdelivr.net/npm/vanjs-ui@0.10.0/dist/van-ui.nomodule.js

import van from './van.min.js';
const { div, span } = van.tags;

const toStyleStr = (style) => Object.entries(style).map(([k, v]) => `${k}: ${v};`).join("");

const Tooltip = ({ text, show, backgroundColor = '#333D', fontColor = 'white', fadeInSec = 0.3, tooltipClass = '', tooltipStyleOverrides = {}, triangleClass = '', triangleStyleOverrides = {}, }) => {
    const tooltipStylesStr = toStyleStr({
        width: 'max-content',
        'min-width': '100px',
        'max-width': '400px',
        visibility: 'hidden',
        'background-color': backgroundColor,
        color: fontColor,
        'text-align': 'center',
        padding: '5px',
        'border-radius': '5px',
        position: 'absolute',
        'z-index': 1,
        bottom: '125%',
        left: '50%',
        transform: 'translateX(-50%)',
        opacity: 0,
        transition: `opacity ${fadeInSec}s`,
        'font-size': '14px',
        'font-family': `'Roboto', 'Helvetica Neue', sans-serif`,
        'text-wrap': 'wrap',
        ...tooltipStyleOverrides,
    });
    const triangleStylesStr = toStyleStr({
        width: 0,
        height: 0,
        'margin-left': '-5px',
        'border-left': '5px solid transparent',
        'border-right': '5px solid transparent',
        'border-top': '5px solid #333',
        position: 'absolute',
        bottom: '-5px',
        left: '50%',
        ...triangleStyleOverrides,
    });
    const dom = span({ class: tooltipClass, style: tooltipStylesStr }, text, div({ class: triangleClass, style: triangleStylesStr }));
    van.derive(() => show.val ?
        (dom.style.opacity = '1', dom.style.visibility = 'visible') :
        (dom.style.opacity = '0', dom.style.visibility = 'hidden'));
    return dom;
};

export { Tooltip };
