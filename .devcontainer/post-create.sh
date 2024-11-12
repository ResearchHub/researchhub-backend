#!/usr/bin/env bash
set -e

# Install dependencies
poetry install --directory=src
pip install -r src/requirements-dev.txt --no-deps

cd src
# Apply database migrations
python manage.py makemigrations
python manage.py migrate
# Copy static conent
python manage.py collectstatic --no-input
cd -

echo "Post create script complete."
