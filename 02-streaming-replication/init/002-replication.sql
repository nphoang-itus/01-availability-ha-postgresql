CREATE ROLE replicator
    WITH REPLICATION LOGIN
    PASSWORD 'lab_replication_password';

SELECT pg_create_physical_replication_slot('pg02');
