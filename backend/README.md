# PFCD Backend (Skeleton)

This is the first runnable backend skeleton for the Video-First v1 API contract.

- Framework: FastAPI
- Entry point: `backend/app/main.py`

## Quick start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/draft`
- `PUT /api/jobs/{job_id}/draft`
- `POST /api/jobs/{job_id}/finalize`
- `GET /api/jobs/{job_id}/exports/{format}`
- `DELETE /api/jobs/{job_id}`
- `GET /health`

## Notes

- Job payloads are persisted via SQL (default: local SQLite).
- Export payloads for PDF/DOCX are placeholders.
- This baseline includes:
  - fixed file-size guard (413 on >500MB),
  - agent run placeholders and state transitions,
  - review blocker checks on finalize,
  - speaker resolution persistence in draft payloads.

## Persistence and storage

The backend now persists job payloads to a SQL database and stores exports in Blob Storage
when configured.

Required/optional environment variables:

- `DATABASE_URL` (optional, default: `sqlite:///./pfcd.db`)
- Azure SQL example (ODBC 18):
  - `mssql+pyodbc://<user>:<password>@<server>:1433/<database>?driver=ODBC+Driver+18+for+SQL+Server`
- `AZURE_STORAGE_CONNECTION_STRING` (optional, enables Blob exports)
- `AZURE_STORAGE_CONTAINER_EXPORTS` (optional, default: `exports`)
- `EXPORTS_BASE_PATH` (optional, default: `./storage/exports` for local exports)
