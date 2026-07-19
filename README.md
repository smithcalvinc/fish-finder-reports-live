# Fish Finder Outdoors Report Generator — Phase 7

Phase 7 converts the local-only submission system into a real shared database and private administration system.

## New capabilities

- Public submissions from any phone or computer
- One shared pending-review queue
- Private administrator email/password login
- Edit submissions before publication
- Approve and publish immediately
- Reject or permanently delete submissions
- Public display of approved angler reports on matching waterbody reports
- Private contact details stored in a separate protected table
- Existing official-source monitoring remains active

## Backend

Phase 7 uses Supabase Auth and Postgres. The browser uses only the project URL and publishable key. Database Row Level Security controls access.

Never put a Supabase secret key or service-role key in the website.

## Setup

Follow `PHASE_7_SETUP.txt`.

The two main setup files are:

- `SUPABASE_SETUP_COPY.sql`
- `site_config.js`

## Main public pages

- `/index.html` — report generator and approved community reports
- `/submit-report.html` — public submission form
- `/admin.html` — private login, review, editing and publishing

## Files to upload

Upload all files from this package to the existing GitHub repository, including:

- `index.html`
- `admin.html`
- `submit-report.html`
- `site_config.js`
- `supabase_client.js`
- `supabase_setup.sql`
- `SUPABASE_SETUP_COPY.sql`
- `PHASE_7_SETUP.txt`
- all existing Phase 6 data, status and workflow files
