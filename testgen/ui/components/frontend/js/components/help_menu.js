/**
 * @typedef Version
 * @type {object}
 * @property {string} edition
 * @property {string} current
 * @property {string} latest
 * 
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} page_help
 * @property {string} support_email
 * @property {Version} version
 * @property {Permissions} permissions
*/
import van from '../van.min.js';
import { emitEvent, getRandomId, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Streamlit } from '../streamlit.js';
import { Icon } from './icon.js';

const { a, div, span } = van.tags;

const baseHelpUrl = 'https://docs.datakitchen.io/articles/#!dataops-testgen-help/';
const releaseNotesTopic = 'testgen-release-notes';
const upgradeTopic = 'upgrade-testgen';

const slackUrl = 'https://data-observability-slack.datakitchen.io/join';
const trainingUrl = 'https://info.datakitchen.io/data-quality-training-and-certifications';

const HelpMenu = (/** @type Properties */ props) => {
    loadStylesheet('help-menu', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const domId = `help-menu-${getRandomId()}`;
    const version = getValue(props.version) ?? {};
    
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);    

    return div(
        { id: domId },
        div(
            { class: 'flex-column pt-3' },
            getValue(props.help_topic) 
                ? HelpLink(`${baseHelpUrl}${getValue(props.help_topic)}`, 'Help for this Page', 'description')
                : null,
            HelpLink(baseHelpUrl, 'TestGen Help', 'help'),
            HelpLink(trainingUrl, 'Training Portal', 'school'),
            getValue(props.permissions)?.can_edit
                ? div(
                    { class: 'help-item', onclick: () => emitEvent('AppLogsClicked') },
                    Icon({ classes: 'help-item-icon' }, 'browse_activity'),
                    'Application Logs',
                )
                : null,
            span({ class: 'help-divider' }),
            HelpLink(slackUrl, 'Slack Community', 'group'),
            getValue(props.support_email)
                ? HelpLink(
                    `mailto:${getValue(props.support_email)}
                        ?subject=${version.edition}: Contact Support
                        &body=%0D%0D%0DVersion: ${version.edition} ${version.current}`,
                    'Contact Support',
                    'email',
                )
                : null,
            span({ class: 'help-divider' }),
            version.current || version.latest
                ? div(
                    { class: 'help-version' },
                    version.current
                        ? HelpLink(`${baseHelpUrl}${releaseNotesTopic}`, `${version.edition} ${version.current}`, null, null)
                        : null,
                    version.latest !== version.current 
                        ? HelpLink(
                            `${baseHelpUrl}${upgradeTopic}`,
                            `New version available! ${version.latest}`,
                            null,
                            'latest',
                        )
                        : null,
                )
                : null,
        ),
    );
}

const HelpLink = (
    /** @type string */ url,
    /** @type string */ label,
    /** @type string? */ icon,
    /** @type string */ classes = 'help-item',
) => {
    return a(
        {
            class: classes,
            href: url,
            target: '_blank',
            onclick: () => emitEvent('ExternalLinkClicked'),
        },
        icon ? Icon({ classes: 'help-item-icon' }, icon) : null,
        label,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.help-item {
    padding: 12px 24px;
    color: var(--primary-text-color);
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    transition: 0.3s;
}

.help-item:hover {
    background-color: var(--select-hover-background);
    color: var(--primary-color);
}

.help-item-icon {
    color: var(--primary-text-color);
    transition: 0.3s;
}

.help-item:hover .help-item-icon {
    color: var(--primary-color);
}

.help-divider {
    height: 1px;
    background-color: var(--border-color);
    margin: 0 16px;
}

.help-version {
    padding: 16px 16px 8px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
}

.help-version > a {
    color: var(--secondary-text-color);
    text-decoration: none;
}

.help-version > a.latest {
    color: var(--red);
}
`);

export { HelpMenu };
