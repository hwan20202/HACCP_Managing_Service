/* BOM substitutes are scoped to a versioned line. Existing production/document views stay intact. */
CREATE TABLE bom_line_alternatives (
    id INTEGER PRIMARY KEY,
    bom_line_id INTEGER NOT NULL REFERENCES bom_lines(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    UNIQUE (bom_line_id, item_id)
) STRICT;

CREATE TRIGGER trg_alternatives_valid BEFORE INSERT ON bom_line_alternatives
WHEN NEW.item_id = (SELECT component_item_id FROM bom_lines WHERE id = NEW.bom_line_id)
 OR NEW.item_id = (SELECT b.item_id FROM boms b JOIN bom_lines l ON l.bom_id = b.id WHERE l.id = NEW.bom_line_id)
BEGIN
    SELECT RAISE(ABORT, 'alternative cannot be the primary component or output item');
END;

CREATE TRIGGER trg_alternatives_locked_insert BEFORE INSERT ON bom_line_alternatives
WHEN EXISTS (SELECT 1 FROM production_batches b JOIN bom_lines l ON l.bom_id = b.bom_id WHERE l.id = NEW.bom_line_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

CREATE TRIGGER trg_alternatives_locked_delete BEFORE DELETE ON bom_line_alternatives
WHEN EXISTS (SELECT 1 FROM production_batches b JOIN bom_lines l ON l.bom_id = b.bom_id WHERE l.id = OLD.bom_line_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

CREATE TRIGGER trg_alternatives_no_update BEFORE UPDATE ON bom_line_alternatives
BEGIN
    SELECT RAISE(ABORT, 'replace alternatives before using the BOM; create a new version after use');
END;
