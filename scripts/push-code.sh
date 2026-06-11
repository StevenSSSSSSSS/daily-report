#!/usr/bin/env bash
set -euo pipefail

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" != "main" ]]; then
  echo "Refusing to push from branch: $branch"
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes first."
  git status --short
  exit 1
fi

git fetch origin main

base="$(git merge-base HEAD origin/main)"
remote_changes="$(git diff --name-only "$base"..origin/main || true)"

if [[ -n "$remote_changes" ]]; then
  invalid_remote_changes="$(printf "%s\n" "$remote_changes" | grep -Ev '^(daily-data/|$)' || true)"
  if [[ -n "$invalid_remote_changes" ]]; then
    echo "Remote has non-daily-data changes. Review before rebasing:"
    printf "%s\n" "$invalid_remote_changes"
    exit 1
  fi

  echo "Remote only has daily-data state updates. Rebasing local commits..."
  git rebase origin/main
fi

python3 -m py_compile main_new.py prompts.py
git push origin main
