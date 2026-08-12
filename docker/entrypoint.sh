#!/bin/sh
set -eu

case "${1:-api}" in
  api)
    set -- daphne \
      --bind 0.0.0.0 \
      --port 8000 \
      researchhub.asgi:application
    ;;

  beat)
    set -- celery \
      --app researchhub beat \
      --loglevel INFO \
      --pidfile= \
      --scheduler redbeat.RedBeatScheduler
    ;;

  flower)
    set -- celery \
      --app researchhub flower \
      --port 5555 \
      --url_prefix flower
    ;;

  worker)
    : "${QUEUE:?QUEUE is required}"
    concurrency="${CELERY_CONCURRENCY:-$(( $(nproc) * 3 ))}"
    set -- celery \
      --app researchhub \
      worker \
      --concurrency "$concurrency" \
      --events \
      --hostname "${CELERY_WORKER_NAME:-worker}" \
      --loglevel INFO \
      --pool "${CELERY_POOL:-prefork}" \
      --prefetch-multiplier 1 \
      --queues "$QUEUE"
    ;;
esac

exec "$@"
