#!/usr/bin/env bash
set -e

# Install dependencies
poetry install --directory=src
pip install -r src/requirements.txt --no-deps

cd src
# Apply database migrations
python manage.py makemigrations
python manage.py migrate
# Copy static conent
python manage.py collectstatic --no-input
cd -

# Install AWS CLI
echo "Post create script adding aws cli."
pip install awscli

# Create S3 bucket in LocalStack
echo "Post create script creating local S3 bucket."
aws --endpoint-url=http://localstack:4566 s3 mb s3://local-researchhub-bucket

echo "Post create script complete."
