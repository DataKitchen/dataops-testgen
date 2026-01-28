
/**
 * @typedef WizardStepMeta
 * @type {object}
 * @property {int} index
 * @property {string} title
 * @property {boolean} skipped
 * @property {string[]} includedSteps
 * 
 * @typedef CurrentStep
 * @type {object}
 * @property {int} index
 * @property {string} name
 * 
 * @param {WizardStepMeta[]} steps
 * @param {CurrentStep} currentStep
 * @returns 
 */
import van from '../van.min.js';
import { colorMap } from '../display_utils.js';

const { div, i, span } = van.tags;

const WizardProgressIndicator = (steps, currentStep) => {
  const currentPhysicalIndex = steps.findIndex(s => s.includedSteps.includes(currentStep.name));
  const progressWidth = van.state('0px');

  const updateProgress = () => {
    const container = document.getElementById('wizard-progress-container');
    const activeIcon = document.querySelector('.step-icon-current');

    if (container && activeIcon) {
      const containerRect = container.getBoundingClientRect();
      const iconRect = activeIcon.getBoundingClientRect();
      const centerOffset = (iconRect.left - containerRect.left) + (iconRect.width / 2);
      progressWidth.val = `${centerOffset}px`;
    }
  };

  setTimeout(updateProgress, 10);

  const progressLineStyle = () => `
    position: absolute;
    top: 10px;
    left: 0;
    height: 4px;
    width: ${progressWidth.val};
    background: ${colorMap.green};
    transition: width 0.3s ease-out;
    z-index: -4;
  `;

  const currentStepIndicator = (title, stepIndex) => div(
    { class: `flex-column fx-align-flex-center fx-gap-1 step-icon-current`, style: 'position: relative;' },
    stepIndex === 0
      ? div({ style: 'position: absolute; width: 50%; height: 50%;left: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    stepIndex === steps.length - 1
      ? div({ style: 'position: absolute; width: 50%; height: 50%;right: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    div(
      { class: 'flex-row fx-justify-center', style: `border: 2px solid black; background: var(--dk-card-background); border-radius: 50%; height: 24px; width: 24px;` },
      div({ style: 'width: 14px; height: 14px; border-radius: 50%; background: black;' }, ''),
    ),
    span({}, title),
  );

  const pendingStepIndicator = (title, stepIndex) => div(
    { class: `flex-column fx-align-flex-center fx-gap-1 ${currentPhysicalIndex === stepIndex ? 'step-icon-current' : 'text-secondary'}`, style: 'position: relative;' },
    stepIndex === 0
      ? div({ style: 'position: absolute; width: 50%; height: 50%;left: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    stepIndex === steps.length - 1
      ? div({ style: 'position: absolute; width: 50%; height: 50%;right: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    div(
      { class: 'flex-row', style: `color: white; border: 2px solid ${colorMap.lightGrey}; background: var(--dk-card-background); border-radius: 50%;` },
      i({style: 'width: 20px; height: 20px;'}, ''),
    ),
    span({}, title),
  );

  const completedStepIndicator = (title, stepIndex) => div(
    { class: `flex-column fx-align-flex-center fx-gap-1 ${currentPhysicalIndex === stepIndex ? 'step-icon-current' : 'text-secondary'}`, style: 'position: relative;' },
    stepIndex === 0
      ? div({ style: 'position: absolute; width: 50%; height: 50%;left: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    stepIndex === steps.length - 1
      ? div({ style: 'position: absolute; width: 50%; height: 50%;right: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    div(
      { class: 'flex-row', style: `color: white; border: 2px solid ${colorMap.green}; background: ${colorMap.green}; border-radius: 50%;` },
      i(
        {
            class: 'material-symbols-rounded',
            style: `font-size: 20px; color: white;`,
        },
        'check',
      ),
    ),
    span({}, title),
  );

  const skippedStepIndicator = (title, stepIndex) => div(
    { class: `flex-column fx-align-flex-center fx-gap-1 ${currentPhysicalIndex === stepIndex ? 'step-icon-current' : 'text-secondary'}`, style: 'position: relative;' },
    stepIndex === 0
      ? div({ style: 'position: absolute; width: 50%; height: 50%;left: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    stepIndex === steps.length - 1
      ? div({ style: 'position: absolute; width: 50%; height: 50%;right: 0px;background: var(--dk-card-background); z-index: -1;' }, '')
      : '',
    div(
      { class: 'flex-row', style: `color: white; border: 2px solid ${colorMap.grey}; background: ${colorMap.grey}; border-radius: 50%;` },
      i(
        {
            class: 'material-symbols-rounded',
            style: `font-size: 20px; color: white;`,
        },
        'remove',
      ),
    ),
    span({}, title),
  );

  return div(
    {
      id: 'wizard-progress-container',
      class: 'flex-row fx-justify-space-between mb-5',
      style: 'position: relative; margin-top: -20px;'
    },
    div({ style: `position: absolute; top: 10px; left: 0; width: 100%; height: 4px; background: ${colorMap.grey}; z-index: -5;` }),
    div({ style: progressLineStyle }),

    ...steps.map((step, physicalIdx) => {
      if (step.index < currentStep.index) {
        if (step.skipped) return skippedStepIndicator(step.title, physicalIdx);
        return completedStepIndicator(step.title, physicalIdx);
      } else if (step.includedSteps.includes(currentStep.name)) {
        return currentStepIndicator(step.title, physicalIdx);
      } else {
        return pendingStepIndicator(step.title, physicalIdx);
      }
    }),
  );
};

export { WizardProgressIndicator };
