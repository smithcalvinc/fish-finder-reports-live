# Fish Finder Outdoors Report Generator — Phase 6

Phase 6 adds automatic source monitoring, freshness warnings, a review dashboard and a safe angler-submission intake system.

## What works immediately after uploading the root files

- Visible current / aging / stale labels
- Source-health status on each matched fishing report
- Warnings when a report is old
- `admin.html` review dashboard
- `submit-report.html` intake form
- Local submission review and JSON export
- Optional public webhook support through `site_config.js`

## What the automatic monitor does

The daily checker:

1. Opens each unique official report source.
2. Saves a fingerprint of the visible page content.
3. Updates the last-checked time, HTTP status and freshness age.
4. Flags a report when the official page changes.
5. Flags unreachable sources.
6. Commits the new status files to GitHub, which triggers the connected Wasmer deployment.

It does **not** rewrite catch totals from unstructured webpage text. Changed pages go to the review queue instead, preventing inaccurate fishing claims from being published automatically.

## Upload these root files

Replace/add these files in the repository root:

- `index.html`
- `official_species_data.js`
- `recent_fishing_reports.js`
- `update_status.js`
- `source_check_log.json`
- `site_config.js`
- `update_reports.py`
- `submit-report.html`
- `admin.html`
- `404.html`
- `README.md`

## Enable the scheduled GitHub workflow

GitHub Actions requires this exact repository path:

`.github/workflows/update-fishing-reports.yml`

The ZIP includes that folder and file. The easiest method is GitHub Desktop, which preserves folders.

When using the GitHub website:

1. Open the repository.
2. Choose **Add file → Create new file**.
3. In the filename field, enter:
   `.github/workflows/update-fishing-reports.yml`
4. Open `WORKFLOW_TO_COPY.yml` from this package.
5. Paste all of its contents into the GitHub editor.
6. Commit the new file to `main`.
7. Open the repository’s **Actions** tab.
8. Select **Update Fishing Report Sources**.
9. Choose **Run workflow** once to create the first live source baseline.

The workflow then runs daily. GitHub may delay scheduled workflows during periods of high load.

## Repository permissions

If the workflow can check sources but cannot commit:

1. Open repository **Settings → Actions → General**.
2. Find **Workflow permissions**.
3. Select **Read and write permissions**.
4. Save.

## Public submissions

The included form works in local draft/export mode without a backend. To receive public submissions automatically, edit `site_config.js` and add a public JSON form/webhook endpoint to `submission_endpoint`.

Never place private API keys or passwords in `site_config.js`.
