#!/usr/bin/env bash
#
# Runs the database migration ECS task with the given image and waits for it
# to finish. Fails when the task cannot be started or does not exit with 0.
#
# Usage: run-migration-task.sh <image-uri> <run-task-parameter-name>

set -euo pipefail

image_uri=$1
parameter_name=$2
poll_interval=${MIGRATION_POLL_INTERVAL:-10}

run_config=$(
  aws ssm get-parameter \
    --name "$parameter_name" \
    --query Parameter.Value \
    --output text
)
cluster=$(jq -r .cluster <<<"$run_config")
family=$(jq -r .taskDefinition <<<"$run_config")

# Terraform owns the task definition with a placeholder image, so register a
# revision of the latest one with the image to deploy.
task_definition=$(
  aws ecs describe-task-definition \
    --task-definition "$family" \
    --query taskDefinition \
    --output json |
    jq --arg image "$image_uri" '
      .containerDefinitions[0].image = $image
      | del(
          .compatibilities,
          .deregisteredAt,
          .registeredAt,
          .registeredBy,
          .requiresAttributes,
          .revision,
          .status,
          .taskDefinitionArn
        )
    '
)
task_definition_arn=$(
  aws ecs register-task-definition \
    --cli-input-json "$task_definition" \
    --query taskDefinition.taskDefinitionArn \
    --output text
)
echo "Registered $task_definition_arn with image $image_uri"

run_result=$(
  aws ecs run-task \
    --cli-input-json "$(jq --arg arn "$task_definition_arn" '.taskDefinition = $arn' <<<"$run_config")" \
    --started-by "github-${GITHUB_RUN_ID:-manual}" \
    --output json
)
task_arn=$(jq -r '.tasks[0].taskArn // empty' <<<"$run_result")
if [ -z "$task_arn" ]; then
  echo "Failed to start the migration task:" >&2
  jq .failures <<<"$run_result" >&2
  exit 1
fi
echo "Started $task_arn"

last_status=""
while :; do
  task=$(
    aws ecs describe-tasks \
      --cluster "$cluster" \
      --tasks "$task_arn" \
      --query 'tasks[0]' \
      --output json
  )
  status=$(jq -r .lastStatus <<<"$task")
  if [ "$status" != "$last_status" ]; then
    echo "Task status: $status"
    last_status=$status
  fi
  if [ "$status" = "STOPPED" ]; then
    break
  fi
  sleep "$poll_interval"
done

container=$(jq -r '.containerDefinitions[0].name' <<<"$task_definition")
log_options=$(jq '.containerDefinitions[0].logConfiguration.options' <<<"$task_definition")
log_group=$(jq -r '."awslogs-group"' <<<"$log_options")
log_stream="$(jq -r '."awslogs-stream-prefix"' <<<"$log_options")/$container/${task_arn##*/}"

# The log stream does not exist when the container never started.
aws logs get-log-events \
  --log-group-name "$log_group" \
  --log-stream-name "$log_stream" \
  --start-from-head \
  --output json |
  jq -r '.events[].message' ||
  echo "No logs available in $log_group/$log_stream" >&2

exit_code=$(jq -r '.containers[0].exitCode // empty' <<<"$task")
if [ "$exit_code" = "0" ]; then
  echo "Migration task succeeded"
  exit 0
fi

echo "Migration task failed (exit code: ${exit_code:-none})" >&2
jq -r '.stoppedReason, .containers[0].reason | select(. != null)' <<<"$task" >&2
exit 1
