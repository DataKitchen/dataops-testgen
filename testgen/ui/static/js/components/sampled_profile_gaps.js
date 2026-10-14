/**
 * Help icon whose tooltip lists the test types and hygiene issues a sampled table cannot support,
 * one per line.
 *
 * @typedef Properties
 * @type {object}
 * @property {string[]?} testTypes
 * @property {string[]?} hygieneIssues
 */
import van from '../van.min.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';

const { div } = van.tags;

const SampledProfileGapsHelp = (/** @type Properties */ props) => {
    const section = (title, names) => names?.length
        ? div(
            { class: 'flex-column' },
            div({ class: 'text-bold' }, title),
            ...names.map(name => div(name)),
        )
        : '';

    return withTooltip(
        Icon({ size: 16, classes: 'text-disabled' }, 'help'),
        {
            text: div(
                { class: 'flex-column fx-gap-2' },
                div('They need measures that a sample cannot give exactly.'),
                section('Test types', props.testTypes),
                section('Hygiene issues', props.hygieneIssues),
            ),
            position: 'top',
            width: 320,
            style: 'text-align: left;',
        },
    );
};

export { SampledProfileGapsHelp };
