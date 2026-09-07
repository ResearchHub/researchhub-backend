#!/bin/sh

set -eu

image_uri=$1
output_directory=$2
script_directory=$(dirname -- "$0")

mkdir -p "$output_directory"

sed \
  "s|__API_IMAGE_URI__|$image_uri|" \
  "$script_directory/docker-compose.yml" \
  > "$output_directory/docker-compose.yml"

rm -f "$output_directory/deploy.zip"
zip -j "$output_directory/deploy.zip" "$output_directory/docker-compose.yml"
