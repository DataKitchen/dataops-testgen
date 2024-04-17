/**
 * @typedef MenuItem
 * @type {object}
 * @property {(string|null)} id
 * @property {(string|null)} icon
 * @property {string} label
 * @property {(string|null)} page
 * @property {(Array.<MenuItem>|null)} items
 * 
 * @typedef Version
 * @type {object}
 * @property {string} current
 * @property {string} latest
 * @property {string} schema
 * 
 * @typedef Menu
 * @type {object}
 * @property {Array.<MenuItem>} items
 * @property {Version} version
 * 
 * @typedef Project
 * @type {object}
 * @property {string} code
 * @property {string} name
 * 
 * @typedef Properties
 * @type {object}
 * @property {Menu} menu
 * @property {string} username
 * @property {string} current_page
 * @property {string} current_project
 * @property {string} auth_cookie_name
 */
const van = window.top.van;
const { a, button, div, i, img, label, option, select, span } = van.tags;

const Sidebar = (/** @type {Properties} */ props) => {
    if (Sidebar.StreamlitInstance) {
        Sidebar.StreamlitInstance.setFrameHeight(1);
    }

    if (!window.testgen.loadedStylesheets.sidebar) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.sidebar = true;
    }

    return div(
        {class: 'menu'},
        a({class: 'logo', href: `/#overview`, onclick: () => navigate('overview')}, img({ src: logo })),
        () => {
            const menuItems = van.val(props.menu).items;
            return div(
                {class: 'content'},
                menuItems.map(item =>
                    item.items?.length > 0
                    ? MenuSection(item, props.current_page)
                    : MenuItem(item, props.current_page))
            );
        },
        button(
            { class: `tg-button logout`, onclick: () => Sidebar.onLogout(van.val(props.auth_cookie_name)) },
            i({class: 'material-symbols-rounded'}, 'logout'),
            span('Logout'),
        ),
        span({class: 'menu--username'}, props.username),
        () => Version(van.val(props.menu).version),
    );
};

const MenuSection = (/** @type {MenuItem} */ item, /** @type {string} */ currentPage) => {
    return div(
        {class: 'menu--section'},
        div({class: 'menu--section--label'}, item.label),
        div(
            {class: 'menu--section--items'},
            ...item.items.map(child => MenuItem(child, currentPage)),
        )
    );
}

const MenuItem = (/** @type {MenuItem} */ item, /** @type {string} */ currentPage) => {
    const classes = van.derive(() => {
        if (isCurrentPage(item.page, van.val(currentPage))) {
            return 'menu--item active';
        }
        return 'menu--item';
    });

    return a(
        {class: classes, href: `/#${item.page}`, onclick: () => navigate(item.page)},
        i({class: 'menu--item--icon material-symbols-rounded'}, item.icon),
        span({class: 'menu--item--label'}, item.label),
    );
};

const Version = (/** @type {Version} */ version) => {
    const expanded = van.state(false);

    const icon = van.derive(() => expanded.val ? 'expand_less' : 'expand_more');
    const classes = van.derive(() => expanded.val ? ' version expanded' : 'version');

    return div(
        {class: classes, onclick: () => { expanded.val = !expanded.val; }},
        VersionRow(
            'version',
            version.current,
            i({class: 'material-symbols-rounded version--dropdown-icon'}, icon),
        ),
        div(
            {class: 'version--details'},
            VersionRow('latest version', version.latest),
            VersionRow('schema revision', version.schema),
        ),
    );
};

const VersionRow = (/** @type string */ label, /** @type string */ version, iconEl = undefined) => {
    return div(
        {class: 'version--row'},
        span({class: 'version--row--label'}, `${label}:`),
        span({class: 'version--row--value'}, version),
        iconEl,
    );
};

function navigate(/** @type string */ path) {
    window.parent.postMessage({ type: 'TestgenNavigationRequest', path: path }, '*');
    return false;
}

function isCurrentPage(itemPath, currentPage) {
    const normalizedItemPath = normalizePath(itemPath);
    const normalizedCurrentPagePath = normalizePath(currentPage);
    const isTheSamePage = normalizedItemPath === normalizedCurrentPagePath;
    const isASubPage = normalizedCurrentPagePath.includes(normalizedItemPath);

    return isTheSamePage || isASubPage;
}

function normalizePath(path) {
    if (!path) {
        return '';
    }

    return path.split('/').filter(p => p.length > 0).join('/');
}

