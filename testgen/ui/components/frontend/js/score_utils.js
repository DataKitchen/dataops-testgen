/**
 * Get a color based on a numeric score.
 * 
 * @param {number} score 
 * @returns {string}
 */
function getScoreColor(score) {
    if (Number.isNaN(parseFloat(score))) {
        return '#c4c4c4';
    }

    if (score >= 96) {
        return '#9CCC65';
    } else if (score >= 91) {
        return '#FDD835';
    } else if (score >= 86) {
        return '#FF9800';
    } else {
        return '#EF5350';
    }
}

export { getScoreColor };
