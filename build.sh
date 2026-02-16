#!/usr/bin/env bash
set -euo pipefail

IMAGE="ghcr.io/ebrainte/rd-dav-server"
PLATFORMS="linux/amd64,linux/arm64"
BUILDER="multiarch"

# Default tag
TAG="${1:-latest}"

echo "==> Building ${IMAGE}:${TAG} for ${PLATFORMS}"

# Ensure buildx builder exists
if ! docker buildx inspect "$BUILDER" &>/dev/null; then
    echo "==> Creating buildx builder: ${BUILDER}"
    docker buildx create --name "$BUILDER" --use
else
    docker buildx use "$BUILDER"
fi

# Build and push
docker buildx build \
    --platform "$PLATFORMS" \
    --push \
    -t "${IMAGE}:${TAG}" \
    -t "${IMAGE}:latest" \
    .

echo "==> Pushed ${IMAGE}:${TAG} and ${IMAGE}:latest"
