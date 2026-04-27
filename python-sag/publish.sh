#!/usr/bin/env bash
#
# Build and publish the semantic-action-grammar package to PyPI.
#
# Usage:
#   ./publish.sh                # auto-bump patch, build + upload to PyPI
#   ./publish.sh --minor        # bump minor version (new features)
#   ./publish.sh --major        # bump major version (breaking changes)
#   ./publish.sh --patch        # bump patch version (default)
#   ./publish.sh --no-bump      # build + upload without version bump
#   ./publish.sh --test         # auto-bump patch, upload to TestPyPI
#   ./publish.sh --build-only   # auto-bump patch, build only (no upload)
#
# Auth: ~/.pypirc, or TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-…

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="/tmp/sag-publish-venv"
PYPROJECT="$SCRIPT_DIR/pyproject.toml"
INIT_FILE="$SCRIPT_DIR/src/sag/__init__.py"

BUMP="patch"
TARGET="pypi"
UPLOAD=true

for arg in "$@"; do
  case "$arg" in
    --major)      BUMP="major" ;;
    --minor)      BUMP="minor" ;;
    --patch)      BUMP="patch" ;;
    --no-bump)    BUMP="none" ;;
    --test)       TARGET="testpypi" ;;
    --build-only) UPLOAD=false ;;
    -h|--help)    sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "=== semantic-action-grammar publisher ==="

# --- Read current version ---
CURRENT=$(grep '^version = ' "$PYPROJECT" | sed 's/version = "\(.*\)"/\1/')
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
echo "Current version: $CURRENT"

# --- Bump version ---
if [ "$BUMP" != "none" ]; then
  case "$BUMP" in
    major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
    patch) PATCH=$((PATCH + 1)) ;;
  esac
  NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"

  sed -i "s/^version = \".*\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT"
  if [ -f "$INIT_FILE" ]; then
    sed -i "s/__version__ = \".*\"/__version__ = \"${NEW_VERSION}\"/" "$INIT_FILE"
  fi

  echo "Bumped: $CURRENT → $NEW_VERSION ($BUMP)"
else
  NEW_VERSION="$CURRENT"
  echo "No version bump"
fi

# --- Regenerate ANTLR sources (uses project .venv if present, else system python3) ---
GEN_PY="${PYTHON:-$( [ -f "$SCRIPT_DIR/.venv/bin/python3" ] && echo "$SCRIPT_DIR/.venv/bin/python3" || command -v python3 )}"
echo "Regenerating ANTLR sources with: $GEN_PY"
make -C "$SCRIPT_DIR" generate PYTHON="$GEN_PY"

# --- Clean previous artifacts ---
rm -rf "$SCRIPT_DIR/dist" "$SCRIPT_DIR/build" "$SCRIPT_DIR/src"/*.egg-info

# --- Fresh build venv ---
echo "Creating clean build environment..."
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip build twine

# --- Build ---
echo "Building v${NEW_VERSION}..."
cd "$SCRIPT_DIR"
python -m build --quiet

echo ""
echo "Built:"
ls -lh dist/

# --- Validate ---
twine check dist/* --strict

# --- Upload ---
if [ "$UPLOAD" = true ]; then
  echo ""
  if [ "$TARGET" = "testpypi" ]; then
    echo "Uploading v${NEW_VERSION} to TestPyPI..."
    twine upload --repository testpypi dist/*
    echo ""
    echo "Test install:"
    echo "  pip install --index-url https://test.pypi.org/simple/ semantic-action-grammar==${NEW_VERSION}"
  else
    echo "Uploading v${NEW_VERSION} to PyPI..."
    twine upload dist/*
    echo ""
    echo "Install:"
    echo "  pip install semantic-action-grammar==${NEW_VERSION}"
  fi
else
  echo ""
  echo "Build complete (v${NEW_VERSION}). Skipping upload."
fi

# --- Cleanup ---
deactivate
rm -rf "$VENV_DIR"

echo ""
echo "Done. Version: ${NEW_VERSION}"
