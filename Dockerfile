# ---- Builder stage ----
FROM python:3.9-slim AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN python3 -m venv $VIRTUAL_ENV

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Verify scipy installation
RUN python -c "import scipy; print(f'Scipy version: {scipy.__version__}')"

# ---- Final stage ----
FROM python:3.9-slim

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install runtime system dependencies (poppler for PDF processing, curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -r -s /bin/false appuser

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY . .

# Set ownership so appuser can read the app files
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run the FastAPI app with uvicorn
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
