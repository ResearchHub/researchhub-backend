#!/usr/bin/env bash
set -e

# Install dependencies
poetry install --directory=src
pip install --upgrade pip pkginfo
pip install -r src/requirements.txt --no-deps

cd src
# Apply database migrations
python manage.py makemigrations
python manage.py migrate
# Copy static conent
python manage.py collectstatic --no-input
cd -

# Add Django manage.py alias to .bashrc
echo "alias dj='python ${WORKSPACE_PATH}/src/manage.py'" >> ~/.bashrc

echo "Post create script complete."
