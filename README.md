# Fish Finder Outdoors — Phase 6.3

Phase 6.3 adds a simple email-based angler report workflow without Supabase, accounts, API keys or a form service.

## Visitor workflow
1. The angler completes `submit-report.html`.
2. Their email application opens a report addressed to `mountain.dog.enterprises@gmail.com`.
3. They press Send.
4. The report arrives as a structured email.

## Approval workflow
1. Open the email and copy its complete body.
2. Open `/admin.html`.
3. Paste it under **Add an emailed angler report**.
4. Parse and review it.
5. Click **Approve and download community_fishing_reports.js**.
6. Replace only that file in the root of GitHub and commit to `main`.

Private contact information is removed automatically from the public file. Community reports are clearly labeled as manually reviewed, not independently verified.

Do not touch `.github/workflows/update-fishing-reports.yml`. The workflow does not edit the separate community report file.
