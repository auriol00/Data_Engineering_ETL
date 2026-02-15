-- ==========================================================================
--  Heycar Database Schema
--  Creates the relational tables for the data warehouse.
--  Run this once on first deployment — after that, SQLAlchemy ORM manages it.
-- ==========================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Raw data audit log: stores every API response verbatim
CREATE TABLE IF NOT EXISTS raw_data (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_content     JSONB NOT NULL,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_site     VARCHAR(50),
    source_url      TEXT,
    processed_at    TIMESTAMPTZ,
    error_log       TEXT
);

CREATE INDEX IF NOT EXISTS ix_raw_data_scraped_at   ON raw_data (scraped_at);
CREATE INDEX IF NOT EXISTS ix_raw_data_source_site  ON raw_data (source_site);
CREATE INDEX IF NOT EXISTS ix_raw_data_processed_at ON raw_data (processed_at);

-- Vehicle: canonical attributes for a unique car
CREATE TABLE IF NOT EXISTS vehicle (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    make                    VARCHAR(100),
    model                   VARCHAR(100),
    first_registration_year INTEGER,
    mileage_km              INTEGER,
    fuel_type               VARCHAR(50),
    vehicle_type            VARCHAR(50),
    power_bhp                INTEGER,
    transmission            VARCHAR(50),
    engine_size_l           NUMERIC(3, 1),
    color                   VARCHAR(50),
    doors                   INTEGER,
    seats                   INTEGER,
    emission_class          VARCHAR(20),
    ulez                    BOOLEAN,
    is_new_car              BOOLEAN,
    is_taxi                 BOOLEAN,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_vehicle_make_model_year ON vehicle (make, model, first_registration_year);

-- Listing: links a vehicle to a marketplace ad
CREATE TABLE IF NOT EXISTS listing (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_id      UUID REFERENCES vehicle(id) ON DELETE SET NULL,
    original_ad_id  VARCHAR(255) NOT NULL,
    source_site     VARCHAR(50) NOT NULL,
    url             TEXT,
    location        VARCHAR(200),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_listing_source_ad UNIQUE (source_site, original_ad_id)
);

CREATE INDEX IF NOT EXISTS ix_listing_source_site ON listing (source_site);
CREATE INDEX IF NOT EXISTS ix_listing_location    ON listing (location);

-- Price history: time-series price tracking per listing
CREATE TABLE IF NOT EXISTS price_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id  UUID NOT NULL REFERENCES listing(id) ON DELETE CASCADE,
    price       NUMERIC(12, 2),
    price_currency VARCHAR(3),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_price_listing_time UNIQUE (listing_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS ix_price_history_listing_time ON price_history (listing_id, recorded_at);
