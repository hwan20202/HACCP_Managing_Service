/* Production journal read contract: additive columns; quantities are integer e6.
   The report number is external master data, not a generated identifier or unique key. */
ALTER TABLE items ADD COLUMN manufacturing_report_number TEXT;

DROP VIEW v_doc_batch;
CREATE VIEW v_doc_batch AS
SELECT b.id AS production_batch_id,
       b.batch_number,
       b.process_type,
       b.status,
       b.shift,
       i.id AS item_id,
       i.item_code,
       i.name AS item_name,
       i.item_type,
       i.base_unit,
       i.unit_weight_mg,
       b.bom_id,
       bm.version AS bom_version,
       b.planned_date,
       b.planned_quantity_e6,
       b.manufactured_date,
       b.started_at,
       b.completed_at,
       (SELECT COALESCE(SUM(o.net_quantity_e6), 0) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_quantity_e6,
       (SELECT COUNT(DISTINCT o.lot_id) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_lot_count,
       (SELECT COUNT(*) FROM v_batch_usages u WHERE u.batch_id = b.id) AS input_line_count,
       st.name AS staff_name,
       i.item_code || ' ' || i.name || ' / ' || b.batch_number
           || ' / ' || COALESCE(b.manufactured_date, b.planned_date, '') AS subject_label,
       (SELECT GROUP_CONCAT(DISTINCT o.lot_number) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_lot_number,
       i.food_type,
       i.manufacturing_report_number
FROM production_batches b
JOIN items i ON i.id = b.item_id
JOIN staff st ON st.id = b.staff_id
LEFT JOIN boms bm ON bm.id = b.bom_id;

/* One row per batch/BOM line, including unconsumed and non-stock-managed items.
   Scale by PLAN, never by actual output. Integer quotient/remainder multiplication
   avoids SQLite promoting large e6 products to imprecise REALs. Binary multiplication
   takes at most 63 steps; remainders are added via subtraction to avoid overflow too.
   Result = ceil(line.quantity_e6 * plan_e6 / bom.base_quantity_e6). */
CREATE VIEW v_doc_batch_bom_line AS
WITH RECURSIVE scale (
    production_batch_id, bom_line_id, remaining, divisor, add_q, add_r, total_q, total_r
) AS (
    SELECT b.id, l.id, b.planned_quantity_e6, bm.base_quantity_e6,
           l.quantity_e6 / bm.base_quantity_e6, l.quantity_e6 % bm.base_quantity_e6,
           0, 0
    FROM production_batches b
    JOIN boms bm ON bm.id = b.bom_id
    JOIN bom_lines l ON l.bom_id = bm.id
    UNION ALL
    SELECT production_batch_id, bom_line_id, remaining / 2, divisor,
           CASE WHEN remaining > 1 THEN add_q * 2 + (add_r >= divisor - add_r) ELSE 0 END,
           CASE WHEN remaining <= 1 THEN 0
                WHEN add_r >= divisor - add_r THEN add_r - (divisor - add_r)
                ELSE add_r + add_r END,
           total_q + CASE WHEN remaining % 2 = 1
                          THEN add_q + (total_r >= divisor - add_r) ELSE 0 END,
           CASE WHEN remaining % 2 = 0 THEN total_r
                WHEN total_r >= divisor - add_r THEN total_r - (divisor - add_r)
                ELSE total_r + add_r END
    FROM scale WHERE remaining > 0
)
SELECT b.id AS production_batch_id,
       bm.id AS bom_id,
       bm.version AS bom_version,
       l.id AS bom_line_id,
       l.line_no,
       i.id AS item_id,
       i.item_code,
       i.name AS item_name,
       i.origin_country,
       i.base_unit,
       i.is_stock_managed,
       bm.base_quantity_e6 AS bom_base_quantity_e6,
       l.quantity_e6 AS bom_quantity_e6,
       b.planned_quantity_e6,
       CASE WHEN b.planned_quantity_e6 IS NULL THEN NULL
            ELSE s.total_q + (s.total_r > 0) END AS standard_quantity_e6
FROM scale s
JOIN production_batches b ON b.id = s.production_batch_id
JOIN boms bm ON bm.id = b.bom_id
JOIN bom_lines l ON l.id = s.bom_line_id
JOIN items i ON i.id = l.component_item_id
WHERE s.remaining = 0 OR s.remaining IS NULL;

/* One row per usage; preserve zero-net rows for audit. For earliest active input date,
   use MIN(input_date) WHERE net_quantity_e6 > 0, grouped by batch and bom_line_id.
   Legacy unlinked PRIMARY items match the batch's BOM by item, never by a name.
   Alternative quantities stay in the ACTUAL item's base unit (convert before summing). */
CREATE VIEW v_doc_batch_usage AS
SELECT b.id AS production_batch_id,
       u.usage_id,
       COALESCE(u.bom_line_id, bl.id) AS bom_line_id,
       COALESCE(linked.line_no, bl.line_no) AS line_no,
       COALESCE(linked.component_item_id, bl.component_item_id) AS bom_item_id,
       original.item_code AS bom_item_code,
       original.name AS bom_item_name,
       original.base_unit AS bom_base_unit,
       u.item_id,
       i.item_code,
       i.name AS item_name,
       i.origin_country,
       i.base_unit,
       i.is_stock_managed,
       u.lot_id,
       u.lot_number,
       u.quantity_e6,
       u.net_quantity_e6,
       u.stock_movement_id,
       m.occurred_at,
       date(m.occurred_at) AS input_date
FROM v_batch_usages u
JOIN production_batches b ON b.id = u.batch_id
JOIN items i ON i.id = u.item_id
JOIN stock_movements m ON m.id = u.stock_movement_id
LEFT JOIN bom_lines linked ON linked.id = u.bom_line_id
LEFT JOIN bom_lines bl ON u.bom_line_id IS NULL AND bl.bom_id = b.bom_id
                          AND bl.component_item_id = u.item_id
LEFT JOIN items original ON original.id = COALESCE(linked.component_item_id, bl.component_item_id);
