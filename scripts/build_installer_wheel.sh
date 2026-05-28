#!/usr/bin/env bash

set -euo pipefail

# ------------------------------------------------------------
# Build SURFACE CDMS installer wheel
# ------------------------------------------------------------
#
# Important:
# If anything in surface/ changes, the SURFACE app artifact must
# be rebuilt before the installer wheel is built.
#
# This script does:
#   1. Copies the root README.md into installer/README.md
#   2. Builds the SURFACE app artifact
#   3. Builds the installer wheel
# ------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER_DIR="${REPO_ROOT}/installer"

ROOT_README="${REPO_ROOT}/README.md"
INSTALLER_README="${INSTALLER_DIR}/README.md"

if [ ! -f "${ROOT_README}" ]; then
    echo "ERROR: Root README.md not found at ${ROOT_README}"
    exit 1
fi

echo "Copying root README.md into installer package..."
cp "${ROOT_README}" "${INSTALLER_README}"

echo ""
echo "Building SURFACE app artifact..."
"${REPO_ROOT}/scripts/build_surface_artifact.sh"

echo ""
echo "Building SURFACE CDMS installer wheel..."
cd "${INSTALLER_DIR}"

rm -rf build dist *.egg-info src/*.egg-info src/surface_cdms.egg-info

python3 -m build

echo ""
echo "Installer wheel built successfully."
echo "Output:"
ls -lh "${INSTALLER_DIR}/dist"