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
 * @property {string} edition
 * @property {string} current
 * @property {string} latest
 *
 * @typedef Menu
 * @type {object}
 * @property {Array.<MenuItem>} items
 *
 * @typedef Project
 * @type {object}
 * @property {string} code
 * @property {string} name
 *
 * @typedef Properties
 * @type {object}
 * @property {Menu} menu
 * @property {Project[]} projects
 * @property {string} current_project
 * @property {string} current_page
 * @property {string} username
 * @property {string} role
 * @property {string} logout_path
 * @property {Version} version
 * @property {string} support_email
 */
const van = window.top.van;
const { a, button, div, i, img, label, option, select, span } = van.tags;

const PROJECT_CODE_QUERY_PARAM = 'project_code';

const Sidebar = (/** @type {Properties} */ props) => {
    if (Sidebar.StreamlitInstance) {
        Sidebar.StreamlitInstance.setFrameHeight(1);
    }

    if (!window.testgen.loadedStylesheets.sidebar) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.sidebar = true;
    }

    const currentProject = van.derive(() => props.projects.val.find(({ code }) => code === props.current_project.val));

    return div(
        {class: 'menu'},
        div(
            div(
                { class: 'menu--project' },
                div({ class: 'caption' }, 'Project'),
                () => props.projects.val.length > 1
                    ? ProjectSelect(props.projects, currentProject)
                    : div(currentProject.val?.name ?? '...'),
            ),
            () => {
                const menuItems = props.menu?.val.items || [];
                return div(
                    {class: 'content'},
                    menuItems.map(item =>
                        item.items?.length > 0
                        ? MenuSection(item, props.current_page, currentProject.val?.code)
                        : MenuItem(item, props.current_page, currentProject.val?.code))
                );
            },
        ),
        div(
            div(
                { class: 'menu--user' },
                span({class: 'menu--username', title: props.username}, props.username),
                span({class: 'menu--role'}, props.role.val?.replace('_', ' ')),
            ),
            div(
                { class: 'menu--buttons' },
                button(
                    {
                        class: 'tg-button logout',
                        onclick: (event) => navigate(event, props.logout_path?.val),
                    },
                    i({class: 'material-symbols-rounded'}, 'logout'),
                    span('Logout'),
                ),
                props.support_email?.val ? a(
                    {
                        href: `mailto:${props.support_email?.val}
                            ?subject=${props.version.val?.edition}: Contact Us
                            &body=%0D%0D%0DVersion: ${props.version.val?.edition} ${props.version.val?.current}`,
                        target: '_blank',
                    },
                    'Contact Us',
                ) : null,
            ),
        ),
    );
};

const ProjectSelect = (/** @type Project[] */ projects, /** @type string */ currentProject) => {
    const opened = van.state(false);
    van.derive(() => {
        const clickHandler = () => opened.val = false;
        if (opened.val) {
            document.addEventListener('click', clickHandler);
        } else {
            document.removeEventListener('click', clickHandler);
        }
    });

    return div(
        {
            class: 'project-select',
            onclick: (/** @type Event */ event) => event.stopPropagation(),
        },
        div(
            {
                class: 'project-select--label',
                onclick: () => opened.val = !opened.val,
            },
            div(currentProject.val?.name ?? '...'),
            i({ class: 'material-symbols-rounded' }, 'arrow_drop_down'),
        ),
        () => opened.val
            ? div(
                { class: 'project-select--options-wrapper' },
                projects.val.map(({ name, code }) => a(
                    {
                        class: `project-select--option ${code === currentProject.val?.code ? 'selected' : ''}`,
                        href: `/?${PROJECT_CODE_QUERY_PARAM}=${code}`,
                        onclick: (event) => {
                            opened.val = false;
                            navigate(event, '', { [PROJECT_CODE_QUERY_PARAM]: code });
                        },
                    },
                    name,
                )),
            )
            : '',
    );
};

