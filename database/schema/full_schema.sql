-- ============================================================
-- COCKROACHDB MASTER SCHEMA (LATEST)
-- Consolidated from database/schema/ and database/backup/
-- Generated on: 2026-02-24
-- ============================================================

-- ============================================================
-- 1. EXTENSIONS & CONFIGURATION
-- ============================================================
-- Note: CockroachDB handles extensions differently, standard ones like uuid-ossp are built-in.

-- ============================================================
-- 2. CORE PROPERTY TABLES
-- ============================================================

-- Main properties table (source from scraping/manual entry)
CREATE TABLE IF NOT EXISTS properties (
    id VARCHAR(255) PRIMARY KEY,
    address TEXT,
    suburb TEXT,
    city TEXT,
    postcode TEXT,
    year_built INTEGER,
    bedrooms INTEGER,
    bathrooms INTEGER,
    car_spaces INTEGER,
    floor_size TEXT,
    land_area TEXT,
    last_sold_price DOUBLE PRECISION,
    last_sold_date DATE,
    capital_value DOUBLE PRECISION,
    land_value DOUBLE PRECISION,
    improvement_value DOUBLE PRECISION,
    has_rental_history BOOLEAN DEFAULT FALSE,
    is_currently_rented BOOLEAN DEFAULT FALSE,
    status TEXT,
    property_history TEXT,
    normalized_address TEXT,
    property_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    region TEXT,
    cover_image_url TEXT,
    address_fingerprint TEXT UNIQUE,
    land_area_numeric NUMERIC,
    description TEXT,
    property_type TEXT,
    images JSONB,
    image_sync_status INTEGER DEFAULT 0,
    sale_status VARCHAR(50) DEFAULT 'unknown',
    sale_status_source VARCHAR(255),
    sale_status_updated_at TIMESTAMPTZ,
    estimated_value_low DOUBLE PRECISION,
    estimated_value_high DOUBLE PRECISION,
    suburb_median_price DOUBLE PRECISION,
    suburb_median_rent DOUBLE PRECISION,
    suburb_days_on_market INTEGER
);

-- Real estate listings table (active listings)
CREATE TABLE IF NOT EXISTS real_estate (
    id VARCHAR(255) PRIMARY KEY DEFAULT md5(random()::text || clock_timestamp()::text),
    address TEXT NOT NULL,
    status TEXT,
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    normalized_lead_address TEXT,
    listing_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    listing_date_raw TEXT,
    price_display TEXT,
    agent_name TEXT,
    bedroom_count INTEGER,
    bathroom_count INTEGER,
    land_area INTEGER,
    floor_area INTEGER,
    property_url TEXT,
    original_link TEXT,
    region TEXT DEFAULT 'auckland',
    address_fingerprint TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION
);

-- Rental properties table
CREATE TABLE IF NOT EXISTS real_estate_rent (
    id VARCHAR(255) PRIMARY KEY DEFAULT md5(random()::text || clock_timestamp()::text),
    address TEXT,
    status TEXT,
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    normalized_lead_address TEXT,
    listing_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    listing_date_raw TEXT,
    price_display TEXT,
    agent_name TEXT,
    bedroom_count INTEGER,
    bathroom_count INTEGER,
    land_area INTEGER,
    floor_area INTEGER,
    property_url TEXT,
    original_link TEXT,
    region TEXT DEFAULT 'auckland',
    address_fingerprint TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS property_history (
    id VARCHAR(255) PRIMARY KEY DEFAULT md5(random()::text || clock_timestamp()::text),
    property_id VARCHAR(255) REFERENCES properties(id) ON DELETE CASCADE,
    event_description TEXT,
    event_date DATE NOT NULL,
    interval_since_last_event TEXT,
    UNIQUE(property_id, event_date, event_description)
);

CREATE TABLE IF NOT EXISTS property_history_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id VARCHAR(255) REFERENCES properties(id) ON DELETE CASCADE,
    event_date DATE NOT NULL,
    event_type VARCHAR(50),
    price NUMERIC,
    description TEXT,
    interval_since_last TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(property_id, event_date, description)
);

