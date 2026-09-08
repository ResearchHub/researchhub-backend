#!/bin/sh

set -eu

image_uri=$1
output_directory=$2
script_directory=$(dirname -- "$0")

mkdir -p \
  "$output_directory" \
  "$output_directory/beanstalk.d"

sed \
  "s|__API_IMAGE_URI__|$image_uri|" \
  "$script_directory/docker-compose.yml" \
  > "$output_directory/docker-compose.yml"

cp \
  "$script_directory/beanstalk.d/conf.yaml" \
  "$output_directory/beanstalk.d/conf.yaml"

rm -f "$output_directory/deploy.zip"
(
  cd "$output_directory"
  zip \
    deploy.zip \
    docker-compose.yml \
    beanstalk.d/conf.yaml
)
