// https://stackoverflow.com/a/4955179
function niceNumber(value, round = false) {
    const exponent = Math.floor(Math.log10(value));
    const fraction = value / Math.pow(10, exponent);
    let niceFraction;

    if (round) {
        if (fraction < 1.5) {
            niceFraction = 1;
        } else if (fraction < 3) {
            niceFraction = 2;
        } else if (fraction < 7) {
            niceFraction = 5;
        } else {
            niceFraction = 10;
        }
    } else {
        if (fraction <= 1) {
            niceFraction = 1;
        } else if (fraction <= 2) {
            niceFraction = 2;
        } else if (fraction <= 5) {
            niceFraction = 5;
        } else {
            niceFraction = 10;
        }
    }

    return niceFraction * Math.pow(10, exponent);
}

function niceBounds(axisStart, axisEnd, tickCount = 4) {
    let axisWidth = axisEnd - axisStart;

    if (axisWidth == 0) {
        axisStart -= 0.5;
        axisEnd += 0.5;
        axisWidth = axisEnd - axisStart;
    }

    const niceRange = niceNumber(axisWidth);
    const niceTick = niceNumber(niceRange / (tickCount - 1), true);
    axisStart = Math.floor(axisStart / niceTick) * niceTick;
    axisEnd = Math.ceil(axisEnd / niceTick) * niceTick;

    return {
        min: axisStart,
        max: axisEnd,
        step: niceTick,
        range: axisEnd - axisStart,
    };
}

export { niceBounds };
