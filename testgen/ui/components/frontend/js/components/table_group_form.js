/**
 * @import { Connection } from './connection_form.js';
 * 
 * @typedef TableGroup
 * @type {object}
 * @property {string?} id
 * @property {string?} connection_id
 * @property {string?} table_groups_name
 * @property {string?} profiling_include_mask
 * @property {string?} profiling_exclude_mask
 * @property {string?} profiling_table_set
 * @property {string?} table_group_schema
 * @property {string?} profile_id_column_mask
 * @property {string?} profile_sk_column_mask
 * @property {number?} profiling_delay_days
 * @property {boolean?} profile_flag_cdes
 * @property {boolean?} include_in_dashboard
 * @property {boolean?} add_scorecard_definition
 * @property {boolean?} profile_use_sampling
 * @property {number?} profile_sample_percent
 * @property {number?} profile_sample_min_count
 * @property {string?} description
 * @property {string?} data_source
 * @property {string?} source_system
 * @property {string?} source_process
 * @property {string?} data_location
 * @property {string?} business_domain
 * @property {string?} stakeholder_group
 * @property {string?} transform_level
 * @property {string?} data_product
 * 
 * @typedef FormState
 * @type {object}
 * @property {boolean} dirty
 * @property {boolean} valid
 * 
 * @typedef Properties
 * @type {object}
 * @property {TableGroup} tableGroup
 * @property {Connection[]} connections
 * @property {boolean?} showConnectionSelector
 * @property {boolean?} disableConnectionSelector
 * @property {boolean?} disableSchemaField
 * @property {(tg: TableGroup, state: FormState) => void} onChange
 */
import van from '../van.min.js';
import { getValue, isEqual, loadStylesheet } from '../utils.js';
import { Input } from './input.js';
import { Checkbox } from './checkbox.js';
import { ExpansionPanel } from './expansion_panel.js';
import { required } from '../form_validators.js';
import { Select } from './select.js';
import { Caption } from './caption.js';
import { Textarea } from './textarea.js';

const { div } = van.tags;

const normalizeTableSet = (value) => {
    return value?.split(/[,\n]/)
        .map(part => part.trim())
        .filter(part => part)
        .join(', ');
}

/**
 * 
 * @param {Properties} props 
 * @returns 
 */
