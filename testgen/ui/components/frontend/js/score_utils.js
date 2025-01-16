import { colorMap } from './display_utils.js';

/**
 * Get a color based on a numeric score.
 * 
 * @param {number} score 
 * @returns {string}
 */
function getScoreColor(score) {
    if (Number.isNaN(parseFloat(score))) {
        const stringScore = String(score);
        if (stringScore.startsWith('>')) {
            return colorMap.green;
        } else if (stringScore.startsWith('<')) {
            return colorMap.red;
        }
        return colorMap.grey;
    }

    if (score >= 96) {
        return colorMap.green;
    } else if (score >= 91) {
        return colorMap.yellow;
    } else if (score >= 86) {
        return colorMap.orange;
    } else {
        return colorMap.red;
    }
}

export { getScoreColor };
