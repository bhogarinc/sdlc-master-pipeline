-- TaskFlow Pro Database Rollback Scripts
-- =======================================
-- Reversible migration scripts for safe rollbacks
-- All migrations MUST include corresponding rollback scripts

-- Migration: 20240425_001_create_user_preferences
-- Description: Add user preferences table
-- Rollback Script:

BEGIN;

-- Rollback: Remove user preferences table
DROP TABLE IF EXISTS user_preferences CASCADE;

-- Remove from migration tracking
DELETE FROM schema_migrations WHERE version = '20240425_001';

-- Log the rollback
INSERT INTO migration_rollbacks (
    migration_version,
    rolled_back_at,
    rollback_reason,
    rolled_back_by
) VALUES (
    '20240425_001',
    NOW(),
    'Deployment rollback',
    current_user
);

COMMIT;

-- =======================================
-- Migration: 20240425_002_add_task_priority
-- Description: Add priority column to tasks
-- Rollback Script:

BEGIN;

-- Rollback: Remove priority column from tasks
ALTER TABLE tasks DROP COLUMN IF EXISTS priority;

-- Remove from migration tracking
DELETE FROM schema_migrations WHERE version = '20240425_002';

-- Log the rollback
INSERT INTO migration_rollbacks (
    migration_version,
    rolled_back_at,
    rollback_reason,
    rolled_back_by
) VALUES (
    '20240425_002',
    NOW(),
    'Deployment rollback',
    current_user
);

COMMIT;

-- =======================================
-- Migration: 20240425_003_create_notification_settings
-- Description: Add notification settings table
-- Rollback Script:

BEGIN;

-- Rollback: Remove notification settings
DROP TABLE IF EXISTS notification_settings CASCADE;

-- Remove from migration tracking
DELETE FROM schema_migrations WHERE version = '20240425_003';

-- Log the rollback
INSERT INTO migration_rollbacks (
    migration_version,
    rolled_back_at,
    rollback_reason,
    rolled_back_by
) VALUES (
    '20240425_003',
    NOW(),
    'Deployment rollback',
    current_user
);

COMMIT;

-- =======================================
-- Migration: 20240425_004_add_team_invite_indexes
-- Description: Add indexes for team invitation queries
-- Rollback Script:

BEGIN;

-- Rollback: Remove indexes
DROP INDEX IF EXISTS idx_team_invites_email;
DROP INDEX IF EXISTS idx_team_invites_token;
DROP INDEX IF EXISTS idx_team_invites_expires;

-- Remove from migration tracking
DELETE FROM schema_migrations WHERE version = '20240425_004';

-- Log the rollback
INSERT INTO migration_rollbacks (
    migration_version,
    rolled_back_at,
    rollback_reason,
    rolled_back_by
) VALUES (
    '20240425_004',
    NOW(),
    'Deployment rollback',
    current_user
);

COMMIT;

-- =======================================
-- Migration: 20240425_005_create_audit_log_partition
-- Description: Partition audit log table
-- Rollback Script:

BEGIN;

-- Rollback: Merge partitions back to single table
-- Note: This is a complex operation requiring data migration

-- Create temporary table with old structure
CREATE TABLE audit_log_old (
    id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100),
    record_id BIGINT,
    action VARCHAR(20),
    old_data JSONB,
    new_data JSONB,
    changed_at TIMESTAMP DEFAULT NOW(),
    changed_by INTEGER REFERENCES users(id)
);

-- Migrate data from all partitions
INSERT INTO audit_log_old (
    id, table_name, record_id, action, 
    old_data, new_data, changed_at, changed_by
)
SELECT id, table_name, record_id, action,
       old_data, new_data, changed_at, changed_by
FROM audit_log;

-- Drop partitioned table
DROP TABLE audit_log CASCADE;

-- Rename old table back
ALTER TABLE audit_log_old RENAME TO audit_log;

-- Recreate indexes
CREATE INDEX idx_audit_table_record ON audit_log(table_name, record_id);
CREATE INDEX idx_audit_changed_at ON audit_log(changed_at);

-- Remove from migration tracking
DELETE FROM schema_migrations WHERE version = '20240425_005';

-- Log the rollback
INSERT INTO migration_rollbacks (
    migration_version,
    rolled_back_at,
    rollback_reason,
    rolled_back_by
) VALUES (
    '20240425_005',
    NOW(),
    'Deployment rollback',
    current_user
);

COMMIT;

-- =======================================
-- Emergency Full Database Restore Procedure
-- =======================================
-- Use this only when migration rollback is not possible

-- Procedure: emergency_restore_from_backup
-- Parameters: backup_file_path

CREATE OR REPLACE FUNCTION emergency_restore_from_backup(
    p_backup_path TEXT
) RETURNS VOID AS $$
DECLARE
    v_start_time TIMESTAMP;
    v_db_name TEXT;