const b64LogoString = `PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz4NCjwhLS0gR2VuZXJhdG9yOiBBZG9iZSBJbGx1c3RyYXRv
ciAyNC4xLjIsIFNWRyBFeHBvcnQgUGx1Zy1JbiAuIFNWRyBWZXJzaW9uOiA2LjAwIEJ1aWxkIDApICAtLT4NCjxzdmcgdmVyc2lvbj0iMS4xIiBpZD0iTGF
5ZXJfMSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeD0iMH
B4IiB5PSIwcHgiDQoJIHZpZXdCb3g9IjAgMCA2MDIuMiAxMTcuNyIgc3R5bGU9ImVuYWJsZS1iYWNrZ3JvdW5kOm5ldyAwIDAgNjAyLjIgMTE3Ljc7IiB4b
Ww6c3BhY2U9InByZXNlcnZlIj4NCjxzdHlsZSB0eXBlPSJ0ZXh0L2NzcyI+DQoJLnN0MHtmaWxsOiNBQUQwNDY7fQ0KCS5zdDF7ZmlsbDojMDZBMDRBO30N
Cjwvc3R5bGU+DQo8cGF0aCBkPSJNMzcuMywxMDcuNmMwLjYsMCwxLjEsMCwxLjYtMC4xYy0yLjIsMC00LjUsMC4xLTYuOSwwLjFIMzcuM3oiLz4NCjxwYXR
oIGQ9Ik0zNy4zLDkuOUgzMmMyLjQsMCw0LjcsMCw2LjksMC4xQzM4LjMsOS45LDM3LjgsOS45LDM3LjMsOS45eiIvPg0KPHBhdGggY2xhc3M9InN0MCIgZD
0iTTg1LjYsNTguM2MwLTEuNy0wLjEtMy4zLTAuMy00LjljLTAuNi03LjgtMi41LTE0LjgtNS45LTIwLjhDNzYsMjYuNSw3MS41LDIxLjcsNjUuOSwxOA0KC
WMtMS4yLTAuOC0yLjMtMS42LTMuNi0yLjJjLTIuNy0xLjQtNS41LTIuNS04LjUtMy40TDExLjcsNTguN2w0Mi4yLDQ2LjRjMi45LTAuOSw1LjgtMiw4LjUt
My40YzAuOS0wLjUsMS44LTEuMSwyLjctMS43DQoJYzYtMy44LDEwLjktOC44LDE0LjQtMTUuMmMzLjYtNi40LDUuNS0xMy45LDUuOS0yMi40YzAuMS0wLjk
sMC4xLTEuOCwwLjEtMi43YzAtMC40LDAuMS0wLjcsMC4xLTEuMWMwLTAuMSwwLTAuMSwwLTAuMg0KCUM4NS41LDU4LjUsODUuNiw1OC40LDg1LjYsNTguM3
oiLz4NCjxwYXRoIGNsYXNzPSJzdDEiIGQ9Ik01My44LDEyLjNjLTQuNi0xLjQtOS42LTIuMi0xNC45LTIuNGMtMi4yLDAtNC41LTAuMS02LjktMC4xSDE2L
jVjLTIuNywwLTQuOCwyLjItNC44LDQuOHYyOS44djE0LjNMNTMuOCwxMi4zDQoJQzUzLjgsMTIuMyw1My44LDEyLjMsNTMuOCwxMi4zeiIvPg0KPHBhdGgg
Y2xhc3M9InN0MSIgZD0iTTExLjcsNzN2MjkuOGMwLDIuNywyLjIsNC44LDQuOCw0LjhIMzJjMi40LDAsNC43LDAsNi45LTAuMWM1LjMtMC4xLDEwLjMtMSw
xNC45LTIuNGMwLDAsMCwwLDAsMEwxMS43LDU4LjdWNzMNCgl6Ii8+DQo8cGF0aCBjbGFzcz0ic3QwIiBkPSJNOTQuNSw5LjlINjkuM2MwLjMsMC4yLDAuNS
wwLjQsMC44LDAuN2M2LjQsNC40LDExLjcsMTAsMTUuNiwxNy4xYzQsNy4yLDYuMywxNS41LDcsMjQuOA0KCWMwLjIsMS45LDAuMywzLjksMC4zLDUuOWMwL
DAuMSwwLDAuMiwwLDAuM2MwLDAuMSwwLDAuMSwwLDAuMmMwLDAuNC0wLjEsMC44LTAuMSwxLjNjMCwxLjEtMC4xLDIuMS0wLjIsMy4yDQoJYy0wLjUsMTAu
MS0yLjgsMTktNy4xLDI2LjdjLTQuMSw3LjQtOS43LDEzLjItMTYuNSwxNy42YzAsMCwwLDAuMSwwLDAuMWgyNS40YzIuNywwLDQuOC0yLjIsNC44LTQuOHY
tODgNCglDOTkuNCwxMi4xLDk3LjIsOS45LDk0LjUsOS45eiIvPg0KPHBhdGggY2xhc3M9InN0MSIgZD0iTTEzMiwyOGgyNC4xYzE3LjYsMCwyNy44LDEzLj
QsMjcuOCwzMC45YzAsMTcuNC0xMC4zLDMwLjYtMjcuOCwzMC42SDEzMlYyOHogTTE1Ni4xLDc5LjcNCgljMTEuMiwwLDE2LjktOS41LDE2LjktMjAuOWMwL
TExLjUtNS43LTIxLjEtMTYuOS0yMS4xaC0xMy4ydjQySDE1Ni4xeiIvPg0KPHBhdGggY2xhc3M9InN0MSIgZD0iTTIzMS45LDQ3Ljh2NDEuN2gtMTAuNHYt
NS42Yy0yLjksNC41LTguNyw2LjUtMTMuOCw2LjVjLTExLDAtMjAuNS04LjUtMjAuNS0yMS44YzAtMTMuNCw5LjUtMjEuNywyMC40LTIxLjcNCgljNS4zLDA
sMTEuMSwyLjEsMTMuOSw2LjR2LTUuNUgyMzEuOXogTTIyMS40LDY4LjVjMC03LjMtNi4xLTEyLTEyLTEyYy02LjQsMC0xMS43LDUtMTEuNywxMmMwLDcsNS
4zLDEyLjEsMTEuNywxMi4xDQoJQzIxNS43LDgwLjYsMjIxLjQsNzUuOCwyMjEuNCw2OC41eiIvPg0KPHBhdGggY2xhc3M9InN0MSIgZD0iTTI2Myw1Ni4xa
C04Ljh2MzMuNGgtMTAuNFY1Ni4xaC03LjV2LTguM2g3LjVWMzIuNWgxMC40djE1LjRoOC44VjU2LjF6Ii8+DQo8cGF0aCBjbGFzcz0ic3QxIiBkPSJNMzA5
LDQ3Ljh2NDEuN2gtMTAuNHYtNS42Yy0yLjksNC41LTguNyw2LjUtMTMuOCw2LjVjLTExLDAtMjAuNS04LjUtMjAuNS0yMS44YzAtMTMuNCw5LjUtMjEuNyw
yMC40LTIxLjcNCgljNS4zLDAsMTEuMSwyLjEsMTMuOSw2LjR2LTUuNUgzMDl6IE0yOTguNCw2OC41YzAtNy4zLTYuMS0xMi0xMi0xMmMtNi40LDAtMTEuNy
w1LTExLjcsMTJjMCw3LDUuMywxMi4xLDExLjcsMTIuMQ0KCUMyOTIuNyw4MC42LDI5OC40LDc1LjgsMjk4LjQsNjguNXoiLz4NCjxwYXRoIGNsYXNzPSJzd
DEiIGQ9Ik0zNTQuNiw4OS41bC0yMS4yLTIzLjR2MjMuNGgtMTAuOFYyOGgxMC44djIzLjNMMzUwLjcsMjhoMTMuNWwtMjMuNSwzMC42bDI4LjYsMzAuOUgz
NTQuNnoiLz4NCjxwYXRoIGNsYXNzPSJzdDEiIGQ9Ik0zNzMuNywzMy4xYzAtMy43LDMuMS02LjMsNi44LTYuM2MzLjcsMCw2LjcsMi43LDYuNyw2LjNjMCw
zLjYtMi45LDYuMy02LjcsNi4zDQoJQzM3Ni45LDM5LjQsMzczLjcsMzYuNiwzNzMuNywzMy4xeiBNMzc1LjMsNDcuOGgxMC40djQxLjdoLTEwLjRWNDcuOH
oiLz4NCjxwYXRoIGNsYXNzPSJzdDEiIGQ9Ik00MTcuNCw1Ni4xaC04Ljh2MzMuNGgtMTAuNFY1Ni4xaC03LjV2LTguM2g3LjVWMzIuNWgxMC40djE1LjRoO
C44VjU2LjF6Ii8+DQo8cGF0aCBjbGFzcz0ic3QxIiBkPSJNNDE3LjYsNjguNmMwLTEzLjIsMTAuNi0yMS43LDIyLjctMjEuN2M3LjIsMCwxMy4xLDMuMSwx
Nyw4bC03LjQsNS44Yy0yLjEtMi42LTUuNy00LjItOS40LTQuMg0KCWMtNy4yLDAtMTIuNCw1LTEyLjQsMTJjMCw3LDUuMiwxMiwxMi40LDEyYzMuNywwLDc
uMi0xLjYsOS40LTQuMmw3LjQsNS44Yy0zLjgsNC44LTkuNyw4LTE3LDhDNDI4LjMsOTAuMyw0MTcuNiw4MS44LDQxNy42LDY4LjZ6Ig0KCS8+DQo8cGF0aC
BjbGFzcz0ic3QxIiBkPSJNNTAwLjcsNjYuMXYyMy40aC0xMC40VjY3LjFjMC02LjYtNC0xMC04LjctMTBjLTQuNywwLTEwLjYsMi42LTEwLjYsMTAuNnYyM
S44aC0xMC40di02NGgxMC40djI4LjYNCgljMi4xLTUsOC43LTcuMiwxMi45LTcuMkM0OTQuOCw0Ni45LDUwMC43LDU0LDUwMC43LDY2LjF6Ii8+DQo8cGF0
aCBjbGFzcz0ic3QxIiBkPSJNNTQ3LjUsNzIuM2gtMzIuMmMxLjIsNS44LDUuNiw4LjcsMTEuOCw4LjdjNC42LDAsOC44LTEuOCwxMS4zLTUuMmw2LjksNS4
zYy0zLjgsNi4xLTExLjIsOS4zLTE4LjcsOS4zDQoJYy0xMi41LDAtMjItOC43LTIyLTIxLjhjMC0xMy4zLDEwLTIxLjcsMjEuOS0yMS43YzEyLDAsMjEuMy
w4LjMsMjEuMywyMS4zQzU0Ny44LDY5LjQsNTQ3LjcsNzAuNyw1NDcuNSw3Mi4zeiBNNTM3LjQsNjUNCgljLTAuNi01LjctNS05LTEwLjgtOWMtNS42LDAtM
TAuMSwyLjctMTEuMyw5SDUzNy40eiIvPg0KPHBhdGggY2xhc3M9InN0MSIgZD0iTTU5MS45LDY2LjF2MjMuNGgtMTAuNFY2Ny4xYzAtNi42LTQtMTAtOC43
LTEwYy00LjcsMC0xMC42LDIuNi0xMC42LDEwLjZ2MjEuOGgtMTAuNFY0Ny44aDEwLjR2Ni42DQoJYzIuMS01LjIsOC43LTcuNSwxMi45LTcuNUM1ODUuOSw
0Ni45LDU5MS45LDU0LDU5MS45LDY2LjF6Ii8+DQo8L3N2Zz4NCg==`
const logo = `data:image/svg+xml;base64,${b64LogoString}`;

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.menu {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--sidebar-background-color);
}

