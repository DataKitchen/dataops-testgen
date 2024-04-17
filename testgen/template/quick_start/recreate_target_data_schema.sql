create schema if not exists {PROJECT_SCHEMA};

SET SEARCH_PATH TO {PROJECT_SCHEMA};

DROP TABLE if exists d_ebike_customers CASCADE;

CREATE TABLE d_ebike_customers (
    customer_id INTEGER,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    address VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    postal_code VARCHAR(10),
    country VARCHAR(100),
    customer_type VARCHAR(20),
    avg_age INT,
    income_level VARCHAR(10),
    gender VARCHAR(10),
    occupation VARCHAR(100),
    marital_status VARCHAR(20),
    customer_note TEXT,
    sales_region VARCHAR(10),
    sales_territory VARCHAR(10),
    customer_decile INT,
    phone_number VARCHAR(40),
    tax_id VARCHAR(15),
    credit_card VARCHAR(20),
    last_contact DATE
);

DROP TABLE if exists tmp_d_ebike_customers CASCADE;

CREATE TABLE tmp_d_ebike_customers (
    customer_id INTEGER,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    address VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    postal_code VARCHAR(10),
    country VARCHAR(100),
    customer_type VARCHAR(20),
    avg_age INT,
    income_level VARCHAR(10),
    gender VARCHAR(10),
    occupation VARCHAR(100),
    marital_status VARCHAR(20),
    customer_note TEXT,
    sales_region VARCHAR(10),
    sales_territory VARCHAR(10),
    customer_decile INT,
    phone_number VARCHAR(40),
    tax_id VARCHAR(15),
    credit_card VARCHAR(20),
    last_contact DATE
);

DROP TABLE if exists d_ebike_products CASCADE;

CREATE TABLE d_ebike_products (
    product_id INTEGER,
    product_name VARCHAR(255) NOT NULL,
    product_description TEXT,
    product_type VARCHAR(50), --CHECK (product_type IN ('Bicycle', 'E-bike', 'E-scooter')),
    frame_size VARCHAR(50),
    battery_life INT,  -- in hours; NULL for regular bicycles
    max_speed DECIMAL(5,2),  -- in mph or km/h; NULL for regular bicycles
    weight_capacity DECIMAL(10,2),  -- in lbs or kg
    color VARCHAR(50),
    wheel_size DECIMAL(5,2),  -- in inches or cm
    gear_count INT,
    country_of_origin VARCHAR(50),
    price DECIMAL(10,2) NOT NULL,
    max_discount DECIMAL(5,2)
);

DROP TABLE if exists tmp_d_ebike_products CASCADE;

CREATE TABLE tmp_d_ebike_products (
    product_id INTEGER,
    product_name VARCHAR(255) NOT NULL,
    product_description TEXT,
    product_type VARCHAR(50), -- CHECK (product_type IN ('Bicycle', 'E-bike', 'E-scooter')),
    frame_size VARCHAR(50),
    battery_life INT,  -- in hours; NULL for regular bicycles
    max_speed DECIMAL(5,2),  -- in mph or km/h; NULL for regular bicycles
    weight_capacity DECIMAL(10,2),  -- in lbs or kg
    color VARCHAR(50),
    wheel_size DECIMAL(5,2),  -- in inches or cm
    gear_count INT,
    country_of_origin VARCHAR(50),
    price DECIMAL(10,2) NOT NULL,
    max_discount DECIMAL(5,2)
);

DROP TABLE IF EXISTS d_ebike_suppliers CASCADE;

CREATE TABLE d_ebike_suppliers (
    supplier_id INTEGER,
    supplier_name VARCHAR(255) NOT NULL,
    is_manufacturer BOOLEAN DEFAULT FALSE,
    manufacturing_certifications TEXT,
    contact_name VARCHAR(255),
    contact_email VARCHAR(100),
    address VARCHAR(255),
    country VARCHAR(100),
    region_code VARCHAR(50),
    phone VARCHAR(30),
    last_order DATE,
    key_supplier VARCHAR(3),
    supply_reliability VARCHAR(3)
);

DROP TABLE IF EXISTS tmp_d_ebike_suppliers CASCADE;

CREATE TABLE tmp_d_ebike_suppliers (
    supplier_id INTEGER,
    supplier_name VARCHAR(255) NOT NULL,
    is_manufacturer BOOLEAN DEFAULT FALSE,
    manufacturing_certifications TEXT,
    contact_name VARCHAR(255),
    contact_email VARCHAR(100),
    address VARCHAR(255),
    country VARCHAR(100),
    region_code VARCHAR(50),
    phone VARCHAR(30),
    last_order DATE,
    key_supplier VARCHAR(3),
    supply_reliability VARCHAR(3)
);

DROP TABLE IF EXISTS tmp_ebike_sales CASCADE;

CREATE TABLE tmp_ebike_sales (
    sale_id INTEGER,
    sale_date DATE,
    customer_id INT,
    supplier_id INT,
    product_id INT,
    quantity_sold INT,
    sale_price DECIMAL(10,2),
    total_amount DECIMAL(10,2),
    discount_amount DECIMAL(10,2) DEFAULT 0,
    adjusted_total_amount DECIMAL(10,2),
    warranty_end_date DATE,
    next_maintenance_date DATE,
    return_reason TEXT
);

DROP TABLE IF EXISTS f_ebike_sales CASCADE;

CREATE TABLE f_ebike_sales (
    sale_id INTEGER,
    sale_date DATE,
    customer_id INT,
    supplier_id INT,
    product_id INT,
    quantity_sold INT,
    sale_price DECIMAL(10,2),
    total_amount DECIMAL(10,2),
    discount_amount DECIMAL(10,2) DEFAULT 0,
    adjusted_total_amount DECIMAL(10,2),
    warranty_end_date DATE,
    next_maintenance_date DATE,
    return_reason TEXT
);