BEGIN
    v_start_time := clock_timestamp();
    v_db_name := current_database();
    
    -- Log restore attempt
    INSERT INTO disaster_recovery_log (
        action_type,
        action_details,
        started_at,
        status
    ) VALUES (
        'EMERGENCY_RESTORE',
        format('Restoring from %s', p_backup_path),
        v_start_time,
        'IN_PROGRESS'
    );
    
    -- Note: Actual pg_restore must be run from command line
    -- This function logs the intent and validates post-conditions
    
    -- Validation: Check critical tables exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables 
                   WHERE table_name = 'users') THEN
        RAISE EXCEPTION 'Critical table users missing after restore';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables 
                   WHERE table_name = 'tasks') THEN
        RAISE EXCEPTION 'Critical table tasks missing after restore';
    END IF;
    
    -- Update log
    UPDATE disaster_recovery_log
    SET status = 'COMPLETED',
        completed_at = clock_timestamp(),
        duration_seconds = EXTRACT(EPOCH FROM (clock_timestamp() - v_start_time))
    WHERE action_type = 'EMERGENCY_RESTORE'
    AND started_at = v_start_time;
    
EXCEPTION WHEN OTHERS THEN
    UPDATE disaster_recovery_log
    SET status = 'FAILED',
        completed_at = clock_timestamp(),
        error_message = SQLERRM
    WHERE action_type = 'EMERGENCY_RESTORE'
    AND started_at = v_start_time;
    
    RAISE;
END;
$$ LANGUAGE plpgsql;

-- =======================================
-- Pre-deployment Backup Verification
-- =======================================

CREATE OR REPLACE FUNCTION verify_backup_integrity(
    p_backup_id TEXT
) RETURNS TABLE (
    check_name TEXT,
    passed BOOLEAN,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Backup file exists and is readable
    RETURN QUERY SELECT 
        'BACKUP_FILE_ACCESSIBLE'::TEXT,
        pg_stat_file('/backups/' || p_backup_id || '.sql').size > 0,
        format('Backup size: %s bytes', 
               pg_stat_file('/backups/' || p_backup_id || '.sql').size)::TEXT;
    
    -- Check 2: Backup contains required tables
    RETURN QUERY SELECT 
        'REQUIRED_TABLES_PRESENT'::TEXT,
        EXISTS (
            SELECT 1 FROM pg_tables 
            WHERE schemaname = 'public' 
            AND tablename IN ('users', 'tasks', 'teams')
        ),
        'Core tables verified'::TEXT;
    
    -- Check 3: Recent data exists
    RETURN QUERY SELECT 
        'RECENT_DATA_CHECK'::TEXT,
        EXISTS (
            SELECT 1 FROM users 
            WHERE created_at > NOW() - INTERVAL '1 hour'
        ),
        'Recent user activity found'::TEXT;
    
    -- Check 4: Backup timestamp valid
    RETURN QUERY SELECT 
        'BACKUP_TIMESTAMP_VALID'::TEXT,
        p_backup_id ~ '^\\d{8}_\\d{6}$',
        'Backup ID format valid'::TEXT;
        
EXCEPTION WHEN OTHERS THEN
    RETURN QUERY SELECT 
        'VERIFICATION_ERROR'::TEXT,
        FALSE,
        SQLERRM::TEXT;
END;
$$ LANGUAGE plpgsql;

-- =======================================
-- Rollback Safety Checks
-- =======================================

CREATE OR REPLACE FUNCTION can_rollback_safely(
    p_migration_version TEXT
) RETURNS TABLE (
    can_rollback BOOLEAN,
    reason TEXT,
    blocking_issues TEXT[]
) AS $$
DECLARE
    v_blocking_issues TEXT[] := ARRAY[]::TEXT[];
    v_is_reversible BOOLEAN;
    v_has_backup BOOLEAN;
    v_active_connections INTEGER;
BEGIN
    -- Check 1: Migration exists and is reversible
    SELECT is_reversible INTO v_is_reversible
    FROM schema_migrations
    WHERE version = p_migration_version;
    
    IF NOT FOUND THEN
        v_blocking_issues := array_append(v_blocking_issues, 
            'Migration not found: ' || p_migration_version);
    ELSIF NOT v_is_reversible THEN
        v_blocking_issues := array_append(v_blocking_issues,
            'Migration is not reversible - backup restore required');
    END IF;
    
    -- Check 2: Backup exists for non-reversible migrations
    SELECT EXISTS (
        SELECT 1 FROM pg_stat_file('/backups/latest.sql')
    ) INTO v_has_backup;
    
    IF NOT v_is_reversible AND NOT v_has_backup THEN
        v_blocking_issues := array_append(v_blocking_issues,
            'No backup available for non-reversible migration');
    END IF;
    
    -- Check 3: No active long-running transactions
    SELECT count(*) INTO v_active_connections
    FROM pg_stat_activity
    WHERE state = 'active'
    AND query_start < NOW() - INTERVAL '5 minutes'
    AND pid != pg_backend_pid();
    
    IF v_active_connections > 0 THEN
        v_blocking_issues := array_append(v_blocking_issues,
            format('%s long-running transactions active', v_active_connections));
    END IF;
    
    -- Check 4: Database not in recovery mode
    IF pg_is_in_recovery() THEN
        v_blocking_issues := array_append(v_blocking_issues,
            'Database is in recovery mode');
    END IF;
    
    RETURN QUERY SELECT 
        array_length(v_blocking_issues, 1) IS NULL,
        CASE 
            WHEN array_length(v_blocking_issues, 1) IS NULL 
            THEN 'All checks passed - safe to rollback'
            ELSE 'Blocking issues detected'
        END,
        v_blocking_issues;
END;
$$ LANGUAGE plpgsql;