const TableGroupForm = (props) => {
    loadStylesheet('table-group-form', stylesheet);

    const tableGroup = getValue(props.tableGroup);
    const tableGroupConnectionId = van.state(tableGroup.connection_id);
    const tableGroupsName = van.state(tableGroup.table_groups_name);
    const profilingIncludeMask = van.state(tableGroup.profiling_include_mask ?? '%');
    const profilingExcludeMask = van.state(tableGroup.profiling_exclude_mask ?? 'tmp%');
    const profilingTableSet = van.state(normalizeTableSet(tableGroup.profiling_table_set));
    const tableGroupSchema = van.state(tableGroup.table_group_schema);
    const profileIdColumnMask = van.state(tableGroup.profile_id_column_mask ?? '%_id');
    const profileSkColumnMask = van.state(tableGroup.profile_sk_column_mask ?? '%_sk');
    const profilingDelayDays = van.state(tableGroup.profiling_delay_days ?? 0);
    const profileFlagCdes = van.state(tableGroup.profile_flag_cdes ?? true);
    const includeInDashboard = van.state(tableGroup.include_in_dashboard ?? true);
    const addScorecardDefinition = van.state(tableGroup.add_scorecard_definition ?? true);
    const profileUseSampling = van.state(tableGroup.profile_use_sampling ?? false);
    const profileSamplePercent = van.state(tableGroup.profile_sample_percent ?? 30);
    const profileSampleMinCount = van.state(tableGroup.profile_sample_min_count ?? 15000);
    const description = van.state(tableGroup.description);
    const dataSource = van.state(tableGroup.data_source);
    const sourceSystem = van.state(tableGroup.source_system);
    const sourceProcess = van.state(tableGroup.source_process);
    const dataLocation = van.state(tableGroup.data_location);
    const businessDomain = van.state(tableGroup.business_domain);
    const stakeholderGroup = van.state(tableGroup.stakeholder_group);
    const transformLevel = van.state(tableGroup.transform_level);
    const dataProduct = van.state(tableGroup.data_product);

    const connectionOptions = van.derive(() => {
        const connections = getValue(props.connections) ?? [];
        return connections.map(c => ({
            label: c.connection_name,
            value: c.connection_id,
            icon: c.flavor.icon,
        }));
    });
    const showConnectionSelector = getValue(props.showConnectionSelector) ?? false;
    const disableSchemaField = van.derive(() => getValue(props.disableSchemaField) ?? false)

    const updatedTableGroup = van.derive(() => {
        return {
            id: tableGroup.id,
            connection_id: tableGroupConnectionId.val,
            table_groups_name: tableGroupsName.val,
            profiling_include_mask: profilingIncludeMask.val,
            profiling_exclude_mask: profilingExcludeMask.val,
            profiling_table_set: normalizeTableSet(profilingTableSet.val),
            table_group_schema: tableGroupSchema.val,
            profile_id_column_mask: profileIdColumnMask.val,
            profile_sk_column_mask: profileSkColumnMask.val,
            profiling_delay_days: profilingDelayDays.val,
            profile_flag_cdes: profileFlagCdes.val,
            include_in_dashboard: includeInDashboard.val,
            add_scorecard_definition: addScorecardDefinition.val,
            profile_use_sampling: profileUseSampling.val,
            profile_sample_percent: profileSamplePercent.val,
            profile_sample_min_count: profileSampleMinCount.val,
            description: description.val,
            data_source: dataSource.val,
            source_system: sourceSystem.val,
            source_process: sourceProcess.val,
            data_location: dataLocation.val,
            business_domain: businessDomain.val,
            stakeholder_group: stakeholderGroup.val,
            transform_level: transformLevel.val,
            data_product: dataProduct.val,
        };
    });
    const dirty = van.derive(() => !isEqual(updatedTableGroup.val, tableGroup));
    const validityPerField = van.state({});
    if (showConnectionSelector) {
        validityPerField.val.connection_id = !!tableGroupConnectionId.val;
    }

    van.derive(() => {
        const fieldsValidity = validityPerField.val;
        const isValid = Object.keys(fieldsValidity).length > 0 &&
            Object.values(fieldsValidity).every(v => v);
        props.onChange?.(updatedTableGroup.val, { dirty: dirty.val, valid: isValid });
    });

    const setFieldValidity = (field, validity) => {
        validityPerField.val = {...validityPerField.rawVal, [field]: validity};
    }

    return div(
        { class: 'flex-column fx-gap-3' },
        showConnectionSelector
            ? Select({
                name: 'connection_id',
                label: 'Connection',
                value: tableGroupConnectionId.rawVal,
                options: connectionOptions,
                height: 38,
                disabled: props.disableConnectionSelector,
                onChange: (value) => {
                    tableGroupConnectionId.val = value;
                    setFieldValidity('connection_id', !!value);
                },
            })
            : undefined,
        MainForm(
            { disableSchemaField, setValidity: setFieldValidity },
            tableGroupsName,
            tableGroupSchema,
        ),
        CriteriaForm(
            { setValidity: setFieldValidity },
            profilingIncludeMask,
            profilingExcludeMask,
            profilingTableSet,
            profileIdColumnMask,
            profileSkColumnMask,
        ),
        SettingsForm(
            { editMode: !!tableGroup.id, setValidity: setFieldValidity },
            profilingDelayDays,
            profileFlagCdes,
            includeInDashboard,
            addScorecardDefinition,
        ),
        SamplingForm(
            { setValidity: setFieldValidity },
            profileUseSampling,
            profileSamplePercent,
            profileSampleMinCount,
        ),
        TaggingForm(
            { setValidity: setFieldValidity },
            description,
            dataSource,
            sourceSystem,
            sourceProcess,
            dataLocation,
            businessDomain,
            stakeholderGroup,
            transformLevel,
            dataProduct,
        ),
    );
};

const MainForm = (
    options,
    tableGroupsName,
    tableGroupSchema,
) => {
    return div(
        { class: 'flex-row fx-gap-3 fx-flex-wrap' },
        Input({
            name: 'table_groups_name',
            label: 'Name',
            value: tableGroupsName,
            height: 38,
            class: 'tg-column-flex',
            help: 'Unique name to describe the table group',
            helpPlacement: 'bottom-right',
            onChange: (value, state) => {
                tableGroupsName.val = value;
                options.setValidity?.('table_groups_name', state.valid);
            },
            validators: [ required ],
        }),
        Input({
            name: 'table_group_schema',
            label: 'Schema',
            value: tableGroupSchema,
            height: 38,
            class: 'tg-column-flex',
            help: 'Database schema containing the tables for the Table Group',
            helpPlacement: 'bottom-left',
            disabled: options.disableSchemaField,
            onChange: (value, state) => {
                tableGroupSchema.val = value;
                options.setValidity?.('table_group_schema', state.valid);
            },
            validators: [ required ],
        }),
    );
};