CREATE INDEX IF NOT EXISTS idx_property_history_events_prop_id ON property_history_events (property_id);
CREATE INDEX IF NOT EXISTS idx_property_history_events_date ON property_history_events (event_date);

-- AI prediction results
CREATE TABLE IF NOT EXISTS property_status (
    id VARCHAR(255) PRIMARY KEY DEFAULT md5(random()::text || clock_timestamp()::text),
    property_id VARCHAR(255),
    predicted_status VARCHAR(50),
    confidence_score NUMERIC,
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. SCRAPER & SYSTEM CONTROL TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS scraping_progress (
    id SERIAL PRIMARY KEY,
    last_processed_id TEXT,
    batch_size INTEGER,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'idle',
    description TEXT
);

CREATE TABLE IF NOT EXISTS api_keepalive_status (
    id INTEGER PRIMARY KEY DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'idle',
    last_ping_time TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);

-- ============================================================
-- 4. ANALYTICS & MONITORING TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id TEXT NOT NULL,
    date DATE NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    ai_questions INTEGER DEFAULT 0,
    ai_summaries INTEGER DEFAULT 0,
    language TEXT DEFAULT 'en',
    userid TEXT,
    pageviews INTEGER DEFAULT 0,
    uniquevisitors INTEGER DEFAULT 0,
    reads INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS post_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id TEXT NOT NULL,
    title TEXT DEFAULT 'Blog Post',
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    ai_questions INTEGER DEFAULT 0,
    ai_summaries INTEGER DEFAULT 0,
    language TEXT DEFAULT 'en',
    comments INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS database_analysis_stats (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    auckland_properties INTEGER,
    wellington_properties INTEGER,
    auckland_forecast_total INTEGER,
    wellington_forecast_total INTEGER,
    auckland_forecast_90_percent INTEGER,
    auckland_forecast_80_percent INTEGER,
    auckland_forecast_60_percent INTEGER,
    wellington_forecast_90_percent INTEGER,
    wellington_forecast_80_percent INTEGER,
    wellington_forecast_60_percent INTEGER
);

CREATE TABLE IF NOT EXISTS real_estate_archive (
    id VARCHAR(255) PRIMARY KEY DEFAULT md5(random()::text || clock_timestamp()::text),
    address TEXT,
    status TEXT,
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 5. INDEXES & OPTIMIZATIONS
-- ============================================================

-- Address Fingerprint Indexes (Critical for cross-table joins)
CREATE INDEX IF NOT EXISTS idx_properties_fingerprint ON properties (address_fingerprint);
CREATE INDEX IF NOT EXISTS idx_properties_sale_status ON properties (sale_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_real_estate_fingerprint ON real_estate (address_fingerprint) WHERE address_fingerprint IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_real_estate_rent_fingerprint ON real_estate_rent (address_fingerprint) WHERE address_fingerprint IS NOT NULL;

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_real_estate_listing_date ON real_estate(listing_date);
CREATE INDEX IF NOT EXISTS idx_real_estate_rent_listing_date ON real_estate_rent(listing_date);
CREATE INDEX IF NOT EXISTS idx_properties_city_suburb ON properties(city, suburb);
CREATE INDEX IF NOT EXISTS idx_property_status_lookup ON property_status(property_id, predicted_at);

-- Property Image Update Optimization (for NULL cover_image_url queries)
CREATE INDEX IF NOT EXISTS idx_properties_null_cover_with_id 
ON properties (id) 
WHERE cover_image_url IS NULL;

-- ============================================================
-- 6. VIEWS
-- ============================================================

-- Match properties between listings and core data
CREATE OR REPLACE VIEW matched_properties AS
 SELECT p.id,
    p.address AS property_address,
    p.suburb,
    p.status,
    p.property_history,
    p.last_sold_date,
    p.year_built,
    p.bedrooms,
    p.bathrooms,
    p.car_spaces,
    p.floor_size,
    p.land_area,
    p.last_sold_price,
    p.capital_value,
    p.land_value,
    p.improvement_value,
    p.has_rental_history,
    p.is_currently_rented
   FROM real_estate r
   JOIN properties p ON lower(split_part(regexp_replace(p.address, ',[^,]*$', ''), ',', 1)) = lower(split_part(r.address, ',', 1));

-- Active listings currently for sale
CREATE OR REPLACE VIEW properties_with_is_listed AS
 SELECT p.id,
    p.address AS property_address,
    p.suburb,
    p.city,
    p.status AS p_status,
    1 AS status,
    p.property_history,
    p.last_sold_date,
    p.year_built,
    p.bedrooms,
    p.bathrooms,
    p.car_spaces,
    p.floor_size,
    p.land_area,
    p.last_sold_price,
    p.capital_value,
    p.land_value,
    p.improvement_value,
    p.has_rental_history,
    p.is_currently_rented
   FROM real_estate r
   JOIN properties p ON lower(split_part(regexp_replace(p.address, ',[^,]*$', ''), ',', 1)) = lower(split_part(r.address, ',', 1))
  WHERE r.status = 'for Sale';

-- Properties not currently listed (targets for prediction)
CREATE OR REPLACE VIEW properties_to_predict AS
 SELECT p.id,
    p.address AS property_address,
    p.suburb,
    p.city,
    p.status AS p_status,
    0 AS status,
    p.property_history,
    p.last_sold_date,
    p.year_built,
    p.bedrooms,
    p.bathrooms,
    p.car_spaces,
    p.floor_size,
    p.land_area,
    p.last_sold_price,
    p.capital_value,
    p.land_value,
    p.improvement_value,
    p.has_rental_history,
    p.is_currently_rented
   FROM properties p
  WHERE NOT EXISTS (
      SELECT 1 FROM real_estate r 
      WHERE r.status = 'for Sale' 
      AND lower(split_part(regexp_replace(p.address, ',[^,]*$', ''), ',', 1)) = lower(split_part(r.address, ',', 1))
  );

-- Combined dataset for training requirements
CREATE OR REPLACE VIEW full_properties_for_training AS
 SELECT * FROM properties_with_is_listed
 UNION ALL
 SELECT * FROM properties_to_predict;

-- Standard property view ordered by ID
CREATE OR REPLACE VIEW properties_view AS
 SELECT * FROM properties ORDER BY id;

-- High confidence predictions for display
CREATE OR REPLACE VIEW properties_with_latest_status AS
 SELECT p.address,
    p.suburb,
    p.city,
    ps.predicted_status,
    ps.confidence_score,
    p.last_sold_price,
    p.last_sold_date,
    p.property_history,
    p.year_built,
    p.bedrooms,
    p.bathrooms,
    p.car_spaces,
    p.floor_size,
    p.land_area,
    p.capital_value,
    p.land_value,
    p.improvement_value,
    p.has_rental_history,
    p.is_currently_rented,
    p.property_url,
    p.cover_image_url,
    ps.predicted_at
   FROM properties p
   LEFT JOIN property_status ps ON p.id = ps.property_id 
   AND ps.predicted_at = (SELECT max(ps_inner.predicted_at) FROM property_status ps_inner WHERE ps_inner.property_id = p.id)
  WHERE ps.predicted_status = 'for Sale' AND ps.confidence_score > 0.60
  ORDER BY ps.confidence_score DESC;

-- ============================================================
-- 7. COMMENTS & METADATA
-- ============================================================

COMMENT ON COLUMN properties.address_fingerprint IS 'Normalized address for cross-table matching (canonical form)';
COMMENT ON COLUMN real_estate.address_fingerprint IS 'Normalized address for cross-table matching (canonical form)';
COMMENT ON COLUMN real_estate_rent.address_fingerprint IS 'Normalized address for cross-table matching (canonical form)';
