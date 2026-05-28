#!/usr/bin/env bash

set -euo pipefail

# ------------------------------------------------------------
# Build SURFACE application release artifact
# ------------------------------------------------------------
#
# This script packages the top-level surface/ directory into a
# versioned tar.gz artifact.
#
# Example output:
#
#   dist/surface-app-v0.2.0-alpha.3.tar.gz
#
# It also copies the artifact into:
#
#   installer/src/surface_cdms/artifacts/
#
# so the Python wheel can include the matching SURFACE app artifact.
# ------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${REPO_ROOT}/VERSION"
SURFACE_DIR="${REPO_ROOT}/surface"
DIST_DIR="${REPO_ROOT}/dist"
PACKAGE_ARTIFACTS_DIR="${REPO_ROOT}/installer/src/surface_cdms/artifacts"

if [ ! -f "${VERSION_FILE}" ]; then
    echo "ERROR: VERSION file not found at ${VERSION_FILE}"
    exit 1
fi

VERSION="$(cat "${VERSION_FILE}" | tr -d '[:space:]')"

if [ -z "${VERSION}" ]; then
    echo "ERROR: VERSION file is empty"
    exit 1
fi

if [ ! -d "${SURFACE_DIR}" ]; then
    echo "ERROR: surface/ directory not found at ${SURFACE_DIR}"
    exit 1
fi

mkdir -p "${DIST_DIR}"
mkdir -p "${PACKAGE_ARTIFACTS_DIR}"

ARTIFACT_NAME="surface-app-v${VERSION}.tar.gz"
ARTIFACT_PATH="${DIST_DIR}/${ARTIFACT_NAME}"
PACKAGE_ARTIFACT_PATH="${PACKAGE_ARTIFACTS_DIR}/${ARTIFACT_NAME}"

echo "Building SURFACE app artifact..."
echo "Version: ${VERSION}"
echo "Source:  ${SURFACE_DIR}"
echo "Output:  ${ARTIFACT_PATH}"

# Remove existing artifact with the same version.
rm -f "${ARTIFACT_PATH}"

tar \
    --exclude="surface/.git" \
    --exclude="surface/.gitignore" \
    --exclude="surface/data" \
    --exclude="surface/data/*" \
    --exclude="surface/backup_restore_dumps" \
    --exclude="surface/backup_restore_dumps/*" \
    --exclude="surface/api/production.env" \
    --exclude="surface/api/.env" \
    --exclude="surface/.env" \
    --exclude="surface/**/*.env" \
    --exclude="surface/**/__pycache__" \
    --exclude="surface/**/*.pyc" \
    --exclude="surface/**/*.pyo" \
    --exclude="surface/**/.DS_Store" \
    --exclude="surface/**/db.sqlite3" \
    --exclude="surface/**/db.sqlite3-journal" \
    --exclude="surface/**/*.log" \
    --exclude="surface/api/static/admin" \
    --exclude="surface/api/static/colorfield" \
    --exclude="surface/api/static/gis" \
    --exclude="surface/api/static/import_export" \
    --exclude="surface/api/static/material" \
    --exclude="surface/api/static/rest_framework" \
    --exclude="surface/api/static/ckeditor" \
    --exclude="surface/api/staticfiles" \
    --exclude="surface/api/productionfiles" \
    -czf "${ARTIFACT_PATH}" \
    -C "${REPO_ROOT}" \
    surface

echo ""
echo "Artifact created successfully:"
echo "${ARTIFACT_PATH}"

echo ""
echo "Copying artifact into Python package..."

# Keep only the current matching app artifact inside the package.
rm -f "${PACKAGE_ARTIFACTS_DIR}"/surface-app-v*.tar.gz

cp "${ARTIFACT_PATH}" "${PACKAGE_ARTIFACT_PATH}"

echo "Packaged artifact copied to:"
echo "${PACKAGE_ARTIFACT_PATH}"