const CriteriaForm = (
    options,
    profilingIncludeMask,
    profilingExcludeMask,
    profilingTableSet,
    profileIdColumnMask,
    profileSkColumnMask,
) => {
    return div(
        { class: 'flex-column fx-gap-3 border border-radius-1 p-3 mt-1', style: 'position: relative;' },
        Caption({content: 'Criteria', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start' },
            div(
                { class: 'tg-column-flex flex-column fx-gap-3', },
                Input({
                    name: 'profiling_include_mask',
                    label: 'Tables to Include Mask',
                    value: profilingIncludeMask,
                    height: 38,
                    help: 'SQL filter supported by your database\'s LIKE operator for table names to include',
                    onChange: (value, state) => {
                        profilingIncludeMask.val = value;
                        options.setValidity?.('profiling_include_mask', state.valid);
                    },
                }),
                Input({
                    name: 'profiling_exclude_mask',
                    label: 'Tables to Exclude Mask',
                    value: profilingExcludeMask,
                    height: 38,
                    help: 'SQL filter supported by your database\'s LIKE operator for table names to exclude',
                    onChange: (value, state) => {
                        profilingExcludeMask.val = value;
                        options.setValidity?.('profiling_exclude_mask', state.valid);
                    },
                }),
            ),
            Textarea({
                name: 'profiling_table_set',
                label: 'Explicit Table List',
                value: profilingTableSet,
                height: 108,
                class: 'tg-column-flex',
                help: 'List of specific table names to include, separated by commas or newlines',
                onChange: (value) => profilingTableSet.val = value,
            }),
        ),
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap' },
            Input({
                name: 'profile_id_column_mask',
                label: 'Profiling ID Column Mask',
                value: profileIdColumnMask,
                height: 38,
                class: 'tg-column-flex',
                help: 'SQL filter supported by your database\'s LIKE operator representing ID columns',
                onChange: (value, state) => {
                    profileIdColumnMask.val = value;
                    options.setValidity?.('profile_id_column_mask', state.valid);
                },
            }),
            Input({
                name: 'profile_sk_column_mask',
                label: 'Profiling Surrogate Key Column Mask',
                value: profileSkColumnMask,
                height: 38,
                class: 'tg-column-flex',
                help: 'SQL filter supported by your database\'s LIKE operator representing surrogate key columns',
                onChange: (value, state) => {
                    profileSkColumnMask.val = value
                    options.setValidity?.('profile_sk_column_mask', state.valid);
                },
            }),
        ),
    );
};

