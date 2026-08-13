#!/bin/sh

set -eu

image_uri=$1
output_directory=$2

mkdir -p "$output_directory"

jq --null-input \
  --arg image "$image_uri" \
  '{
    AWSEBDockerrunVersion: "1",
    Image: {
      Name: $image,
      Update: "true"
    },
    Ports: [
      {ContainerPort: "8000"}
    ]
  }' > "$output_directory/Dockerrun.aws.json"

(
  cd "$output_directory"
  zip deploy.zip Dockerrun.aws.json
)
