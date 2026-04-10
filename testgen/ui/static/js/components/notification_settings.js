/**
 * @typedef NotificationItem
 * @type {object}
 * @property {String?} scope
 * @property {String?} total_score_threshold
 * @property {String?} cde_score_threshold
 * @property {string[]} recipients
 * @property {string} trigger
 * @property {boolean} enabled
 * @property {string[]} duplicates
 *
 * @typedef Subtitle
 * @type {object}
 * @property {string} label
 * @property {string} value
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 *
 * @typedef Properties
 * @type {object}
 * @property {Boolean} smtp_configured
 * @property {String} event
 * @property {NotificationItem[]} items
 * @property {Permissions} permissions
 * @property {String} scope_label
 * @property {import('/app/static/js/components/select.js').Option[]} scope_options
 * @property {import('/app/static/js/components/select.js').Option[]} trigger_options
 * @property {Boolean} cde_enabled;
 * @property {Boolean} total_enabled;
 * @property {Subtitle?} subtitle
 * @property {Result?} result
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { ExpansionPanel } from '/app/static/js/components/expansion_panel.js';
import { Select } from '/app/static/js/components/select.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Textarea } from '/app/static/js/components/textarea.js';
import { Icon } from '/app/static/js/components/icon.js';
import { TruncatedText } from '/app/static/js/components/truncated_text.js';
import { Input } from '/app/static/js/components/input.js';
import { numberBetween } from '/app/static/js/form_validators.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '/app/static/js/components/empty_state.js';

const { div, span, b } = van.tags;

const NotificationSettings = (/** @type Properties */ props) => {
    const emit = props.emit;
  loadStylesheet('notification-settings', stylesheet);

  const dialogProp = getValue(props.dialog);
  const externalOpen = dialogProp?.open;
  const isVanState = externalOpen != null && typeof externalOpen === 'object' && 'val' in externalOpen;
  const dialogOpen = isVanState ? externalOpen : van.state(dialogProp?.open === true);
  if (!isVanState) {
    van.derive(() => { if (getValue(props.dialog)?.open === true) dialogOpen.val = true; });
  }

  const handleClose = () => {
    dialogOpen.val = false;
    if (typeof props.onClose === 'function') props.onClose();
    else emit('CloseClicked', {});
  };

  const smtpConfigured = van.derive(() => getValue(props.smtp_configured));
  const event = van.derive(() => getValue(props.event));
  const cdeScoreEnabled = van.derive(() => getValue(props.cde_enabled));
  const totalScoreEnabled = van.derive(() => getValue(props.total_enabled));
  const scopeOptions = van.derive(() => getValue(props.scope_options));
  const triggerOptions = van.derive(() => getValue(props.trigger_options));
  const nsItems = van.derive(() => getValue(props.items));
  const subtitle = van.derive(() => getValue(props.subtitle));

  const scopeLabel = (scope) => {
    const match = scopeOptions.val?.find(([key]) => key === scope);
    return match ? match[1] : '';
  };

  const triggerLabel = (trigger) => {
    const match = triggerOptions.val?.find(([key]) => key === trigger);
    return match ? match[1] : '';
  };

  const newNotificationItemForm = {
    id: van.state(null),
    scope: van.state(null),
    recipientsString: van.state(''),
    trigger: van.state(triggerOptions.val && triggerOptions.val.length > 0 ? triggerOptions.val[0][0] : null),
    totalScoreThreshold: van.state(0),
    cdeScoreThreshold: van.state(0),
    isEdit: van.state(false),
  };

  const resetForm = () => {
    newNotificationItemForm.id.val = null;
    newNotificationItemForm.scope.val = null;
    newNotificationItemForm.recipientsString.val = '';
    newNotificationItemForm.trigger.val = triggerOptions.val && triggerOptions.val.length > 0 ? triggerOptions.val[0][0] : null;
    newNotificationItemForm.totalScoreThreshold.val = 0;
    newNotificationItemForm.cdeScoreThreshold.val = 0;
    newNotificationItemForm.isEdit.val = false;
  };

  van.derive(() => {
    if (getValue(props.result)?.success && newNotificationItemForm.isEdit.rawVal) {
      resetForm();
    }
  });

  const panelExpanded = van.state(false);
  van.derive(() => { if (newNotificationItemForm.isEdit.val) panelExpanded.val = true; });
  van.derive(() => { if (!newNotificationItemForm.isEdit.val) panelExpanded.val = false; });

  const NotificationItem = (
        /** @type NotificationItem */ item,
        /** @type number[] */ columns,
        /** @type Permissions */ permissions,
  ) => {
    const showTotalScore = totalScoreEnabled.val && item.total_score_threshold !== '0.0';
    const showCdeScore = cdeScoreEnabled.val && item.cde_score_threshold !== '0.0';
    const duplicatedMessage = item.duplicates?.length
      ? `This notification will be delivered multiple times for: ${item.duplicates.join(', ')}`
      : '';

    return div(
      { class: 'flex-column table-row' },
      div(
        { class: () => `flex-row ${newNotificationItemForm.isEdit.val && newNotificationItemForm.id.val === item.id ? 'notifications--editing-row' : ''}` },
        event.val === 'score_drop'
          ? div(
            { style: `flex: ${columns[0]}%`, class: 'flex-column fx-gap-1 score-threshold' },
            showTotalScore ? div('Total score: ', b(item.total_score_threshold)) : '',
            showCdeScore ? div(`${showTotalScore ? 'or ' : ''}CDE score: `, b(item.cde_score_threshold)) : '',
          )
          : div(
            { style: `flex: ${columns[0]}%` },
            div(scopeLabel(item.scope)),
            div({ class: 'text-caption mt-1' }, triggerLabel(item.trigger)),
          ),
        div(
          { style: `flex: ${columns[1]}%` },
          TruncatedText({ max: 6 }, ...item.recipients),
        ),
        div(
          { class: 'flex-row fx-gap-2', style: `flex: ${columns[2]}%` },
          permissions.can_edit
            ? (newNotificationItemForm.isEdit.val && newNotificationItemForm.id.val === item.id
              ? div(
                { class: 'flex-row fx-gap-1' },
                Icon({ size: 18, classes: 'notifications--editing' }, 'edit'),
                span({ class: 'notifications--editing' }, 'Editing'),
              )
              : [
                item.enabled
                  ? Button({
                    type: 'stroked',
                    icon: 'pause',
                    tooltip: 'Pause notification',
                    style: 'height: 32px;',
                    onclick: () => emit('PauseNotification', { payload: item }),
                  })
                  : Button({
                    type: 'stroked',
                    icon: 'play_arrow',
                    tooltip: 'Resume notification',
                    style: 'height: 32px;',
                    onclick: () => emit('ResumeNotification', { payload: item }),
                  }),
                Button({
                  type: 'stroked',
                  icon: 'edit',
                  tooltip: 'Edit notification',
                  style: 'height: 32px;',
                  onclick: () => {
                    newNotificationItemForm.isEdit.val = true;
                    newNotificationItemForm.id.val = item.id;
                    newNotificationItemForm.recipientsString.val = item.recipients.join(', ');
                    if (event.val === 'score_drop') {
                      newNotificationItemForm.totalScoreThreshold.val = item.total_score_threshold;
                      newNotificationItemForm.cdeScoreThreshold.val = item.cde_score_threshold;
                    } else {
                      newNotificationItemForm.scope.val = item.scope;
                      newNotificationItemForm.trigger.val = item.trigger;
                    }
                  },
                }),
                Button({
                  type: 'stroked',
                  icon: 'delete',
                  tooltip: 'Delete notification',
                  tooltipPosition: 'top-left',
                  style: 'height: 32px;',
                  onclick: () => emit('DeleteNotification', { payload: item }),
                }),
              ]) : null,
        ),
      ),
      duplicatedMessage
        ? div(
          { class: 'flex-row fx-gap-1 text-caption text-warning' },
          Icon({ size: 12, classes: 'text-warning' }, 'warning'),
          span({}, duplicatedMessage),
        )
        : '',
    );
  };

  const columns = [30, 50, 20];
  const domId = 'notifications-table';

  const mainContentBuilder = () => div(
    { id: domId, class: 'flex-column fx-gap-2', style: 'height: 100%; overflow-y: auto;' },
    () => subtitle.val
      ? div(
        { class: 'flex-row fx-gap-1 mb-5 text-large' },
        span({ class: 'text-secondary' }, `${subtitle.val.label}: `),
        span(subtitle.val.value),
      )
      : '',
    ExpansionPanel(
      {
        title: () => newNotificationItemForm.isEdit.val
          ? span({ class: 'notifications--editing' }, 'Edit Notification')
          : 'Add Notification',
        testId: 'notification-item-editor',
        expanded: panelExpanded,
      },
      div(
        { class: 'flex-row fx-gap-4 fx-align-flex-start' },
        div(
          { style: 'flex: 40%' },
          () => event.val === 'score_drop'
            ? div(
              { class: 'flex-column fx-gap-2' },
              () => totalScoreEnabled.val
                ? Input({
                  label: 'When total score drops below',
                  value: newNotificationItemForm.totalScoreThreshold,
                  type: 'number',
                  step: 0.1,
                  onChange: (value) => newNotificationItemForm.totalScoreThreshold.val = value,
                  validators: [
                    numberBetween(0, 100, 1),
                  ],
                })
                : '',
              () => cdeScoreEnabled.val
                ? Input({
                  label: `${totalScoreEnabled.val ? 'or w' : 'W'}hen CDE score drops below`,
                  value: newNotificationItemForm.cdeScoreThreshold,
                  type: 'number',
                  step: 0.1,
                  onChange: (value) => newNotificationItemForm.cdeScoreThreshold.val = value,
                  validators: [
                    numberBetween(0, 100, 1),
                  ],
                })
                : '',
            )
            : div(
              { class: 'flex-column fx-gap-2' },
              () => Select({
                label: getValue(props.scope_label),
                options: scopeOptions.val.map(([value, label]) => ({
                  label: label, value: value
                })),
                value: newNotificationItemForm.scope,
                onChange: (value) => newNotificationItemForm.scope.val = value,
                portalClass: 'short-select-portal',
              }),
              () => event.val !== 'monitor_run'
                ? Select({
                  label: 'When',
                  options: triggerOptions.val.map(([value, label]) => ({
                    label: label, value: value
                  })),
                  value: newNotificationItemForm.trigger,
                  onChange: (value) => newNotificationItemForm.trigger.val = value,
                  portalClass: 'short-select-portal',
                })
                : '',
            ),
        ),
        div(
          { style: 'flex: 60%; height: 100%' },
          () => Textarea({
            label: 'Recipients',
            help: 'List of email addresses, separated by commas or newlines',
            placeholder: 'Email addresses separated by commas or newlines',
            height: 100,
            value: newNotificationItemForm.recipientsString,
            onChange: (value) => newNotificationItemForm.recipientsString.val = value,
          }),
        ),
      ),
      div(
        { class: 'flex-row fx-justify-content-flex-end fx-gap-2 mt-3' },
        () => newNotificationItemForm.isEdit.val
          ? Button({
            type: 'stroked',
            label: 'Cancel',
            width: 'auto',
            onclick: resetForm,
          })
          : '',
        Button({
          type: 'stroked',
          label: van.derive(() => newNotificationItemForm.isEdit.val ? 'Save Changes' : 'Add Notification'),
          width: 'auto',
          onclick: () => emit(
            newNotificationItemForm.isEdit.val ? 'UpdateNotification' : 'AddNotification',
            {
              payload: {
                id: newNotificationItemForm.isEdit.val ? newNotificationItemForm.id.val : null,
                scope: newNotificationItemForm.scope.val,
                recipients: [...new Set(newNotificationItemForm.recipientsString.val.split(/[,;\n ]+/).filter(s => s.length > 0))],
                ...(event.val === 'score_drop' ?
                  {
                    total_score_threshold: newNotificationItemForm.totalScoreThreshold.val,
                    cde_score_threshold: newNotificationItemForm.cdeScoreThreshold.val,
                  } : {
                    trigger: newNotificationItemForm.trigger.val,
                  }
                ),
              }
            }
          ),
        }),
      ),
    ),
    () => {
      const result = getValue(props.result);
      return result?.message
        ? div( // Wrapper div needed, otherwise new Alert does not appear after closing previous one
          Alert({
            type: result.success ? 'success' : 'error',
            class: 'mt-3',
            closeable: true,
            timeout: result.success ? 2000 : 5000,
          }, result.message)
        )
        : '';
    },
    div(
      { class: 'table fx-flex' },
      div(
        { class: 'table-header flex-row' },
        () => span(
          { style: `flex: ${columns[0]}%` },
          event.val === 'score_drop' ? 'Score Drop Threshold' : `${getValue(props.scope_label)} | Trigger`,
        ),
        span(
          { style: `flex: ${columns[1]}%` },
          'Recipients',
        ),
        span(
          { style: `flex: ${columns[2]}%` },
          'Actions',
        ),
      ),
      () => nsItems.val?.length
        ? div(
          nsItems.val.map(item => NotificationItem(item, columns, getValue(props.permissions))),
        )
        : div({ class: 'mt-5 mb-3 ml-3 text-secondary', style: 'text-align: center;' }, 'No notifications defined yet.'),
    ),
  );

  // mainContent is always kept in the DOM (just CSS-hidden when SMTP is unconfigured).
  // If it were conditionally removed, its reactive bindings would die while disconnected
  // and the items list would not update when the dialog is reopened.
  const mainContent = mainContentBuilder();

  const content = div(
    div({ style: () => smtpConfigured.val ? '' : 'display: none' }, mainContent),
    () => smtpConfigured.val
      ? ''
      : EmptyState({ emit, 
        label: 'Email server not configured.',
        message: EMPTY_STATE_MESSAGE.notifications,
        class: 'notifications--empty',
        link: {
          label: 'View documentation',
          href: 'https://docs.datakitchen.io/articles/dataops-testgen-help/configure-email-server',
          open_new: true,
        },
      }),
  );

  if (dialogProp) {
    const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? '');
    return Dialog(
      {
        title: dialogTitle,
        open: dialogOpen,
        onClose: handleClose,
        width: '65rem',
      },
      content,
    );
  }
  return content;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.notifications--empty.tg-empty-state {
    margin-top: 0;
}
.notifications--editing-row {
    background-color: var(--select-hover-background);
}
.notifications--editing {
    color: var(--purple);
}
.short-select-portal {
    max-height: 250px !important;
}
.score-threshold b {
    font-weight: 500;
}
`);

export { NotificationSettings };
