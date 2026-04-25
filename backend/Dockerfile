# TaskFlow Pro Backend - Production Dockerfile
# Multi-stage build with security hardening
# Python 3.11 + FastAPI + PostgreSQL

# =============================================================================
# STAGE 1: Dependencies
# =============================================================================
FROM python:3.11-slim-bookworm AS dependencies

# Build arguments
ARG POETRY_VERSION=1.7.1
ARG APP_ENV=production

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==${POETRY_VERSION}

# Set Poetry configuration
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# Copy dependency files
WORKDIR /app
COPY pyproject.toml poetry.lock* ./

# Install dependencies (without dev dependencies for production)
RUN poetry install --no-dev --no-ansi && rm -rf $POETRY_CACHE_DIR

# =============================================================================
# STAGE 2: Test Runner
# =============================================================================
FROM python:3.11-slim-bookworm AS test-runner

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy dependency files
WORKDIR /app
COPY pyproject.toml poetry.lock* ./

# Install all dependencies including dev
RUN poetry install --no-ansi

# Copy source code
COPY . .

# Run tests
RUN pytest tests/ -v --tb=short -x

# =============================================================================
# STAGE 3: Production
# =============================================================================
FROM python:3.11-slim-bookworm AS production

# Security: Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/false appuser

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set working directory
WORKDIR /app

# Copy installed dependencies from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appgroup . .

# Remove unnecessary files
RUN rm -rf \
    tests/ \
    .pytest_cache/ \
    __pycache__/ \
    .git/ \
    *.md \
    .env* \
    docker-compose*.yml \
    Dockerfile*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    APP_ENV=production \
    PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Switch to non-root user
USER appuser

# Run application with Gunicorn + Uvicorn workers
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "--enable-stdio-inheritance", "main:app"]
