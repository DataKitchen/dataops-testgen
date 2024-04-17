SET SEARCH_PATH TO {PROJECT_SCHEMA};

TRUNCATE TABLE f_ebike_sales;

INSERT INTO f_ebike_sales
   (sale_id,
   customer_id, supplier_id, product_id, quantity_sold, sale_price, total_amount,
   discount_amount, adjusted_total_amount, return_reason,
   sale_date, warranty_end_date, next_maintenance_date)
SELECT t.sale_id,
       t.customer_id, t.supplier_id, t.product_id, t.quantity_sold, t.sale_price, t.total_amount,
       t.discount_amount, t.adjusted_total_amount, t.return_reason,
       t.sale_date + (SELECT (CURRENT_DATE - MAX(sale_date))::integer - 1 FROM tmp_ebike_sales),
       t.warranty_end_date + (SELECT (CURRENT_DATE - MAX(sale_date))::integer - 1 FROM tmp_ebike_sales),
       t.next_maintenance_date + (SELECT (CURRENT_DATE - MAX(sale_date))::integer - 1 FROM tmp_ebike_sales)
  FROM tmp_ebike_sales t
LEFT JOIN f_ebike_sales fes ON t.sale_id = fes.sale_id
 WHERE fes.sale_id IS NULL
   AND t.sale_date <= '{MAX_DATE}';


TRUNCATE TABLE d_ebike_customers;

INSERT INTO d_ebike_customers
(customer_id, first_name, last_name, address, city, state, postal_code, country, customer_type, avg_age, income_level,
 gender, occupation, marital_status, customer_note, sales_region, sales_territory, customer_decile, phone_number,
 tax_id, credit_card, last_contact)
SELECT t.customer_id,
       t.first_name,
       t.last_name,
       t.address,
       t.city,
       t.state,
       t.postal_code,
       t.country,
       t.customer_type,
       t.avg_age,
       t.income_level,
       t.gender,
       t.occupation,
       t.marital_status,
       t.customer_note,
       t.sales_region,
       t.sales_territory,
       t.customer_decile,
       t.phone_number,
       t.tax_id,
       t.credit_card,
       t.last_contact - (55 - (SELECT (CURRENT_DATE  - MAX(last_contact)) FROM tmp_d_ebike_customers))
FROM tmp_d_ebike_customers t
WHERE t.customer_id <= '{MAX_CUSTOMER_ID_SEQ}';

UPDATE d_ebike_customers
    SET last_contact =   CASE WHEN '{ITERATION_NUMBER}' = 1 AND
            current_date - last_contact <= 60 THEN last_contact - (62 - (current_date - last_contact))
           ELSE last_contact END;

TRUNCATE TABLE d_ebike_products;

INSERT INTO d_ebike_products
(product_id, product_name, product_description, product_type, frame_size, battery_life, max_speed, weight_capacity,
 color, wheel_size, gear_count, country_of_origin, price, max_discount)
SELECT t.product_id,
       t.product_name,
       t.product_description,
       t.product_type,
       t.frame_size,
       t.battery_life,
       t.max_speed,
       t.weight_capacity,
       t.color,
       t.wheel_size,
       t.gear_count,
       t.country_of_origin,
       t.price,
       t.max_discount
FROM tmp_d_ebike_products t
WHERE  product_id <= '{MAX_PRODUCT_ID_SEQ}';


TRUNCATE TABLE d_ebike_suppliers;

INSERT INTO d_ebike_suppliers
(supplier_id, supplier_name, is_manufacturer, manufacturing_certifications, contact_name, contact_email, address,
 country, region_code, phone, last_order, key_supplier, supply_reliability)
SELECT t.supplier_id,
       t.supplier_name,
       t.is_manufacturer,
       t.manufacturing_certifications,
       t.contact_name,
       t.contact_email,
       t.address,
       t.country,
       t.region_code,
       t.phone,
       t.last_order,
       t.key_supplier,
       t.supply_reliability
FROM tmp_d_ebike_suppliers t
WHERE t.supplier_id <= '{MAX_SUPPLIER_ID_SEQ}';
