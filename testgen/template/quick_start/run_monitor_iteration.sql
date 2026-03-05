
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
SET last_contact = :RUN_DATE,
    customer_decile = customer_decile + 1
WHERE ctid IN (
    SELECT ctid
    FROM demo.d_ebike_customers
    ORDER BY RANDOM()
    LIMIT 10
);


-- TG-IF IS_UPDATE_SUPPLIERS_ITER
UPDATE demo.d_ebike_suppliers
SET last_order = :RUN_DATE
WHERE supplier_id IN (40001, 40002);
-- TG-ENDIF


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


-- Metric_Trend variation: shift discount averages and product prices each iteration
UPDATE demo.f_ebike_sales
SET discount_amount = GREATEST(0, discount_amount + {DISCOUNT_DELTA});

UPDATE demo.d_ebike_products
SET price = GREATEST(50, price + {PRICE_DELTA});


-- TG-IF IS_DELETE_CUSTOMER_COL_ITER
ALTER TABLE demo.d_ebike_customers
    DROP COLUMN occupation,
    DROP COLUMN tax_id;
-- TG-ENDIF


-- TG-IF IS_ADD_CUSTOMER_COL_ITER
ALTER TABLE demo.d_ebike_customers
    ADD COLUMN is_international BOOL DEFAULT FALSE,
    ADD COLUMN first_contact DATE;
-- TG-ENDIF


-- TG-IF IS_CREATE_RETURNS_TABLE_ITER
CREATE TABLE demo.f_ebike_returns
(
    return_id INTEGER,
    sale_id INTEGER,
    return_date DATE,
    refund_amount NUMERIC(10, 2),
    return_reason TEXT
);

INSERT INTO demo.f_ebike_returns
(
    return_id,
    sale_id,
    return_date,
    refund_amount,
    return_reason
)
SELECT
    ROW_NUMBER() OVER (),
    sale_id,
    :RUN_DATE,
    sale_price * 0.8,
    'No reason'
FROM demo.f_ebike_sales
ORDER BY RANDOM()
LIMIT 200;
-- TG-ENDIF


-- TG-IF IS_DELETE_CUSTOMER_ITER
DELETE FROM demo.d_ebike_customers
WHERE customer_id IN
(
    SELECT customer_id FROM demo.d_ebike_customers ORDER BY RANDOM() LIMIT 1
);
-- TG-ENDIF
