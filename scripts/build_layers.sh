#!/bin/bash
# =============================================================================
# Build Lambda Layers for Supply Chain Ghost
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LAYER_DIR="$PROJECT_ROOT/infra/layers"

mkdir -p "$LAYER_DIR"

echo "[SCG] Building shared Lambda layer..."

# Create temporary build directory
BUILD_DIR=$(mktemp -d)
PYTHON_DIR="$BUILD_DIR/python"
mkdir -p "$PYTHON_DIR"

# Install shared dependencies into layer
pip install \
  boto3 \
  requests \
  feedparser \
  strands-agents \
  strands-agents-tools \
  --target "$PYTHON_DIR" \
  --quiet \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  --python-version 3.12 2>/dev/null || \
pip install \
  boto3 \
  requests \
  feedparser \
  --target "$PYTHON_DIR" \
  --quiet

# Copy shared utils into layer
mkdir -p "$PYTHON_DIR/shared"
cp "$PROJECT_ROOT/lambdas/shared/utils.py" "$PYTHON_DIR/shared/"
touch "$PYTHON_DIR/shared/__init__.py"

# Package
cd "$BUILD_DIR"
zip -r "$LAYER_DIR/shared-layer.zip" python/ -q
echo "[✓] Shared layer built: $LAYER_DIR/shared-layer.zip"

# Clean up
rm -rf "$BUILD_DIR"

# Nova Act layer (separate due to size)
echo "[SCG] Building Nova Act layer..."
BUILD_DIR2=$(mktemp -d)
PYTHON_DIR2="$BUILD_DIR2/python"
mkdir -p "$PYTHON_DIR2"

pip install \
  nova-act \
  --target "$PYTHON_DIR2" \
  --quiet 2>/dev/null || echo "[!] nova-act not available via pip — will use container deployment"

if [ -d "$PYTHON_DIR2/nova_act" ] || [ -f "$PYTHON_DIR2/nova_act.py" ]; then
  cd "$BUILD_DIR2"
  zip -r "$LAYER_DIR/nova-act-layer.zip" python/ -q
  echo "[✓] Nova Act layer built: $LAYER_DIR/nova-act-layer.zip"
else
  echo "[!] Nova Act SDK requires special installation — using Bedrock native integration"
fi

rm -rf "$BUILD_DIR2"

echo "[✓] All Lambda layers built successfully"
