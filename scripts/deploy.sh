#!/usr/bin/env bash
set -euo pipefail

# Deploys the latest primary branch and runs docker compose (requires sudo for Docker).
# Usage: ./scripts/deploy.sh

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

BRANCH="master"

echo "=== Updating repo to ${BRANCH} ==="
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "=== Building containers ==="
sudo docker compose build

echo "=== Starting containers (detached) ==="
sudo docker compose up -d

echo "Deployment complete. Containers are running."
