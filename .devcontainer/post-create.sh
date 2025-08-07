#!/usr/bin/env bash
set -e


# Install dependencies with uv
uv sync --dev

# Apply database migrations
uv run --active src/manage.py makemigrations
uv run --active src/manage.py migrate
# Copy static conent
uv run --active src/manage.py collectstatic --no-input

# Add Django manage.py alias to .bashrc
echo "alias dj='uv run ${WORKSPACE_PATH}/src/manage.py'" >> ~/.bashrc

# Execute any custom post-create scripts if they exist
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
for script in "$SCRIPT_DIR"/post-create-*.sh; do
    if [ -f "$script" ] && [ -x "$script" ]; then
        echo "Executing custom script: $(basename "$script")"
        "$script"
    fi
done

echo "Post create script complete."
