-- *****************************************************************
-- IBM Content Cortex WDU (Enhanced Extraction) preparation script for PostgreSQL
-- *****************************************************************
-- Usage:
-- Use psql command-line processor to execute the template file using -f option
-- and a user with administrative privileges (e.g. postgres superuser):
-- psql -h 127.0.0.1 -U postgres -f ./createWDUDB.sql

CREATE ROLE ${youruser1} WITH INHERIT LOGIN ENCRYPTED PASSWORD '${yourpassword}';

-- please modify location follow your requirement
create tablespace ${wdu_name}_tbs owner ${youruser1} location '/pgsqldata/${wdu_name}';
grant create on tablespace ${wdu_name}_tbs to ${youruser1};

-- create database ${wdu_name}
create database ${wdu_name} owner ${youruser1} tablespace ${wdu_name}_tbs template template0 encoding UTF8 ;
revoke connect on database ${wdu_name} from public;
grant all privileges on database ${wdu_name} to ${youruser1};
grant connect, temp, create on database ${wdu_name} to ${youruser1};

-- create a schema for ${wdu_name} and set the default
-- connect to the respective database before executing the below commands
\connect ${wdu_name};
CREATE SCHEMA IF NOT EXISTS AUTHORIZATION ${youruser1};
SET ROLE ${youruser1};
ALTER DATABASE ${wdu_name} SET search_path TO ${youruser1};
