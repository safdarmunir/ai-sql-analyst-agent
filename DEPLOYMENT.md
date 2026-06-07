# Deployment Guide

This project is designed for a simple portfolio deployment:

- Backend API: Railway or Render
- Frontend UI: Streamlit Community Cloud
- Local validation: Docker Compose

Never commit real API keys. Use platform secrets for `GEMINI_API_KEY`.

## 1. Local Docker Smoke Test

Create a root `.env` from the template:

```powershell
Copy-Item .env.example .env
```

Set `GEMINI_API_KEY` inside `.env`, then run:

```powershell
docker compose up --build
```

Open:

- Streamlit: http://localhost:8501
- FastAPI health: http://localhost:8000/health
- FastAPI docs: http://localhost:8000/docs

Expected health response:

```json
{"status":"ok","service":"ai-sql-analyst-api","version":"0.1.0"}
```

## 2. Backend On Railway

Create a new Railway service from the GitHub repository.

Recommended service settings:

- Builder: Dockerfile
- Dockerfile path: `backend/Dockerfile`
- Root/context directory: repository root
- Public networking: enabled
- Persistent volume mount: `/app/data`

Environment variables:

```text
APP_DATA_DIR=/app/data
APP_SCHEMA_SAMPLE_ROWS=5
APP_MAX_UPLOAD_SIZE_MB=25
APP_MAX_QUERY_ROWS=1000
APP_SQL_CORRECTION_ATTEMPTS=1
GEMINI_API_KEY=<your Gemini key>
GEMINI_MODEL=gemini-2.5-flash
CORS_ORIGINS=https://your-streamlit-app.streamlit.app
```

After deploy, open:

```text
https://your-railway-service.up.railway.app/health
```

## 3. Backend On Render

Create a new Render Web Service from the GitHub repository.

Recommended service settings:

- Environment: Docker
- Dockerfile path: `backend/Dockerfile`
- Docker build context directory: repository root
- Disk mount path: `/app/data`
- Health check path: `/health`

Environment variables are the same as Railway.

After deploy, open:

```text
https://your-render-service.onrender.com/health
```

## 4. Frontend On Streamlit Community Cloud

Create a new Streamlit app from the GitHub repository.

Recommended app settings:

- Main file path: `frontend/app.py`
- Python version: 3.13 if available, otherwise 3.12
- Requirements file: root `requirements.txt`

Add this in Streamlit **App settings > Secrets**:

```toml
API_BASE_URL = "https://your-backend-service.example.com"
```

Use the backend root URL only. Do not add `/docs`, `/health`, or another path.

## 5. Deployment Smoke Test

After both apps are deployed:

1. Open the Streamlit app.
2. Confirm no backend identity error appears.
3. Upload `sample_data/sales.csv`.
4. Open the `Dashboard` tab.
5. Ask: `Compare revenue by region`.
6. Confirm the app shows generated SQL, a result table, and an insight.

For the larger portfolio demo, upload:

```text
sample_data/adventure_works_customer_sample.csv
```

## 6. Production Upgrade Path

For a larger production version:

- Move uploaded files to S3, Azure Blob Storage, or GCP Cloud Storage.
- Replace SQLite metadata with PostgreSQL.
- Add authentication and per-user dataset ownership.
- Add centralized logs and metrics.
- Add background jobs for large Excel ingestion.
- Add rate limiting and stricter upload scanning.
