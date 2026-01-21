import van from '../van.min.js';
import { Attribute } from './attribute.js';
import { Caption } from './caption.js';
import { loadStylesheet } from '../utils.js';

const { div, span } = van.tags;

const ScoreMetric = function(
    /** @type number */ score,
    /** @type number? */ profilingScore,
    /** @type number? */ testingScore,
) {
    loadStylesheet('scoreMetric', stylesheet);

    return div(
        { class: 'flex-column fx-align-flex-center score-metric' },
        Caption({ content: 'Score' }),
        span(
            { style: 'font-size: 28px;' },
            score ?? '--',
        ),
        (profilingScore || testingScore) ? div(
            { class: 'flex-row fx-gap-2 mt-1' },
            Attribute({ label: 'Profiling', value: profilingScore }),
            Attribute({ label: 'Testing', value: testingScore }),
        ) : '',
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.score-metric {
    min-width: 120px;
}
`);

export { ScoreMetric };
