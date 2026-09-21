-- Destructive migration: permanently remove legacy network-analysis tables.
-- Back up the database before running this file. This migration is never
-- executed by AgentGuard startup or automated tests.
--
-- Example backup:
--   pg_dump "$DATABASE_URL" > before-agentguard-only.sql
-- Apply explicitly:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f deploy/migrations/drop_network_analysis_tables.sql

BEGIN;

DROP TABLE IF EXISTS long_ttp_short_ttps CASCADE;
DROP TABLE IF EXISTS long_ttp_events CASCADE;
DROP TABLE IF EXISTS short_ttp_events CASCADE;
DROP TABLE IF EXISTS long_ttp_generations CASCADE;
DROP TABLE IF EXISTS long_ttps CASCADE;
DROP TABLE IF EXISTS short_ttps CASCADE;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS processing_status CASCADE;
DROP TABLE IF EXISTS system_metrics CASCADE;
DROP TABLE IF EXISTS langgraph_writes CASCADE;
DROP TABLE IF EXISTS langgraph_blobs CASCADE;
DROP TABLE IF EXISTS langgraph_checkpoints CASCADE;

COMMIT;

-- Verify that only AgentGuard business tables remain:
-- SELECT table_name
-- FROM information_schema.tables
-- WHERE table_schema = 'public'
-- ORDER BY table_name;
