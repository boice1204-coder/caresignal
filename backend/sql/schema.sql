-- =========================================================================
-- CareSignal — BigQuery schema
-- Dataset: caresignal
--
-- Design notes:
--   * One `care_circle` (family) can have multiple `subjects` (parents) and
--     multiple `caregivers`. Kept separate from `subjects` so a household
--     with two parents under care still works without schema changes.
--   * All raw events land in source-specific tables (meds/vitals/meals/notes)
--     with a common `logged_at` / `source` / `caregiver_id` shape, so the
--     decision engine can treat them uniformly.
--   * `risk_alerts` + `audit_trail` are the trust layer: every alert a
--     caregiver sees in the app must have exactly one row here, and every
--     row must resolve to >=1 audit_trail rows pointing at raw source data.
--     This is what makes the "why am I seeing this" drill-down possible.
-- =========================================================================

CREATE SCHEMA IF NOT EXISTS `caresignal`
OPTIONS (description = 'CareSignal data intelligence layer');

-- ---------------------------------------------------------------------
-- Care circle + people
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `caresignal.care_circles` (
  circle_id     STRING NOT NULL,
  circle_name   STRING,
  created_at    TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `caresignal.subjects` (            -- the parent being cared for
  subject_id    STRING NOT NULL,
  circle_id     STRING NOT NULL,
  display_name  STRING NOT NULL,
  date_of_birth DATE,
  conditions    ARRAY<STRING>,                                -- e.g. ['hypertension','type2_diabetes']
  created_at    TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `caresignal.caregivers` (
  caregiver_id  STRING NOT NULL,
  circle_id     STRING NOT NULL,
  display_name  STRING NOT NULL,
  role          STRING                                        -- 'primary' | 'secondary'
);

-- ---------------------------------------------------------------------
-- Raw event tables (ingestion lands here, one row per logged item)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `caresignal.meds_log` (
  event_id       STRING NOT NULL,
  subject_id     STRING NOT NULL,
  caregiver_id   STRING,
  drug_name      STRING NOT NULL,
  dose_mg        FLOAT64,
  frequency      STRING,                                      -- 'daily' | 'twice_daily' | 'as_needed' ...
  is_supplement  BOOL DEFAULT FALSE,
  source         STRING,                                      -- 'ocr_receipt' | 'manual' | 'pharmacy_api'
  logged_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `caresignal.vitals_log` (
  event_id      STRING NOT NULL,
  subject_id    STRING NOT NULL,
  caregiver_id  STRING,
  metric        STRING NOT NULL,                               -- 'bp_systolic' | 'bp_diastolic' | 'glucose'
  value         FLOAT64 NOT NULL,
  unit          STRING,
  source        STRING,                                        -- 'ble_monitor' | 'manual'
  logged_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `caresignal.meal_log` (
  event_id      STRING NOT NULL,
  subject_id    STRING NOT NULL,
  caregiver_id  STRING,
  meal          STRING,                                        -- 'breakfast' | 'lunch' | 'dinner'
  status        STRING,                                        -- 'eaten' | 'skipped' | 'partial'
  note          STRING,
  logged_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `caresignal.notes_log` (
  event_id      STRING NOT NULL,
  subject_id    STRING NOT NULL,
  caregiver_id  STRING,
  text          STRING,
  source        STRING,                                        -- 'manual' | 'group_chat_import'
  logged_at     TIMESTAMP NOT NULL
);

-- ---------------------------------------------------------------------
-- Decision-engine output: the trust layer
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `caresignal.risk_alerts` (
  alert_id       STRING NOT NULL,
  subject_id     STRING NOT NULL,
  rule_id        STRING NOT NULL,                              -- e.g. 'drug_supplement_interaction'
  severity       STRING NOT NULL,                              -- 'urgent' | 'watch' | 'monitor'
  score          FLOAT64,
  title          STRING NOT NULL,                              -- Gemini-generated, plain language
  explanation    STRING NOT NULL,                               -- Gemini-generated, plain language
  suggested_action STRING,
  created_at     TIMESTAMP NOT NULL,
  scoring_latency_ms INT64                                     -- proves the acceleration claim
);

CREATE TABLE IF NOT EXISTS `caresignal.audit_trail` (
  audit_id       STRING NOT NULL,
  alert_id       STRING NOT NULL,                              -- FK -> risk_alerts.alert_id
  source_table   STRING NOT NULL,                              -- 'meds_log' | 'vitals_log' | ...
  source_event_id STRING NOT NULL,                             -- FK -> the raw event row that triggered this
  rule_detail    STRING,                                       -- human-readable clause, e.g. threshold crossed
  created_at     TIMESTAMP NOT NULL
);

-- ---------------------------------------------------------------------
-- Example: BigQuery ML model for the "watch"-tier trend severity score
-- (the rule engine below handles hard clinical rules; this model only
--  scores the *soft* signal — how anomalous a trend is — so it augments
--  rather than replaces the auditable rule logic.)
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE MODEL `caresignal.vitals_trend_anomaly`
-- OPTIONS(model_type='ARIMA_PLUS', time_series_timestamp_col='logged_at',
--         time_series_data_col='value', time_series_id_col='subject_id') AS
-- SELECT subject_id, logged_at, value
-- FROM `caresignal.vitals_log`
-- WHERE metric = 'bp_systolic';
