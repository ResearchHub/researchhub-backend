.DEFAULT_GOAL := help

CELERY_QUEUES := \
	agents \
	bluesky_metrics \
	bounties \
	caches \
	contributions \
	default \
	elastic_search \
	external_reporting \
	github_metrics \
	hubs \
	logs \
	notifications \
	paper_metadata \
	paper_metrics \
	paper_misc \
	pull_papers \
	purchases \
	reputation \
	x_metrics

DOCKER_IMAGE ?= researchhub-backend:local
DOCKER_PLATFORM ?= linux/arm64

.PHONY: help
help: ## Show this help
	@awk -F':.*## ' '/^[a-zA-Z_-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: test
test: ## Run the Django test suite
	cd src && uv run manage.py test --keepdb

.PHONY: format
format: ## Format Python with ruff
	uv run ruff format src

.PHONY: docker-build
docker-build: ## Build the Docker image
	docker buildx build \
		--platform "$(DOCKER_PLATFORM)" \
		--tag "$(DOCKER_IMAGE)" \
		--load \
		.

.PHONY: start-celery
start-celery: ## Run the Celery worker with beat
	cd src && uv run celery \
		--app=researchhub \
		worker \
		--queues "$$(echo $(CELERY_QUEUES) | tr ' ' ',')" \
		--loglevel=info \
		--prefetch-multiplier=1 \
		--pool=prefork \
		--concurrency=1 \
		--beat
