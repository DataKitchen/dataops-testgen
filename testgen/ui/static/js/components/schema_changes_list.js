/**
 * @typedef DataStructureLog
 * @type {object}
 * @property {('A'|'D'|'M')} change
 * @property {string} old_data_type
 * @property {string} new_data_type
 * @property {string} column_name
 * 
 * @typedef Properties
 * @type {object}
 * @property {number} window_start
 * @property {number} window_end
 * @property {(DataStructureLog[])?} data_structure_logs
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Icon } from '../components/icon.js';
import { formatTimestamp } from '../display_utils.js';
import { getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';

const { div, span } = van.tags;

/**
 * @param {Properties} props
 */
const SchemaChangesList = (props) => {
    loadStylesheet('schema-changes-list', stylesheet);
    const domId = 'schema-changes-list';

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(1);
        resizeFrameHeightToElement(domId);
        resizeFrameHeightOnDOMChange(domId);
    }
    
    const dataStructureLogs = getValue(props.data_structure_logs) ?? [];
    const windowStart = getValue(props.window_start);
    const windowEnd = getValue(props.window_end);

    return div(
        { id: domId, class: 'flex-column fx-gap-1 fx-flex schema-changes-list' },
        span({ style: 'font-size: 16px; font-weight: 500;' }, 'Schema Changes'),
        span(
          { class: 'mb-3 text-caption', style: 'min-width: 200px;' },
          `${formatTimestamp(windowStart)} ~ ${formatTimestamp(windowEnd)}`,
        ),
        ...dataStructureLogs.map(log => StructureLogEntry(log)),
    );
};

const StructureLogEntry = (/** @type {DataStructureLog} */ log) => {
  if (log.change === 'A') {
    return div(
      { class: 'flex-row fx-gap-1 fx-align-flex-start' },
      Icon(
        {style: `font-size: 20px; color: var(--primary-text-color)`, filled: !log.column_name},
        log.column_name ? 'add' : 'add_box',
      ),
      div(
        { class: 'schema-changes-item flex-column' },
        span({ class: 'truncate-text' }, log.column_name ?? 'Table added'),
        span(log.new_data_type),
      ),
    );
  } else if (log.change === 'D') {
    return div(
      { class: 'flex-row fx-gap-1' },
      Icon(
        {style: `font-size: 20px; color: var(--primary-text-color)`, filled: !log.column_name},
        log.column_name ? 'remove' : 'indeterminate_check_box',
      ),
      div(
        { class: 'schema-changes-item flex-column' },
        span({ class: 'truncate-text' }, log.column_name ?? 'Table dropped'),
      ),
    );
  } else if (log.change === 'M') {
    return div(
      { class: 'flex-row fx-gap-1 fx-align-flex-start' },
      Icon({style: `font-size: 18px; color: var(--primary-text-color)`}, 'change_history'),
      div(
        { class: 'schema-changes-item flex-column' },
        span({ class: 'truncate-text' }, log.column_name),

        div(
          { class: 'flex-row fx-gap-1' },
          span({ class: 'truncate-text' }, log.old_data_type),
          Icon({ size: 10 }, 'arrow_right_alt'),
          span({ class: 'truncate-text' }, log.new_data_type),
        ),
      ),
    );
  }

  return null;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
  .schema-changes-list {
    overflow-y: auto;
  }

  .schema-changes-item {
    color: var(--secondary-text-color);
    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
  }

  .schema-changes-item span {
    font-family: 'Courier New', Courier, monospace;

    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
  }

  .schema-changes-item > span:first-child {
    font-family: 'Roboto', 'Helvetica Neue', sans-serif;
    color: var(--primary-text-color);
  }
`);

export { SchemaChangesList };
