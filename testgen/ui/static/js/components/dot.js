import van from '../van.min.js';

const { span } = van.tags;


const dot = (props, color, size) => span({
    ...props,
    style: `${props.style ?? ''} ${sizeRules(size ?? 10)} border-radius: 50%; background: ${color ?? 'black'};`,
});

function sizeRules(size) {
    return `width: ${size}px; min-width: ${size}px; max-width: ${size}px; height: ${size}px; min-height: ${size}px; max-height: ${size}px;`
}

export { dot };