.PHONY: start-celery test

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

test:
	cd src && uv run manage.py test --keepdb

start-celery:
	cd src && uv run celery \
		--app=researchhub \
		worker \
		--queues "$$(echo $(CELERY_QUEUES) | tr ' ' ',')" \
		--loglevel=info \
		--prefetch-multiplier=1 \
		--pool=prefork \
		--concurrency=1 \
		--beat
