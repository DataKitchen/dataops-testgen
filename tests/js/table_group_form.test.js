// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import van from '../../testgen/ui/static/js/van.min.js';
import { TableGroupForm } from '../../testgen/ui/static/js/components/table_group_form.js';

const TABLE_GROUP = {
    id: 'tg-1',
    connection_id: 1,
    table_groups_name: 'Sales',
    table_group_schema: 'sales',
};

const render = (tableGroup, tableNames) => {
    const onChange = vi.fn();
    const form = TableGroupForm({ tableGroup, connections: [], tableNames, onChange });
    van.add(document.body, form);
    vi.runAllTimers();
    return { form, lastChange: () => onChange.mock.calls.at(-1) };
};

const filterInputs = (form) => [...form.querySelectorAll('input[name^="table_filter_"], textarea[name^="table_filter_"]')];

const setInput = (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('change'));
    vi.runAllTimers();
};

const clickButton = (form, label) => {
    [...form.querySelectorAll('button')].find(button => button.textContent.includes(label)).click();
    vi.runAllTimers();
};

describe('TableGroupForm table filters', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => {
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    it('sends no table filters when the table group has none', () => {
        const { form, lastChange } = render({ ...TABLE_GROUP, table_filters: null });

        expect(filterInputs(form)).toHaveLength(0);
        expect(form.textContent).toContain('No table filters yet');
        expect(lastChange()[0].table_filters).toBeNull();
    });

    it('opens with the stored filters, one row per table', () => {
        const tableFilters = [{ table_name: 'orders', condition: "region = 'EMEA'" }];
        const { form, lastChange } = render({ ...TABLE_GROUP, table_filters: tableFilters });

        expect(filterInputs(form).map(input => input.value)).toEqual(['orders', "region = 'EMEA'"]);
        expect(lastChange()[0].table_filters).toEqual(tableFilters);
    });

    it('adds a filter row and sends its trimmed table and condition', () => {
        const { form, lastChange } = render({ ...TABLE_GROUP, table_filters: null });

        clickButton(form, 'Add Filter');
        const [table, condition] = filterInputs(form);
        setInput(table, ' orders ');
        setInput(condition, " region = 'EMEA' ");

        expect(lastChange()[0].table_filters).toEqual([{ table_name: 'orders', condition: "region = 'EMEA'" }]);
    });

    it('removes a filter row', () => {
        const { form, lastChange } = render({
            ...TABLE_GROUP,
            table_filters: [{ table_name: 'orders', condition: "region = 'EMEA'" }],
        });

        [...form.querySelectorAll('.tg-table-filters--row button')].at(-1).click();
        vi.runAllTimers();

        expect(filterInputs(form)).toHaveLength(0);
        expect(lastChange()[0].table_filters).toBeNull();
    });
});

describe('TableGroupForm panel summaries', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => {
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    const panel = (form, title) => [...form.querySelectorAll('[data-testid="expansion-panel"]')]
        .find(element => element.querySelector('[data-testid="expansion-panel-trigger"]').textContent.startsWith(title));
    const summary = (form, title) => panel(form, title)
        .querySelector('[data-testid="expansion-panel-summary"]')?.textContent;
    const help = (form, title) => panel(form, title)
        .querySelector('[data-testid="expansion-panel-help"]')?.textContent;
    const toggle = (form, title) => {
        panel(form, title).querySelector('[data-testid="expansion-panel-trigger"]').click();
        vi.runAllTimers();
    };

    it('counts only complete table filters', () => {
        const { form } = render({
            ...TABLE_GROUP,
            table_filters: [
                { table_name: 'orders', condition: "region = 'EMEA'" },
                { table_name: 'customers', condition: 'active' },
            ],
        });
        expect(summary(form, 'Table Filters')).toBe('2 filters applied');

        clickButton(form, 'Add Filter');
        expect(summary(form, 'Table Filters')).toBe('2 filters applied');
    });

    it('shows help in place of an empty summary', () => {
        const { form } = render({ ...TABLE_GROUP, table_filters: null, profile_use_sampling: false });
        expect(summary(form, 'Table Filters')).toBeUndefined();
        expect(help(form, 'Table Filters')).toBe('Read only matching records from specific tables');
        expect(summary(form, 'Sampling Parameters')).toBeUndefined();
        expect(help(form, 'Sampling Parameters')).toBeTruthy();
    });

    it('summarizes sampling the way the table group card does', () => {
        const { form } = render({
            ...TABLE_GROUP,
            profile_use_sampling: true,
            profile_sample_percent: 30,
            profile_sample_min_count: 15000,
        });
        expect(summary(form, 'Sampling Parameters')).toBe('30% (min 15,000 rows)');
    });

    it('hides the summary and help while the panel is open', () => {
        const { form } = render({
            ...TABLE_GROUP,
            table_filters: null,
            profile_use_sampling: true,
            profile_sample_percent: 30,
            profile_sample_min_count: 15000,
        });
        toggle(form, 'Table Filters');
        toggle(form, 'Sampling Parameters');
        expect(help(form, 'Table Filters')).toBeUndefined();
        expect(summary(form, 'Sampling Parameters')).toBeUndefined();
    });

    it('flags a collapsed panel that holds an invalid value', () => {
        const { form } = render(TABLE_GROUP);
        toggle(form, 'Settings');
        setInput(form.querySelector('input[name="profiling_delay_days"]'), '5000');
        toggle(form, 'Settings');
        expect(summary(form, 'Settings')).toBe('Contains errors');
    });
});

describe('TableGroupForm sampling fields', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => {
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    it('disables the sampling parameters while sampling is off', () => {
        const { form } = render({ ...TABLE_GROUP, profile_use_sampling: false });
        const percent = form.querySelector('input[name="profile_sample_percent"]');
        const minCount = form.querySelector('input[name="profile_sample_min_count"]');
        expect(percent.disabled).toBe(true);
        expect(minCount.disabled).toBe(true);

        const checkbox = form.querySelector('input[name="profile_use_sampling"]');
        checkbox.checked = true;
        checkbox.dispatchEvent(new Event('change'));
        vi.runAllTimers();
        expect(percent.disabled).toBe(false);
        expect(minCount.disabled).toBe(false);
    });
});

describe('TableGroupForm condition boxes', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => {
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    const conditionBox = (form) => form.querySelector('textarea[name^="table_filter_condition_"]');

    it('opens a short condition at one line', () => {
        const { form } = render({ ...TABLE_GROUP, table_filters: [{ table_name: 'orders', condition: 'active' }] });
        expect(conditionBox(form).style.minHeight).toBe('38px');
    });

    it('opens a long condition taller, up to a limit', () => {
        const { form } = render({ ...TABLE_GROUP, table_filters: [{ table_name: 'orders', condition: 'x'.repeat(130) }] });
        expect(conditionBox(form).style.minHeight).toBe('78px');

        document.body.innerHTML = '';
        const { form: longest } = render({ ...TABLE_GROUP, table_filters: [{ table_name: 'orders', condition: 'x'.repeat(1000) }] });
        expect(conditionBox(longest).style.minHeight).toBe('98px');
    });
});