const SettingsForm = (
    options,
    profilingDelayDays,
    profileFlagCdes,
    includeInDashboard,
    addScorecardDefinition,
) => {
    return div(
        { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start border border-radius-1 p-3 mt-1', style: 'position: relative;' },
        Caption({content: 'Settings', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),        
        div(
            { class: 'tg-column-flex flex-column fx-gap-3' },
            Checkbox({
                name: 'profile_flag_cdes',
                label: 'Detect critical data elements (CDE) during profiling',
                checked: profileFlagCdes,
                onChange: (value) => profileFlagCdes.val = value,
            }),
            Checkbox({
                name: 'include_in_dashboard',
                label: 'Include table group in Project Dashboard',
                checked: includeInDashboard,
                onChange: (value) => includeInDashboard.val = value,
            }),
            () => !options.editMode
                ? Checkbox({
                    name: 'add_scorecard_definition',
                    label: 'Add scorecard for table group',
                    help: 'Add a new scorecard to the Quality Dashboard upon creation of this table group',
                    checked: addScorecardDefinition,
                    onChange: (value) => addScorecardDefinition.val = value,
                })
                : null,
        ),
        Input({
            name: 'profiling_delay_days',
            type: 'number',
            label: 'Min Profiling Age (in days)',
            value: profilingDelayDays,
            height: 38,
            class: 'tg-column-flex',
            help: 'Number of days to wait before new profiling will be available to generate tests',
            onChange: (value, state) => {
                profilingDelayDays.val = value;
                options.setValidity?.('profiling_delay_days', state.valid);
            },
        }),
    );
};

const SamplingForm = (
    options,
    profileUseSampling,
    profileSamplePercent,
    profileSampleMinCount,
) => {
    return ExpansionPanel(
        { title: 'Sampling Parameters', testId: 'sampling-panel' },
        div(
            { class: 'flex-column fx-gap-3' },
            Checkbox({
                name: 'profile_use_sampling',
                label: 'Use profile sampling',
                help: 'When checked, profiling will be based on a sample of records instead of the full table',
                checked: profileUseSampling,
                onChange: (value) => profileUseSampling.val = value,
            }),
            div(
                { class: 'flex-row fx-gap-3' },
                Input({
                    name: 'profile_sample_percent',
                    class: 'fx-flex',
                    type: 'number',
                    label: 'Sample percent',
                    value: profileSamplePercent,
                    height: 38,
                    help: 'Percent of records to include in the sample, unless the calculated count falls below the specified minimum',
                    onChange: (value, state) => {
                        profileSamplePercent.val = value;
                        options.setValidity?.('profile_sample_percent', state.valid);
                    },
                }),
                Input({
                    name: 'profile_sample_min_count',
                    class: 'fx-flex',
                    type: 'number',
                    label: 'Min Sample Record Count',
                    value: profileSampleMinCount,
                    height: 38,
                    help: 'Minimum number of records to be included in any sample (if available)',
                    onChange: (value, state) => {
                        profileSampleMinCount.val = value;
                        options.setValidity?.('profile_sample_min_count', state.valid);
                    },
                }),
            ),
        ),
    );
};

const TaggingForm = (
    options,
    description,
    dataSource,
    sourceSystem,
    sourceProcess,
    dataLocation,
    businessDomain,
    stakeholderGroup,
    transformLevel,
    dataProduct,
) => {
    return ExpansionPanel(
        { title: 'Table Group Tags', testId: 'tags-panel' },
        Input({
            name: 'description',
            class: 'fx-flex mb-3',
            label: 'Description',
            value: description,
            height: 38,
            onChange: (value, state) => {
                description.val = value;
                options.setValidity?.('description', state.valid);
            },
        }),
        div(
            { class: 'tg-tagging-form-fields flex-column fx-gap-3 fx-flex-wrap' },
            Input({
                name: 'data_source',
                label: 'Data Source',
                value: dataSource,
                height: 38,
                help: 'Original source of the dataset',
                onChange: (value, state) => {
                    dataSource.val = value;
                    options.setValidity?.('data_source', state.valid);
                },
            }),
            Input({
                name: 'source_process',
                label: 'Source Process',
                value: sourceProcess,
                height: 38,
                help: 'Process, program, or data flow that produced the dataset',
                onChange: (value, state) => {
                    sourceProcess.val = value;
                    options.setValidity?.('source_process', state.valid);
                },
            }),
            Input({
                name: 'business_domain',
                label: 'Business Domain',
                value: businessDomain,
                height: 38,
                help: 'Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing',
                onChange: (value, state) => {
                    businessDomain.val = value;
                    options.setValidity?.('business_domain', state.valid);
                },
            }),
            Input({
                name: 'transform_level',
                label: 'Transform Level',
                value: transformLevel,
                height: 38,
                help: 'Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)',
                onChange: (value, state) => {
                    transformLevel.val = value;
                    options.setValidity?.('transform_level', state.valid);
                },
            }),
            Input({
                name: 'source_system',
                label: 'Source System',
                value: sourceSystem,
                height: 38,
                help: 'Enterprise system source for the dataset',
                onChange: (value, state) => {
                    sourceSystem.val = value;
                    options.setValidity?.('source_system', state.valid);
                },
            }),
            Input({
                name: 'data_location',
                label: 'Data Location',
                value: dataLocation,
                height: 38,
                help: 'Physical or virtual location of the dataset, e.g., Headquarters, Cloud',
                onChange: (value, state) => {
                    dataLocation.val = value;
                    options.setValidity?.('data_location', state.valid);
                },
            }),
            Input({
                name: 'stakeholder_group',
                label: 'Stakeholder Group',
                value: stakeholderGroup,
                height: 38,
                help: 'Data owners or stakeholders responsible for the dataset',
                onChange: (value, state) => {
                    stakeholderGroup.val = value;
                    options.setValidity?.('stakeholder_group', state.valid);
                },
            }),
            Input({
                name: 'data_product',
                label: 'Data Product',
                value: dataProduct,
                height: 38,
                help: 'Data domain that comprises the dataset',
                onChange: (value, state) => {
                    dataProduct.val = value;
                    options.setValidity?.('data_product', state.valid);
                },
            }),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-column-flex {
    flex: 250px;
}
.tg-tagging-form-fields {
    height: 332px;
}
`);

export { TableGroupForm };
