import van from './van.min.js';

window.van = van;

window.addEventListener('message', async function(event) {
    if (event.data.type === 'TestgenCopyToClipboard') {
        await copyToClipboard(event.data.text || '');
    }

    if (event.data.type === 'TestgenLogout') {
        window.testgen.states = {};
        deleteCookie(event.data.cookie);
    }
});

document.addEventListener('click', (event) => {
    const openedPortals = (Object.values(window.testgen.portals) ?? []).filter(portal => portal.opened.val);
    if (Object.keys(openedPortals).length <= 0) {
        return;
    }

    const targetParents = getParents(event.target);
    for (const portal of openedPortals) {
        const targetEl = document.getElementById(portal.targetId);
        const portalEl = document.getElementById(portal.domId);

        if (event?.target?.id !== portal.targetId && event?.target?.id !== portal.domId && !targetParents.includes(targetEl) && !targetParents.includes(portalEl)) {
            portal.opened.val = false;
        }
    }
});

function getParents(/** @type HTMLElement*/ element) {
    const parents = [];

    let currentParent = element.parentElement; 
    do {
        if (currentParent !== null) {
            parents.push(currentParent);
            currentParent = currentParent.parentElement;
        }
    }
    while (currentParent !== null && currentParent.tagName !== 'iframe');

    return parents;
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
    portals: {},
    changeLocation: url => window.location.href = url, 
};
