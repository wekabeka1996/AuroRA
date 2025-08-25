#!/usr/bin/env bash
set -euo pipefail

PREFIX=${1:-v1.0.0-canary}

ensure_clean_tree() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree not clean. Commit or stash changes first." >&2
    exit 1
  fi
}

next_tag() {
  local prefix="$1"
  local last
  last=$(git tag --list "${prefix}.*" | sort -V | tail -n1 || true)
  if [[ -z "$last" ]]; then
    echo "${prefix}.1"
    return
  fi
  local n
  n=$(echo "$last" | grep -Eo '[0-9]+$' || echo 0)
  echo "${prefix}.$((n+1))"
}

ensure_clean_tree
TAG=$(next_tag "$PREFIX")

# Idempotent: if tag exists, just print and exit 0
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "Tag already exists: ${TAG}"
  exit 0
fi

git tag -a "$TAG" -m "Release $TAG"
git push origin "$TAG"
echo "Created and pushed tag ${TAG}"
