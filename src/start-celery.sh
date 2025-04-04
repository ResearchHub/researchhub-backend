celery -A researchhub worker \
    -Q default,paper_metadata,caches,hot_score,elastic_search,external_reporting,notifications,paper_misc,cermine,pull_papers,logs,purchases,contributions,author_claim,bounties,hubs \
    -l info \
    --prefetch-multiplier=1 \
    -P prefork \
    --concurrency=1
