.PHONY: help install dev-install test test-cov lint format migrate migrate-up migrate-down run run-dev clean docker-build docker-up docker-down

help:
	@echo "TaskFlow Pro - Backend Commands"
	@echo "================================"
	@echo "install      - Install production dependencies"
	@echo "dev-install  - Install development dependencies"
	@echo "test         - Run tests"
	@echo "test-cov     - Run tests with coverage"
	@echo "lint         - Run linters"
	@echo "format       - Format code"
	@echo "migrate      - Create new migration (make migrate msg='description')"
	@echo "migrate-up   - Apply migrations"
	@echo "migrate-down - Rollback migrations"
	@echo "run          - Run production server"
	@echo "run-dev      - Run development server with reload"
	@echo "clean        - Clean build artifacts"
	@echo "docker-build - Build Docker image"
	@echo "docker-up    - Start Docker services"
	@echo "docker-down  - Stop Docker services"

install:
	pip install -r requirements.txt

dev-install:
	pip install -r requirements.txt
	pre-commit install

test:
	pytest -xvs

test-cov:
	pytest -xvs --cov=src --cov-report=html --cov-report=term-missing

lint:
	flake8 src tests
	mypy src
	black --check src tests
	isort --check-only src tests

format:
	black src tests
	isort src tests

migrate:
	alembic revision --autogenerate -m "$(msg)"

migrate-up:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

run:
	gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

run-dev:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -delete
	rm -rf htmlcov .coverage build dist *.egg-info

docker-build:
	docker build -t taskflow-backend:latest .

docker-up:
	docker-compose up -d postgres redis minio

docker-down:
	docker-compose down
