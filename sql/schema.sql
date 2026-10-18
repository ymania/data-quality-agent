-- 用有建库权限的 MySQL 8 用户执行；此脚本可重复执行且不会清除历史结果。
CREATE DATABASE IF NOT EXISTS data_quality_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE data_quality_agent;

CREATE TABLE IF NOT EXISTS demo_orders (
  order_id BIGINT PRIMARY KEY,
  customer_name VARCHAR(255) NULL,
  order_status VARCHAR(32) NULL,
  amount DECIMAL(10,2) NOT NULL,
  created_at DATETIME NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS demo_empty_orders LIKE demo_orders;
CREATE TABLE IF NOT EXISTS demo_null_orders LIKE demo_orders;
CREATE TABLE IF NOT EXISTS demo_orders_faker LIKE demo_orders;

CREATE TABLE IF NOT EXISTS data_imports (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  source_type VARCHAR(8) NOT NULL,
  sha256 CHAR(64) NOT NULL,
  row_count INT NOT NULL,
  created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_import_content (source_type, sha256)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS uploaded_orders (
  dataset_id BIGINT NOT NULL,
  order_id BIGINT NOT NULL,
  customer_name VARCHAR(255) NULL,
  order_status VARCHAR(32) NULL,
  amount DECIMAL(10,2) NULL,
  created_at DATETIME NULL,
  PRIMARY KEY (dataset_id, order_id),
  FOREIGN KEY (dataset_id) REFERENCES data_imports(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS quality_rules (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  table_name VARCHAR(64) NOT NULL,
  column_name VARCHAR(64) NOT NULL,
  rule_type ENUM('NOT_NULL','ENUM') NOT NULL,
  params_json JSON NOT NULL,
  created_session_id VARCHAR(64) NULL,
  dataset_id BIGINT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_rules_session (created_session_id, id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS quality_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  rule_id BIGINT NOT NULL,
  session_id VARCHAR(64) NULL,
  executed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  status ENUM('RUNNING','SUCCEEDED','FAILED') NOT NULL,
  rule_snapshot_json JSON NOT NULL,
  total_count BIGINT NULL,
  checked_count BIGINT NULL,
  passed_count BIGINT NULL,
  failed_count BIGINT NULL,
  skipped_count BIGINT NULL,
  pass_rate DECIMAL(5,2) NULL,
  samples_json JSON NULL,
  error_text TEXT NULL,
  CONSTRAINT fk_run_rule FOREIGN KEY (rule_id) REFERENCES quality_rules(id),
  INDEX idx_runs_rule (rule_id, id),
  INDEX idx_runs_session (session_id, id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  role ENUM('user','assistant') NOT NULL,
  content TEXT NOT NULL,
  trace_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_chat_session (session_id, id)
) ENGINE=InnoDB;
