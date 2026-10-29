FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home appuser \
    && mkdir -p /data/uploads \
    && chown appuser:appuser /data/uploads \
    && chmod 700 /data/uploads

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
COPY --chown=appuser:appuser alembic.ini /app/alembic.ini
COPY --chown=appuser:appuser migrations /app/migrations

USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