.menu .logo {
    margin: 24px 16px 16px;
}

.menu > .menu--username {
    position: absolute;

    left: 0;
    bottom: 0;

    padding-left: 16px;
    padding-bottom: 8px;

    max-width: 35%;
    overflow-x: hidden;
    text-overflow: ellipsis;
    text-wrap: nowrap;

    color: var(--secondary-text-color);
}

.menu > .menu--username:before {
    content: 'User: ';
}

.menu > .content > .menu--section > .menu--section--label {
    padding: 16px;
    font-weight: 500;
    color: var(--secondary-text-color);
}

.menu .menu--item {
    height: 40px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    color: var(--secondary-text-color);
    border-left: 4px solid transparent;
    font-weight: 500;
    text-decoration: unset;
}

.menu .menu--item.active {
    color: var(--primary-color);
    background: var(--sidebar-active-item-color);
    border-left-color: var(--sidebar-active-item-border-color);
}

.menu .menu--item > .menu--item--icon {
    font-size: 20px;
    line-height: 20px;
}

.menu .menu--item > .menu--item--label {
    margin-left: 16px;
}

.menu .menu--item:hover {
    cursor: pointer;
    background: var(--sidebar-item-hover-color);
}

.menu .version {
    color: var(--secondary-text-color);
    display: flex;
    flex-direction: column;
    padding: 8px 16px;
    cursor: pointer;
}

