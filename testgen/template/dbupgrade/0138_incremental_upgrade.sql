SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE score_definition_criteria (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    definition_id UUID NOT NULL REFERENCES score_definitions(id) ON DELETE CASCADE,
    operand VARCHAR NOT NULL DEFAULT 'AND',
    group_by_field BOOLEAN NOT NULL DEFAULT true
);

ALTER TABLE score_definition_filters
    ADD COLUMN criteria_id UUID DEFAULT NULL,
    ADD COLUMN next_filter_id UUID DEFAULT NULL,
    ADD CONSTRAINT score_definitions_filters_score_definition_criteria_fk FOREIGN KEY (criteria_id) REFERENCES score_definition_criteria (id) ON DELETE CASCADE,
    ADD CONSTRAINT score_definitions_filters_score_definitions_filters_fk FOREIGN KEY (next_filter_id) REFERENCES score_definition_filters (id) ON DELETE CASCADE;

DO $$
DECLARE
    current_definition_id UUID;
    new_criteria_id UUID;
    definition_filter RECORD;
BEGIN
    FOR current_definition_id IN SELECT id FROM score_definitions LOOP
        new_criteria_id := gen_random_uuid();
        RAISE NOTICE 'Definition = %', current_definition_id;
        RAISE NOTICE 'Create Score Criteria (AND)';
        EXECUTE format(
            'INSERT INTO score_definition_criteria (id, definition_id, operand, group_by_field) VALUES (%L, %L, %L, %L)',
            new_criteria_id, current_definition_id, 'AND', true
        );

        FOR definition_filter IN SELECT id, field, value FROM score_definition_filters WHERE definition_id = current_definition_id LOOP
            RAISE NOTICE 'Link filter to Score Criteria Field=% Value=%', definition_filter.field, definition_filter.value;
            EXECUTE format('UPDATE score_definition_filters SET criteria_id = %L WHERE id = %L', new_criteria_id, definition_filter.id);
        END LOOP;
    END LOOP;
END $$;

ALTER TABLE score_definition_filters DROP COLUMN definition_id;
