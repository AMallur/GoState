create extension if not exists pgcrypto with schema extensions;

create table if not exists public.users (
    user_id uuid primary key,
    tenant_id uuid not null,
    email varchar(320) not null unique,
    display_name varchar(128),
    role varchar(32) not null check (role in ('admin', 'operator', 'auditor', 'service')),
    password_hash varchar(255) not null,
    is_active boolean not null default true,
    is_locked boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    last_authenticated_at timestamptz,
    constraint users_locked_inactive check (not (is_locked and is_active)),
    constraint users_updated_after_created check (updated_at >= created_at),
    constraint users_last_auth_after_created check (
        last_authenticated_at is null or last_authenticated_at >= created_at
    )
);

create table if not exists public.context_states (
    state_id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references public.users(user_id) on delete restrict,
    tenant_id uuid not null,
    workspace_id varchar(128) not null,
    captured_at timestamptz not null default now(),
    status varchar(32) not null check (status in ('captured', 'restored', 'expired')),
    payload jsonb not null,
    expires_at timestamptz,
    constraint context_states_expires_after_capture check (
        expires_at is null or expires_at > captured_at
    )
);

create index if not exists users_user_id_is_active_idx
    on public.users using btree (user_id, is_active);

create index if not exists users_tenant_id_idx
    on public.users using btree (tenant_id);

create index if not exists context_states_owner_user_id_idx
    on public.context_states using btree (owner_user_id);

create index if not exists context_states_tenant_workspace_idx
    on public.context_states using btree (tenant_id, workspace_id);

create index if not exists context_states_payload_gin_idx
    on public.context_states using gin (payload jsonb_path_ops);

alter table public.users enable row level security;
alter table public.context_states enable row level security;

create policy users_select_own_identity
    on public.users
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

create policy users_update_own_identity
    on public.users
    for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy context_states_select_own
    on public.context_states
    for select
    to authenticated
    using ((select auth.uid()) = owner_user_id);

create policy context_states_insert_own
    on public.context_states
    for insert
    to authenticated
    with check ((select auth.uid()) = owner_user_id);

create policy context_states_update_own
    on public.context_states
    for update
    to authenticated
    using ((select auth.uid()) = owner_user_id)
    with check ((select auth.uid()) = owner_user_id);

grant select, update on public.users to authenticated;
grant select, insert, update on public.context_states to authenticated;
grant select, insert, update, delete on public.users to service_role;
grant select, insert, update, delete on public.context_states to service_role;
