# Windows Existing Deployment Update: Per-Slot Skill Management

This package updates an existing Windows deployment without replacing its data. It adds independently selectable Markdown rules for each of the 12 article-type and generation-stage slots.

## Keep These Files

Do not overwrite or delete the existing deployment directory, `.env`, `app-data`, Python virtual environments, or MySQL databases. Stop the four existing services first, then extract this package to a new directory such as `D:\geo-writing-agent-20260717`.

Copy the old configuration:

```powershell
copy D:\old-geo-writing\.env D:\geo-writing-agent-20260717\.env
```

If `APP_DATA_DIR=app-data` is a relative path, also copy the existing data directory:

```powershell
robocopy D:\old-geo-writing\app-data D:\geo-writing-agent-20260717\app-data /E
```

If `APP_DATA_DIR` is an absolute path, retain that value and do not copy the directory.

## MySQL Upgrade

Back up the writing database first. Do not run the full `backend\sql\schema.mysql.sql` against an existing database.

Run the additive Skill patch only against the writing database:

```powershell
mysql -u geo_user -p geo_writing < scripts\windows-skill-db-patch.sql
```

The backend also creates missing Skill tables at startup, but running this patch explicitly makes the database change auditable.

## Install And Start

In the new package directory:

```powershell
.\scripts\install-windows.ps1
.\scripts\start-all-windows.ps1
```

Open `http://127.0.0.1:5173`. Click **Skill 管理** in the top toolbar. Each Brief/body slot has its own Markdown candidate list; uploading or switching one slot does not change the other slots.

## Verify And Roll Back

Verify the backend responds at `http://127.0.0.1:8000/api/agent/health` and the existing projects remain visible. New Skill Markdown files are stored under `app-data\skills`.

To roll back, stop the new services and restart the previous deployment directory. The database patch only adds two unused tables and does not modify existing project records.
