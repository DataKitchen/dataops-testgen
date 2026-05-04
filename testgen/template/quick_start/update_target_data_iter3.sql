SET SEARCH_PATH TO {PROJECT_SCHEMA};

UPDATE f_ebike_sales
SET total_amount = (sale_price + 100) * quantity_sold,
    adjusted_total_amount = (sale_price + 100) * quantity_sold - discount_amount,
    sale_price = sale_price + 100
WHERE product_id = 30027;

-- Demo data quality issues on the customer dimension table (entity, table weight 10)
-- to showcase weighted DQ scoring. None of these columns are touched by the monitor demo.

-- ~25% of customers with mangled postal codes — triggers Valid_US_Zip.
-- Combined weight: 10 (entity) x 1.5 (Zip) x 2.0 (PII Address) = 30 per row.
UPDATE d_ebike_customers
SET postal_code = SUBSTRING(postal_code, 1, 4) || 'X'
WHERE customer_id % 4 = 0;

-- ~33% of customers with invalid income_level — triggers LOV_Match (baseline LOV: HIGH/LOW/MEDIUM).
-- Combined weight: 10 x 1.5 (Code) x 2.0 (PII Demographic) = 30 per row.
UPDATE d_ebike_customers
SET income_level = 'PREMIUM'
WHERE customer_id % 3 = 0;

-- ~33% of customers with non-numeric credit_card — triggers Pattern_Match.
-- Combined weight: 10 x 2.0 (ID-Secondary) x 1.0 = 20 per row. credit_card is also marked CDE.
UPDATE d_ebike_customers
SET credit_card = 'PENDING-VERIFY'
WHERE customer_id % 3 = 1;

-- ~5% of customers reassigned to share customer_id 100001 — triggers Unique, Unique_Pct, Dupe_Rows.
-- UPDATE rather than INSERT keeps the row count stable so Volume_Trend baselines aren't disturbed.
-- Combined weight: 10 x 3.0 (ID-Unique) x 1.0 = 30 per row. customer_id is also marked CDE.
-- This must run last because the other plays filter on customer_id.
UPDATE d_ebike_customers
SET customer_id = 100001
WHERE customer_id IN (
    SELECT customer_id FROM d_ebike_customers
     WHERE customer_id != 100001
     ORDER BY customer_id
     OFFSET 100 LIMIT 25
);
