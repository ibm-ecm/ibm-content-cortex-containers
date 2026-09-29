-- *****************************************************************
-- IBM Content Cortex Model Gateway preparation script for PostgreSQL
-- *****************************************************************
-- Usage:
-- Use psql command-line processor to execute the template file using -f option
-- and a user with administrative privileges (e.g. postgres superuser):
-- psql -h 127.0.0.1 -U postgres -f ./createModelGatewayDB.sql

-- Create user ${youruser1} if it does not exist
DO
$$body$$
BEGIN
  IF NOT EXISTS (
    SELECT FROM pg_catalog.pg_user WHERE usename = '${youruser1}'
  ) THEN
    CREATE USER ${youruser1};
  END IF;
END
$$body$$;

-- Set password for ${youruser1}
ALTER USER ${youruser1} WITH ENCRYPTED PASSWORD '${yourpassword}';

-- Create Model Gateway database
CREATE DATABASE ${mg_name};

-- Grant privileges on database ${mg_name}
GRANT CONNECT ON DATABASE ${mg_name} TO public;
ALTER DATABASE ${mg_name} OWNER TO ${youruser1};
GRANT ALL PRIVILEGES ON DATABASE ${mg_name} TO ${youruser1};

-- Set timezone for database ${mg_name}
ALTER DATABASE ${mg_name} SET timezone TO 'Etc/UTC';
