SET SEARCH_PATH TO {PROJECT_SCHEMA};

UPDATE f_ebike_sales
SET total_amount = (sale_price + 100) * quantity_sold,
    adjusted_total_amount = (sale_price + 100) * quantity_sold - discount_amount,
    sale_price = sale_price + 100
WHERE product_id = 30027;
