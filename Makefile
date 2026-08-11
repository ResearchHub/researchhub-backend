.DEFAULT_GOAL := help

CELERY_QUEUES := \
	bluesky_metrics \
	bounties \
	caches \
	contributions \
	default \
	elastic_search \
	external_reporting \
	github_metrics \
	hot_score \
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

.PHONY: help
help: ## Show this help
	@awk -F':.*## ' '/^[a-zA-Z_-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: test
test: ## Run the Django test suite
	cd src && uv run manage.py test --keepdb

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
