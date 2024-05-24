/**
 * @typedef Properties
 * @type {object}
 * @property {boolean} initialized
 * @property {string} current_page_code
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const Location = (/** @type Properties */ props) => {
    Streamlit.setFrameHeight('0');

    van.derive(() => {
        syncHashToCurrentPage(van.val(props.current_page_code));
    });

    if (!van.val(props.initialized)) {
        Streamlit.sendData(extractLocation());
    }

    window.top.addEventListener("hashchange", function(event) {
        if (event.newURL.includes('login')) {
            return;
        }

        const urlChanged = event.oldURL !== event.newURL;
        if (urlChanged) {
            Streamlit.sendData(extractLocation());
        }
    });

    return '';
};


function extractLocation() {
    const hash = decodeURI(window.top.location.hash).replace('#', '');
    const parts = hash.split('?')
    const page = parts[0] ? `${parts[0]}` : undefined;
    const args = (parts[1] || '').split('&').filter(pair => !!pair).reduce((allArgs, pair) => {
        const pairParts = pair.split('=');
        allArgs[pairParts[0].trim()] = pairParts[1].trim() || '';
        return allArgs;
    }, {});

    return { page: page, args: args };
}

function isHashSynchronized(/** @type string */ hash, /** @type string */ currentPageCode) {
    return btoa(decodeURI(hash || '').replace('#', '')) === currentPageCode;
}

function syncHashToCurrentPage(/** @type string */ currentPageCode) {
    if (!currentPageCode) {
        return;
    }

    const path = atob(currentPageCode);
    window.parent.postMessage({ type: 'TestgenNavigationRequest', path: path }, '*');
}

export { Location };
