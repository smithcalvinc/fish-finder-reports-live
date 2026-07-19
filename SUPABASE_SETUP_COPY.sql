-- Fish Finder Outdoors Phase 7
-- Run this entire file once in Supabase: SQL Editor → New query → Run.
-- Then create your admin user in Authentication → Users and run the final
-- admin insert statement after replacing the email placeholder.

create extension if not exists pgcrypto;

create table if not exists public.admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text,
  created_at timestamptz not null default now()
);

create table if not exists public.angler_reports (
  id uuid primary key default gen_random_uuid(),
  submitted_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'rejected')),

  waterbody text not null check (char_length(waterbody) between 2 and 140),
  state text not null check (char_length(state) between 2 and 60),
  fishing_date date not null,
  time_period text,
  species text not null check (char_length(species) between 2 and 160),
  caught_count integer not null default 0 check (caught_count between 0 and 999),
  kept_count integer not null default 0 check (kept_count between 0 and 999),
  size_text text,
  bait_or_lure text not null check (char_length(bait_or_lure) between 2 and 240),
  method text,
  notes text,
  photo_url text,
  display_name text,
  latitude numeric(9,6),
  longitude numeric(9,6),

  reviewer_notes text,
  approved_at timestamptz,
  reviewed_by uuid references auth.users(id),
  source_label text not null default 'Angler submission'
);

create table if not exists public.angler_report_contacts (
  report_id uuid primary key references public.angler_reports(id) on delete cascade,
  private_contact text,
  created_at timestamptz not null default now()
);

create index if not exists angler_reports_status_date_idx
  on public.angler_reports(status, fishing_date desc);

create index if not exists angler_reports_state_water_idx
  on public.angler_reports(state, waterbody);

alter table public.admin_users enable row level security;
alter table public.angler_reports enable row level security;
alter table public.angler_report_contacts enable row level security;

create or replace function public.is_ffo_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.admin_users
    where user_id = (select auth.uid())
  );
$$;

revoke all on function public.is_ffo_admin() from public;
grant execute on function public.is_ffo_admin() to anon, authenticated;

drop policy if exists "Approved reports are public" on public.angler_reports;
create policy "Approved reports are public"
on public.angler_reports
for select
to anon
using (status = 'approved');

drop policy if exists "Authenticated users see approved reports" on public.angler_reports;
create policy "Authenticated users see approved reports"
on public.angler_reports
for select
to authenticated
using (status = 'approved' or (select public.is_ffo_admin()));

drop policy if exists "Admins update reports" on public.angler_reports;
create policy "Admins update reports"
on public.angler_reports
for update
to authenticated
using ((select public.is_ffo_admin()))
with check ((select public.is_ffo_admin()));

drop policy if exists "Admins delete reports" on public.angler_reports;
create policy "Admins delete reports"
on public.angler_reports
for delete
to authenticated
using ((select public.is_ffo_admin()));

drop policy if exists "Admins read admin users" on public.admin_users;
create policy "Admins read admin users"
on public.admin_users
for select
to authenticated
using ((select public.is_ffo_admin()));

drop policy if exists "Admins manage contacts" on public.angler_report_contacts;
create policy "Admins manage contacts"
on public.angler_report_contacts
for all
to authenticated
using ((select public.is_ffo_admin()))
with check ((select public.is_ffo_admin()));

revoke all on public.admin_users from anon, authenticated;
revoke all on public.angler_reports from anon, authenticated;
revoke all on public.angler_report_contacts from anon, authenticated;

grant select on public.angler_reports to anon;
grant select, update, delete on public.angler_reports to authenticated;
grant select on public.admin_users to authenticated;
grant select, update, delete on public.angler_report_contacts to authenticated;

