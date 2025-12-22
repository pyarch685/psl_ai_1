-- PostgreSQL Database User Setup Script
-- Run this as PostgreSQL superuser (postgres)

-- Create user
CREATE USER pyarch685 WITH PASSWORD 'your_password_here';

-- Grant privileges
ALTER USER pyarch685 CREATEDB;

-- Create database
CREATE DATABASE psl_db OWNER pyarch685;

-- Grant all privileges on database
GRANT ALL PRIVILEGES ON DATABASE psl_db TO pyarch685;

-- Connect to the new database and grant schema privileges
\c psl_db
GRANT ALL ON SCHEMA public TO pyarch685;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO pyarch685;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO pyarch685;

-- Show created user and database
\du pyarch685
\l psl_db
