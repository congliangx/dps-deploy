-- This runs only during first initialization of an empty PGDATA.
-- Read the application password from a file, without a CLI argument or SQL log.
\set dps_password `cat /run/secrets/dps-password`
CREATE ROLE dps WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'dps_password';
CREATE DATABASE dps OWNER dps;
REVOKE ALL ON DATABASE dps FROM PUBLIC;
GRANT CONNECT ON DATABASE dps TO dps;
\connect dps
ALTER SCHEMA public OWNER TO dps;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO dps;
