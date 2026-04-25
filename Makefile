.PHONY: help install dev-install test test-coverage lint format migrate migrate-create clean docker-build docker-up docker-down

# Default target
help:
	@echo "TaskFlow Pro - Available Commands:"
	@echo "  make install          Install production dependencies"
	@echo "  make dev-install      Install development dependencies"
	@echo "  make test             Run all tests"
	@echo "  make test-coverage    Run tests with coverage report"
	@echo "  make lint             Run linting (flake8, mypy)"
	@echo "  make format           Format code (black, isort)"
	@echo "  make migrate          Run database migrations"
	@echo "  make migrate-create   Create new migration"
	@echo "  make clean            Clean up cache and temp files"
	@echo "  make docker-build     Build Docker images"
	@echo "  make docker-up        Start Docker services"
	@echo "  make docker-down      Stop Docker services"
	@echo "  make run              Run development server"
	@echo "  make run-worker       Run Celery worker"

# Installation
install:
	pip install -r requirements.txt

dev-install: install
	pip install -e ".[dev]"

# Testing
test:
	pytest tests/ -v --tb=short

test-coverage:
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pytest tests/e2e/ -v

# Code Quality
lint:
	flake8 src/ tests/
	mypy src/
	@echo "Linting complete!"

format:
	black src/ tests/
	isort src/ tests/
	@echo "Formatting complete!"

format-check:
	black --check src/ tests/
	isort --check-only src/ tests/

# Database
migrate:
	alembic upgrade head

migrate-create:
	@read -p "Enter migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

migrate-downgrade:
	alembic downgrade -1

migrate-history:
	alembic history --verbose

# Development
run:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

run-prod:
	uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4

run-worker:
	celery -A src.tasks worker --loglevel=info

run-flower:
	celery -A src.tasks flower --port=5555

# Docker
docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-clean:
	docker-compose down -v --remove-orphans

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/

# Security
security-check:
	bandit -r src/
	safety check

# CI/CD
ci: format-check lint test
	@echo "CI checks passed!"

# Documentation
docs-build:
	cd docs && mkdocs build

docs-serve:
	cd docs && mkdocs serve
