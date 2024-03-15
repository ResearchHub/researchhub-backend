#!/usr/bin/env bash
set -e

# Install dependencies
poetry install --directory=src
pip install -r src/requirements.txt --no-deps

# Apply database migrations
cd src
python manage.py makemigrations
python manage.py migrate
cd -

echo "Post create script complete."
