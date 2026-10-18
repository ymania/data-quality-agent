-- 可选：由 MySQL 管理员执行。修改密码后同步修改 .env。
CREATE USER IF NOT EXISTS 'dq_app'@'127.0.0.1' IDENTIFIED BY 'change-me';
GRANT SELECT, INSERT, UPDATE, DELETE ON data_quality_agent.* TO 'dq_app'@'127.0.0.1';
