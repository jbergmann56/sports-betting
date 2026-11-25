-- Example least-privilege setup for gambling_model_data on Azure Database for MySQL (run as the server admin).
-- Replace host patterns and passwords; store credentials outside Git (.env / Key Vault).
-- Server parameters (Azure portal > Server parameters): require_secure_transport=ON (default),
-- log_bin_trust_function_creators=ON (needed so the migrator can create the append-only triggers).

CREATE DATABASE IF NOT EXISTS gambling_model_data CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- Schema migrations only (CREATE/ALTER/TRIGGER). Used by `python -m gambling.modeldata migrate`.
CREATE USER 'modeldata_migrator'@'%' IDENTIFIED BY '<strong-secret>' REQUIRE SSL;
GRANT CREATE, ALTER, INDEX, REFERENCES, CREATE VIEW, TRIGGER, SELECT, INSERT ON gambling_model_data.* TO 'modeldata_migrator'@'%';

-- Importers and scoring runs: append only. No UPDATE or DELETE privilege at all
-- (the triggers are a second, independent guard).
CREATE USER 'modeldata_writer'@'%' IDENTIFIED BY '<strong-secret>' REQUIRE SSL;
GRANT SELECT, INSERT ON gambling_model_data.* TO 'modeldata_writer'@'%';

-- Research (ChatGPT-side tooling) and dashboards: read only.
CREATE USER 'modeldata_reader'@'%' IDENTIFIED BY '<strong-secret>' REQUIRE SSL;
GRANT SELECT ON gambling_model_data.* TO 'modeldata_reader'@'%';

-- Account / wager data lives in a DIFFERENT database with different users, e.g. gambling_accounts.
-- None of the users above receive any privilege on it.
