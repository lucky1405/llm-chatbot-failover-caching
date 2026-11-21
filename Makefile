.PHONY: up down build test test-local clean logs

# Start all services with Docker Compose (backend on :8000, frontend on :3000)
up:
	docker compose up -d --build

# Stop all running containers
down:
	docker compose down

# Rebuild docker images
build:
	docker compose build

# View logs of services
logs:
	docker compose logs -f

# Run tests inside backend container
test:
	docker compose run --rm backend pytest -v

# Run tests locally with virtualenv
test-local:
	cd backend && PYTHONPATH=. .venv/bin/pytest -v

# Clean docker containers and volumes
clean:
	docker compose down -v
