celery -A researchhub worker -Q development_core_queue -l info --concurrency=1 --prefetch-multiplier=1 -P prefork
