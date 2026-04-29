# PFCD Streamlit App

Python Streamlit UI that mirrors the React frontend and talks to the same backend.

## Environment variables

- `API_BASE` (default `http://127.0.0.1:8000`)
- `PFCD_API_KEY` (optional)

## Local run

```bash
cd streamlit_app
pip install -r requirements.txt
streamlit run app.py
```

## Docker run

```bash
cd streamlit_app
docker build -t pfcd-streamlit:local .
docker run --rm -p 8501:8501 \
  -e API_BASE=http://host.docker.internal:8000 \
  -e PFCD_API_KEY="$PFCD_API_KEY" \
  pfcd-streamlit:local
```
