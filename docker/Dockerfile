FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/
COPY pyproject.toml /app/

RUN pip install -e .

# Non-root user
RUN useradd -m -u 1000 pokealert \
    && mkdir -p /app/data /app/logs /app/config \
    && chown -R pokealert:pokealert /app

USER pokealert

VOLUME ["/app/config", "/app/data", "/app/logs"]

ENTRYPOINT ["python", "-m", "pokealert.main"]
CMD ["run", "--config", "/app/config/config.yaml", "--env-file", "/app/config/.env"]