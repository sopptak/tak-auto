-- Keep queue state outside the Data API's public schema.
create role tak_auto_queue_runtime nologin;
create role tak_auto_queue_importer nologin;

create schema tak_auto_private;
revoke all on schema tak_auto_private from public, anon, authenticated, service_role;

create table tak_auto_private.publishing_queue (
    singleton boolean primary key default true check (singleton),
    revision bigint not null default 0 check (revision >= 0),
    -- Keep JSON numeric representations intact: they contribute to job identity.
    state json not null,
    constraint publishing_queue_state_format check (
        (json_typeof(state) = 'object'
         and json_typeof(state -> 'version') = 'number'
         and state ->> 'version' = '1'
         and json_typeof(state -> 'items') = 'array'
         and json_typeof(state -> 'history') = 'array') is true
    )
);

alter table tak_auto_private.publishing_queue enable row level security;
revoke all on table tak_auto_private.publishing_queue from public, anon, authenticated, service_role;

grant usage on schema tak_auto_private to tak_auto_queue_runtime, tak_auto_queue_importer;
grant select on tak_auto_private.publishing_queue to tak_auto_queue_runtime, tak_auto_queue_importer;
grant update (revision, state) on tak_auto_private.publishing_queue to tak_auto_queue_runtime;
grant insert (singleton, state) on tak_auto_private.publishing_queue to tak_auto_queue_importer;

create policy publishing_queue_read on tak_auto_private.publishing_queue
    for select to tak_auto_queue_runtime, tak_auto_queue_importer using (singleton);
create policy publishing_queue_update on tak_auto_private.publishing_queue
    for update to tak_auto_queue_runtime using (singleton) with check (singleton);
create policy publishing_queue_import on tak_auto_private.publishing_queue
    for insert to tak_auto_queue_importer with check (singleton and revision = 0);

-- No seed row. An operator must import a verified queue snapshot before startup.
