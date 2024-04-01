SET TIMEZONE TO 'PRC';


-- 创建表时额外创建审计历史表，并添加时间戳列，同时为表创建历史数据迁移触发器
CREATE OR REPLACE FUNCTION create_audit_with_timestamp()
RETURNS event_trigger AS $$
DECLARE
    audit_ddl TEXT;
    alter_query TEXT;
    r RECORD;
BEGIN
    IF tg_tag = 'CREATE TABLE'
    THEN
        FOR r IN SELECT * FROM pg_event_trigger_ddl_commands()
        LOOP       
            IF r.object_type = 'table'
            THEN
                -- 临时禁用触发器防止创建表事件递归
                EXECUTE 'SET session_replication_role = replica;';
                -- 添加时间戳列并设置默认值，即插入时间
                EXECUTE format('ALTER TABLE %s ADD __modified_at TIMESTAMP WITH TIME ZONE;',
                               r.object_identity);
                EXECUTE format('ALTER TABLE %s ALTER COLUMN __modified_at SET DEFAULT now()::timestamptz(0);',
                               r.object_identity);
                -- 创建审计历史表
                EXECUTE format('CREATE TABLE %s_audit (LIKE %s INCLUDING ALL);',
                               r.object_identity, r.object_identity);
                -- 删除主键约束
                EXECUTE format('ALTER TABLE %s_audit DROP CONSTRAINT IF EXISTS %s_audit_pkey;',
                               r.object_identity, SPLIT_PART(r.object_identity, '.', 2));
                -- 启用触发器
                EXECUTE 'SET session_replication_role = DEFAULT;';
            END IF;
       END LOOP;
    END IF;
END;
$$
LANGUAGE plpgsql;

-- 创建表事件触发器
DROP EVENT TRIGGER IF EXISTS create_audit_with_timestamp;
CREATE EVENT TRIGGER
create_audit_with_timestamp ON ddl_command_end
WHEN TAG IN ('CREATE TABLE')
EXECUTE PROCEDURE create_audit_with_timestamp();


-- 删除表时同时删除审计历史表与触发器函数
CREATE OR REPLACE FUNCTION trg_drop_dependent_functions()
RETURNS event_trigger AS $$
DECLARE
    dropped record;
BEGIN
    FOR dropped IN
        SELECT schema_name, object_name
        FROM pg_catalog.pg_event_trigger_dropped_objects()
        WHERE object_type = 'table'
    LOOP
        IF dropped.schema_name = 'public' THEN
            -- 临时禁用触发器防止删除表事件递归
            EXECUTE 'SET session_replication_role = replica;';
            -- 删除该表对应的审计历史表
            EXECUTE format('DROP TABLE IF EXISTS %s_audit;', dropped.object_name);
            -- 启用触发器
            EXECUTE 'SET session_replication_role = DEFAULT;';
        END IF;
    END LOOP;
END;
$$
LANGUAGE plpgsql;

-- 删除表事件触发器
DROP EVENT TRIGGER IF EXISTS trg_drop_dependent_functions;
CREATE EVENT TRIGGER trg_drop_dependent_functions ON sql_drop
EXECUTE FUNCTION trg_drop_dependent_functions();
