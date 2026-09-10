FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/finwise
COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY static ./static
COPY scripts ./scripts

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 finwise \
    && mkdir -p /var/lib/finwise /var/lib/finwise/artifacts \
    && chown -R finwise:finwise /opt/finwise /var/lib/finwise

USER finwise
EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/api/v1/health', timeout=3).read()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8766"]
