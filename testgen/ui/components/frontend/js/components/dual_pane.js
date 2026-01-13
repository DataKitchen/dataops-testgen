/**
 * @typedef Options
 * @property {('left'|'right')} resizablePanel
 * @property {string} resizablePanelDomId
 * @property {number} minSize
 * @property {number} maxSize
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span } = van.tags;
const EMPTY_IMAGE = new Image(1, 1);
EMPTY_IMAGE.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==';

/**
 * 
 * @param {Options} options 
 * @param {HTMLElement?} left
 * @param {HTMLElement?} right
 * @returns 
 */
const DualPane = function (options, left, right) {
  loadStylesheet('dualPanel', stylesheet);

  const dragState = van.state(null);
  const dragConstraints = { min: options.minSize, max: options.maxSize };
  const dragResize = (/** @type Event */ event) => {
      // https://stackoverflow.com/questions/36308460/why-is-clientx-reset-to-0-on-last-drag-event-and-how-to-solve-it
      if (event.screenX && dragState.val) {
          const dragWidth = dragState.val.startWidth + (event.screenX - dragState.val.startX) * (options.resizablePanel === 'right' ? -1 : 1);
          const constrainedWidth = Math.min(dragConstraints.max, Math.max(dragWidth, dragConstraints.min));

          const element = document.getElementById(options.resizablePanelDomId);
          if (element) {
            element.style.minWidth = `${constrainedWidth}px`;
          }
      }
  };

  return div(
    { ...options, class: () => `tg-dualpane flex-row fx-align-flex-start ${getValue(options.class) ?? ''}` },
    left,
    div(
      {
        class: 'tg-dualpane-divider',
        draggable: true,
        ondragstart: (event) => {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setDragImage(EMPTY_IMAGE, 0, 0);

            const element = document.getElementById(options.resizablePanelDomId);
            dragState.val = { startX: event.screenX, startWidth: element.offsetWidth };
        },
        ondragend: (event) => {
            dragResize(event);
            dragState.val = null;
        },
        ondrag: (event) => dragState.rawVal ? dragResize(event) : null,
      },
      '',
    ),
    right,
  );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
    .tg-dualpane {
      // height: auto;
    }

    .tg-dualpane-divider {
      min-height: 100px;
      place-self: stretch;
      cursor: col-resize;
      min-width: 16px;
    }
`);

export { DualPane };
