# Backend image for the AnalytIQ Intelligence.
# Build from the repository root, because the image also needs materials/:
#   docker build -f backend/Dockerfile -t analytics-manager-backend .
# Run (keys are passed at run time, never baked into the image):
#   docker run -p 8000:8000 --env-file backend/.env analytics-manager-backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATAPACK_PATH=/app/materials/Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx \
    OUTPUT_DIR=output \
    STAGE_DELAY=0.35

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY materials/ /app/materials/
COPY backend/app ./app

# Run as a non-root user; generated PBIP files go to /app/backend/output.
RUN useradd --create-home appuser && mkdir -p output && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health')" || exit 1

# Hosts such as Render or Azure Container Apps set PORT; default 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
