#!/usr/bin/env bash
set -e

# Install dependencies
poetry install --directory=src
pip install --upgrade pip
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

# Execute any custom post-create scripts if they exist
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
for script in "$SCRIPT_DIR"/post-create-*.sh; do
    if [ -f "$script" ] && [ -x "$script" ]; then
        echo "Executing custom script: $(basename "$script")"
        "$script"
    fi
done

echo "Post create script complete."
