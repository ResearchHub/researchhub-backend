#!/bin/sh

set -eu

image_uri=$1
output_directory=$2
script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

mkdir -p "$output_directory"

sed \
  "s|__API_IMAGE_URI__|$image_uri|" \
  "$script_directory/docker-compose.yml" \
  > "$output_directory/docker-compose.yml"

(
  cd "$output_directory"
  rm -f deploy.zip
  zip deploy.zip docker-compose.yml
)
