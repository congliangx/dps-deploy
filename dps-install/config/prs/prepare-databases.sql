-- PRS / Power Steering 2.1.0 external PostgreSQL preparation.
-- Execute as postgres using the independent server. Existing DPS database is untouched.
\set ON_ERROR_STOP on
SELECT pg_advisory_lock(900921001);
DO $guard$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='dps' AND rolcanlogin
                 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole) THEN
    RAISE EXCEPTION 'Expected existing non-superuser dps application role';
  END IF;
  IF EXISTS (
    SELECT FROM pg_database
    WHERE datname IN ('dps_prs_config','dps_prs_config_staged','dps_prs_controller')
      AND pg_get_userbyid(datdba) <> 'dps'
  ) THEN
    RAISE EXCEPTION 'Existing PRS database owner differs; refusing to take ownership';
  END IF;
END $guard$;
SELECT format('CREATE DATABASE %I OWNER %I', name, 'dps')
FROM (VALUES ('dps_prs_config'),('dps_prs_config_staged'),('dps_prs_controller')) AS expected(name)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname=name)
\gexec
GRANT ALL PRIVILEGES ON DATABASE dps_prs_config TO dps;
GRANT ALL PRIVILEGES ON DATABASE dps_prs_config_staged TO dps;
GRANT ALL PRIVILEGES ON DATABASE dps_prs_controller TO dps;
REVOKE ALL PRIVILEGES ON DATABASE dps_prs_config FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE dps_prs_config_staged FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE dps_prs_controller FROM PUBLIC;
SELECT pg_advisory_unlock(900921001);
\connect dps_prs_config
GRANT USAGE, CREATE ON SCHEMA public TO dps;
\connect dps_prs_config_staged
GRANT USAGE, CREATE ON SCHEMA public TO dps;
\connect dps_prs_controller
GRANT USAGE, CREATE ON SCHEMA public TO dps;
