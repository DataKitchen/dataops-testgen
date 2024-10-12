import van from './static/js/van.min.js';

window.van = van;

window.addEventListener('load', function() {
    removeElements([ 'header[data-testid="stHeader"]' ]);
});

window.addEventListener('message', async function(event) {
    if (event.data.type === 'TestgenCopyToClipboard') {
        await copyToClipboard(event.data.text || '');
    }

    if (event.data.type === 'TestgenLogout') {
        window.testgen.states = {};
        deleteCookie(event.data.cookie);
    }
});

function removeElements(selectors) {
    for (const selector of selectors) {
        const element = window.top.document.querySelector(selector);
        if (element) {
            element.remove();
        }
    }
}

async function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text || '');
    } else {
        const textArea = document.createElement('textarea');
        textArea.value = text;

        textArea.style.opacity = 0;
        textArea.style.pointerEvents = 'none';
        textArea.style.position = 'absolute';

        document.body.prepend(textArea);
        textArea.select();

        try {
            document.execCommand('copy')
        } finally {
            textArea.remove();
        }
    }
}

function deleteCookie(name) {
    const d = new Date();
    d.setTime(d.getTime() - (1 * 24 * 60 * 60 * 1000));

    document.cookie = `${name}=-;expires=${d.toUTCString()};path=/`;
}

window.testgen = {
    states: {},
    components: {},
    loadedStylesheets: {},
};
