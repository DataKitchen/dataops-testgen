
WITH max_sale_id AS (
    SELECT MAX(sale_id) AS max_id FROM demo.f_ebike_sales
),
new_sales AS (
    SELECT
        max_id + ROW_NUMBER() OVER () AS sale_id,
        sale_date + (i * INTERVAL '1 day') AS sale_date,
        customer_id,
        supplier_id,
        product_id,
        quantity_sold,
        sale_price,
        total_amount,
        discount_amount,
        adjusted_total_amount,
        warranty_end_date,
        next_maintenance_date,
        return_reason
    FROM
        demo.f_ebike_sales,
        max_sale_id,
        generate_series(1, {NEW_SALES}) AS i
    LIMIT {NEW_SALES}
)
INSERT INTO demo.f_ebike_sales (
    sale_id,
    sale_date,
    customer_id,
    supplier_id,
    product_id,
    quantity_sold,
    sale_price,
    total_amount,
    discount_amount,
    adjusted_total_amount,
    warranty_end_date,
    next_maintenance_date,
    return_reason
)
SELECT * FROM new_sales;


UPDATE demo.d_ebike_customers
SET last_contact = :RUN_DATE
WHERE ctid IN (
    SELECT ctid
    FROM demo.d_ebike_customers
    ORDER BY RANDOM()
    LIMIT 10
);


UPDATE demo.d_ebike_suppliers
SET last_order = :RUN_DATE
WHERE supplier_id IN (
    SELECT supplier_id
    FROM demo.d_ebike_suppliers
    ORDER BY RANDOM()
    LIMIT 2
);


-- TG-IF IS_UPDATE_PRODUCT_ITER
UPDATE demo.d_ebike_products
SET price = price + 50 * (RANDOM() - 0.5)
WHERE product_id IN (
    SELECT product_id
    FROM demo.d_ebike_products
    ORDER BY RANDOM()
    LIMIT 4
);
-- TG-ENDIF


-- TG-IF IS_CUSTOMER_DEL_COL_ITER
ALTER TABLE demo.d_ebike_customers
    DROP COLUMN occupation,
    DROP COLUMN tax_id;
-- TG-ENDIF


-- TG-IF IS_CUSTOMER_ADD_COL_ITER
ALTER TABLE demo.d_ebike_customers
    ADD COLUMN is_international BOOL DEFAULT FALSE,
    ADD COLUMN first_contact DATE;
-- TG-ENDIF


-- TG-IF IS_ADD_TABLE_ITER
CREATE TABLE demo.f_ebike_returns
(
    return_id INTEGER,
    sale_id INTEGER,
    return_date DATE,
    refund_amount NUMERIC(10, 2),
    return_reason TEXT
);
-- TG-ENDIF