const MenuSection = (
    /** @type {MenuItem} */ item,
    /** @type {string} */ currentPage,
    /** @type {string} */ projectCode,
) => {
    return div(
        {class: 'menu--section'},
        div({class: 'menu--section--label'}, item.label),
        div(
            {class: 'menu--section--items'},
            ...item.items.map(child => MenuItem(child, currentPage, projectCode)),
        )
    );
}

const MenuItem = (
    /** @type {MenuItem} */ item,
    /** @type {string} */ currentPage,
    /** @type {string} */ projectCode,
) => {
    const classes = van.derive(() => {
        if (isCurrentPage(item.page, currentPage?.val)) {
            return 'menu--item active';
        }
        return 'menu--item';
    });

    return a(
        {
            class: classes,
            href: `/${item.page}?${PROJECT_CODE_QUERY_PARAM}=${projectCode}`,
            onclick: (event) => navigate(event, item.page, { [PROJECT_CODE_QUERY_PARAM]: projectCode }),
        },
        i({class: 'menu--item--icon material-symbols-rounded'}, item.icon),
        span({class: 'menu--item--label'}, item.label),
    );
};

function emitEvent(/** @type Object */ data) {
    if (Sidebar.StreamlitInstance) {
        Sidebar.StreamlitInstance.sendData({ ...data, _id: Math.random() }); // Identify the event so its handler is called once
    }
}

function navigate(
    /** @type object */ event,
    /** @type string */ path,
    /** @type object */ params = {},
) {
    // Needed to prevent page refresh
    // Returning false does not work because VanJS does not use inline handlers -> https://github.com/vanjs-org/van/discussions/246
    event.preventDefault();
    // Prevent Streamlit from reacting to event
    event.stopPropagation();

    emitEvent({ path, params });
}

function isCurrentPage(/** @type string */ itemPath, /** @type string */ currentPage) {
    const normalizedItemPath = normalizePath(itemPath);
    const normalizedCurrentPagePath = normalizePath(currentPage);
    const isTheSamePage = normalizedItemPath === normalizedCurrentPagePath;
    const isASubPage = normalizedCurrentPagePath.startsWith(`${normalizedItemPath}:`);

    return isTheSamePage || isASubPage;
}

function normalizePath(path) {
    return path || '';
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.menu {
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: calc(100% - 64px);
}

.menu .menu--project {
    padding: 0 20px;
    margin-bottom: 16px;
}

.project-select {
    position: relative;
}

.project-select--label {
    display: flex;
}

.project-select--options-wrapper {
    position: absolute;
    border-radius: 8px;
    background: var(--portal-background);
    box-shadow: var(--portal-box-shadow);
    min-width: 200px;
    min-height: 40px;
    max-height: 400px;
    overflow: auto;
    z-index: 99;
}

.project-select .project-select--option {
    display: flex;
    align-items: center;
    height: 40px;
    padding: 0px 16px;
    cursor: pointer;
    font-size: 14px;
    color: var(--primary-text-color);
}
.project-select .project-select--option:hover {
    background: var(--select-hover-background);
}

.project-select .project-select--option.selected {
    pointer-events: none;
    background: var(--select-hover-background);
    color: var(--primary-color);
}

.menu .menu--user {
    display: flex;
    flex-direction: column;
    padding: 16px;
}

.menu .menu--username {
    overflow-x: hidden;
    text-overflow: ellipsis;
    text-wrap: nowrap;
}

.menu .menu--role {
    text-transform: uppercase;
    font-size: 12px;
    color: var(--secondary-text-color);
}

.menu .content > .menu--section > .menu--section--label {
    padding: 8px 16px;
    font-size: 15px;
    color: var(--disabled-text-color);
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

.menu .menu--buttons {
    display: flex;
    justify-content: space-between;
    margin-bottom: 16px;
}

.menu--buttons a {
    padding: 8px 16px;
    font-size: 14px;
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