.menu .version .version--dropdown-icon {
    font-size: 19px;
}

.menu .version .version--row {
    display: flex;
    align-items: center;
    justify-content: flex-end;
}

.menu .version .version--row .version--row--label {
    font-weight: 500;
    margin-right: 4px;
}

.menu .version .version--details {
    display: none;
    flex-direction: column;
}

.menu .version .version--details {
    display: none;
    margin-top: 4px;
}

.menu .version.expanded .version--details {
    display: block;
}

.version--row + .version--row {
    margin-top: 4px;
}

.menu > :nth-child(1 of button) {
    margin-top: auto !important;
}

.menu > button {
    margin: 16px;
    color: var(--secondary-text-color) !important;
}

.menu > button.logout {
    margin-top: 8px;
}

.menu > button.users {
    margin-bottom: 0px;
}

/* Intentionally duplicate from button.js */
button.tg-button {
    position: relative;
    overflow: hidden;

    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;

    outline: 0;
    border: unset;
    background: transparent;
    border-radius: 4px;
    padding: 8px 16px;

    color: var(--primary-text-color);
    cursor: pointer;

    font-size: 14px;

    transition: background 400ms;
}

button.tg-button:hover {
    background: rgba(0, 0, 0, 0.04);
}

button.tg-button > i {
    font-size: 18px;
    margin-right: 8px;
}
/* ... */
`);

window.testgen.components.Sidebar = Sidebar;
