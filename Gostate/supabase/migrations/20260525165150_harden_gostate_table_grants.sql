revoke all privileges on table public.users from anon;
revoke all privileges on table public.users from authenticated;
revoke all privileges on table public.users from service_role;

revoke all privileges on table public.context_states from anon;
revoke all privileges on table public.context_states from authenticated;
revoke all privileges on table public.context_states from service_role;

grant select, update on table public.users to authenticated;
grant select, insert, update on table public.context_states to authenticated;

grant select, insert, update, delete on table public.users to service_role;
grant select, insert, update, delete on table public.context_states to service_role;
