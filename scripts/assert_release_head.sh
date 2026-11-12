#!/usr/bin/env bash
set -euo pipefail

test "${GITHUB_REF:-}" = refs/heads/main
test "$(git rev-parse HEAD)" = "${RELEASE_SHA:?}"
if [[ "$(gh api "repos/${GITHUB_REPOSITORY:?}/git/ref/heads/main" --jq .object.sha)" != "$RELEASE_SHA" ]]; then
  echo "::error::Release superseded by a newer main commit."
  exit 1
fi
