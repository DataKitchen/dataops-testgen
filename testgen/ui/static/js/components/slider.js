/**
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {number} value
 * @property {number} min
 * @property {number} max
 * @property {number} step
 * @property {function(number)?} onChange
 * @property {string?} hint
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { input, label, span } = van.tags;

const Slider = (/** @type Properties */ props) => {
    loadStylesheet('slider', stylesheet);

    const value = van.state(getValue(props.value) ?? getValue(props.min) ?? 0);

    const handleInput = e => {
        value.val = Number(e.target.value);
        props.onChange?.(value.val);
    };

    return label(
        { class: 'flex-col fx-gap-1 clickable tg-slider--label text-caption' },
        props.label,
        input({
            type: "range",
            min: props.min ?? 0,
            max: props.max ?? 100,
            step: props.step ?? 1,
            value: value,
            oninput: handleInput,
            class: 'tg-slider--input',
        }),
        span({ class: "tg-slider--value" }, () => value.val),
        props.hint && span({ class: "tg-slider--hint" }, props.hint)
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-slider--label {
    display: flex;
    flex-direction: column;
    gap: 0.5em;
    font-family: inherit;
}

.tg-slider--value {
    font-size: 0.9em;
    color: var(--primary-text-color);
}

.tg-slider--hint {
    font-size: 0.8em;
    color: var(--disabled-text-color);
}

/* Basic reset and common styles for the range input */
input[type=range].tg-slider--input {
  -webkit-appearance: none; /* Override default WebKit styles */
  appearance: none;         /* Override default pseudo-element styles */
  width: 100%;              /* Full width */
  height: 20px;             /* Set height to accommodate thumb; track will be smaller */
  cursor: pointer;
  outline: none;
  background: transparent;  /* Make default track invisible, we'll style it manually */
  accent-color: var(--primary-color);    /* Sets thumb and selected track color for modern browsers (Chrome, Edge, Firefox) */
}

/* --- Thumb Styling (#06a04a) --- */
/* WebKit (Chrome, Safari, Opera, Edge Chromium) */
input[type=range].tg-slider--input::-webkit-slider-thumb {
  -webkit-appearance: none; /* Required to style */
  appearance: none;
  height: 20px;               /* Thumb height */
  width: 20px;                /* Thumb width */
  background-color: var(--primary-color);  /* Thumb color */
  border-radius: 50%;         /* Make it circular */
  border: none;               /* No border */
  margin-top: -7px;           /* Vertically center thumb on track. (Thumb height - Track height) / 2 = (20px - 6px) / 2 = 7px */
                                /* This assumes track height is 6px (defined below) */
}

/* Firefox */
input[type=range].tg-slider--input::-moz-range-thumb {
  height: 20px;               /* Thumb height */
  width: 20px;                /* Thumb width */
  background-color: var(--primary-color);  /* Thumb color */
  border-radius: 50%;         /* Make it circular */
  border: none;               /* No border */
}

/* IE / Edge Legacy (EdgeHTML) */
input[type=range].tg-slider--input::-ms-thumb {
  height: 20px;               /* Thumb height */
  width: 20px;                /* Thumb width */
  background-color: var(--primary-color);  /* Thumb color */
  border-radius: 50%;         /* Make it circular */
  border: 0;                  /* No border */
  /* margin-top: 1px; /* IE may need slight adjustment if track style requires it */
}

/* --- Track Styling --- */
/* Track "unselected" section: #EEEEEE */
/* Track "selected" section: #06a04a */

/* WebKit browsers */
input[type=range].tg-slider--input::-webkit-slider-runnable-track {
  width: 100%;
  height: 6px;                /* Track height */
  background: var(--grey);    /* Color of the "unselected" part of the track */
                              /* accent-color (set on the input) will color the "selected" part */
//   background: transparent !important;
  border-radius: 3px;         /* Rounded track edges */
}

/* Firefox */
input[type=range].tg-slider--input::-moz-range-track {
  width: 100%;
  height: 6px;                /* Track height */
//   background: var(--grey);        /* Color of the "unselected" part of the track */
  background: transparent !important;
  border-radius: 3px;         /* Rounded track edges */
}

/* For Firefox, the "selected" part of the track is ::-moz-range-progress */
/* This is often handled by accent-color, but explicitly styling it provides a fallback. */
input[type=range].tg-slider--input::-moz-range-progress {
  height: 6px;                /* Must match track height */
  background-color: var(--primary-color);  /* Color of the "selected" part */
  border-radius: 3px;         /* Rounded track edges */
}

/* IE / Edge Legacy (EdgeHTML) */
input[type=range].tg-slider--input::-ms-track {
  width: 100%;
  height: 6px;                /* Track height */
  cursor: pointer;

  /* Needs to be transparent for ms-fill-lower and ms-fill-upper to show through */
  background: transparent;
  border-color: transparent;
  color: transparent;
  border-width: 7px 0; /* Adjust vertical positioning; (thumb height - track height) / 2 */
}

input[type=range].tg-slider--input::-ms-fill-lower {
  background: var(--primary-color);        /* Color of the "selected" part */
  border-radius: 3px;         /* Rounded track edges */
}

input[type=range].tg-slider--input::-ms-fill-upper {
  background: var(--grey);        /* Color of the "unselected" part */
  border-radius: 3px;         /* Rounded track edges */
}

`);

export { Slider };