create or replace function public.submit_angler_report(
  p_waterbody text,
  p_state text,
  p_fishing_date date,
  p_time_period text,
  p_species text,
  p_caught_count integer,
  p_kept_count integer,
  p_size_text text,
  p_bait_or_lure text,
  p_method text,
  p_notes text,
  p_photo_url text,
  p_display_name text,
  p_private_contact text,
  p_latitude numeric default null,
  p_longitude numeric default null
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  new_id uuid;
begin
  if char_length(trim(coalesce(p_waterbody, ''))) < 2 then
    raise exception 'Waterbody is required';
  end if;
  if char_length(trim(coalesce(p_state, ''))) < 2 then
    raise exception 'State is required';
  end if;
  if p_fishing_date is null or p_fishing_date > current_date then
    raise exception 'Fishing date is invalid';
  end if;
  if p_fishing_date < current_date - interval '180 days' then
    raise exception 'Reports must be from the last 180 days';
  end if;
  if char_length(trim(coalesce(p_species, ''))) < 2 then
    raise exception 'Species is required';
  end if;
  if char_length(trim(coalesce(p_bait_or_lure, ''))) < 2 then
    raise exception 'Bait or lure is required';
  end if;
  if coalesce(p_caught_count, 0) < 0 or coalesce(p_caught_count, 0) > 999 then
    raise exception 'Caught count is invalid';
  end if;
  if coalesce(p_kept_count, 0) < 0 or coalesce(p_kept_count, 0) > coalesce(p_caught_count, 0) then
    raise exception 'Kept count cannot exceed caught count';
  end if;
  if p_latitude is not null and (p_latitude < -90 or p_latitude > 90) then
    raise exception 'Latitude is invalid';
  end if;
  if p_longitude is not null and (p_longitude < -180 or p_longitude > 180) then
    raise exception 'Longitude is invalid';
  end if;

  insert into public.angler_reports (
    status, waterbody, state, fishing_date, time_period, species,
    caught_count, kept_count, size_text, bait_or_lure, method,
    notes, photo_url, display_name, latitude, longitude
  )
  values (
    'pending',
    left(trim(p_waterbody), 140),
    left(trim(p_state), 60),
    p_fishing_date,
    left(trim(coalesce(p_time_period, '')), 60),
    left(trim(p_species), 160),
    coalesce(p_caught_count, 0),
    coalesce(p_kept_count, 0),
    left(trim(coalesce(p_size_text, '')), 100),
    left(trim(p_bait_or_lure), 240),
    left(trim(coalesce(p_method, '')), 80),
    left(trim(coalesce(p_notes, '')), 2000),
    left(trim(coalesce(p_photo_url, '')), 500),
    left(trim(coalesce(p_display_name, 'Anonymous angler')), 100),
    p_latitude,
    p_longitude
  )
  returning id into new_id;

  if char_length(trim(coalesce(p_private_contact, ''))) > 0 then
    insert into public.angler_report_contacts(report_id, private_contact)
    values (new_id, left(trim(p_private_contact), 240));
  end if;

  return new_id;
end;
$$;

revoke all on function public.submit_angler_report(
  text, text, date, text, text, integer, integer, text,
  text, text, text, text, text, text, numeric, numeric
) from public;

grant execute on function public.submit_angler_report(
  text, text, date, text, text, integer, integer, text,
  text, text, text, text, text, text, numeric, numeric
) to anon, authenticated;

create or replace function public.set_angler_report_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists angler_reports_updated_at on public.angler_reports;
create trigger angler_reports_updated_at
before update on public.angler_reports
for each row execute function public.set_angler_report_updated_at();

-- ---------------------------------------------------------------
-- CREATE YOUR ADMIN USER
-- 1. Supabase Dashboard → Authentication → Users → Add user.
-- 2. Give the user an email and password.
-- 3. Replace the email below and run ONLY this statement.
-- ---------------------------------------------------------------
-- insert into public.admin_users(user_id, email)
-- select id, email from auth.users
-- where lower(email) = lower('YOUR-ADMIN-EMAIL@example.com')
-- on conflict (user_id) do update set email = excluded.email;
