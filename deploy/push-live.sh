#!/usr/bin/env bash
# Publish the current committed branch to main without rewriting history.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash deploy/push-live.sh [--check | --help]

Fetch origin, fast-forward this branch to its origin upstream when needed,
and push this branch's committed changes to origin/main. The working tree
must be clean. Diverged branches require manual reconciliation first.

  --check  Fetch and validate only; do not move this branch or push.
  --help   Show this help.

A successful push starts GitHub Actions; it does not verify the live site.
EOF
}

fail() { printf 'Cannot publish: %s\n' "$*" >&2; exit 1; }

check_only=false
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --check) check_only=true ;;
  '') ;;
  *) usage >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { usage >&2; exit 2; }

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || fail "run this inside the repository."
cd "$repo_root"
branch=$(git symbolic-ref --quiet --short HEAD) || fail "HEAD is detached; switch to a branch first."
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  git status --short >&2
  fail "commit or stash your changes, including untracked files, first."
fi

origin_url=$(git remote get-url origin 2>/dev/null) || fail "the origin remote is not configured."
printf 'Fetching origin for branch %s...\n' "$branch"
git fetch origin
git show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main is missing."

head=$(git rev-parse HEAD)
publish_head=$head
upstream=$(git rev-parse --symbolic-full-name '@{upstream}' 2>/dev/null || true)
upstream_remote=$(git config --get "branch.$branch.remote" || true)
if [ "$upstream_remote" = origin ] && [ -n "$upstream" ]; then
  upstream_head=$(git rev-parse "$upstream")
  if [ "$head" != "$upstream_head" ]; then
    if git merge-base --is-ancestor "$head" "$upstream_head"; then
      publish_head=$upstream_head
      if "$check_only"; then
        printf 'Check: %s would fast-forward to %s.\n' "$branch" "$upstream"
      fi
    elif ! git merge-base --is-ancestor "$upstream_head" "$head"; then
      fail "$branch and its origin upstream have diverged. Reconcile them, commit, then retry."
    fi
  fi
fi

git merge-base --is-ancestor refs/remotes/origin/main "$publish_head" ||
  fail "this branch does not include origin/main. Merge or rebase origin/main, then retry."

if "$check_only"; then
  printf 'Check passed: %s can publish commit %s to main. No branch was moved or pushed.\n' "$branch" "${publish_head:0:12}"
  exit 0
fi

if [ "$head" != "$publish_head" ]; then
  git merge --ff-only "$upstream"
fi

if [ "$(git rev-parse refs/remotes/origin/main)" = "$publish_head" ]; then
  printf 'origin/main already contains commit %s; no push was needed.\n' "${publish_head:0:12}"
else
  git push origin HEAD:refs/heads/main
  printf 'Published commit %s to origin/main.\n' "${publish_head:0:12}"
fi

# Support the usual GitHub HTTPS and SSH remote forms without exposing credentials.
actions_url=''
case "$origin_url" in
  https://github.com/*) actions_url="https://github.com/${origin_url#https://github.com/}" ;;
  git@github.com:*) actions_url="https://github.com/${origin_url#git@github.com:}" ;;
  ssh://git@github.com/*) actions_url="https://github.com/${origin_url#ssh://git@github.com/}" ;;
esac
if [ -n "$actions_url" ]; then
  printf 'GitHub Actions: %s/actions\n' "${actions_url%.git}"
fi
printf 'Deployment has not been verified. Check the Deploy live workflow and its live URL.\n'

# Until the GitHub secrets for automatic deploys exist, releases are manual. Remind every time.
image="ghcr.io/hoanlenguyen/bayer2026-backend:$publish_head"
cat <<EOF

REMINDER: deploy backend and frontend by hand (unless Deploy live shows "Backend deployed" and "Live briefings").
Wait until Actions > Deploy live has built the image for ${publish_head:0:7}, then:

  1. Backend (Azure Cloud Shell or Git Bash, not PowerShell):
       IMAGE=$image bash deploy/azure/containerapp.sh update
       bash deploy/azure/containerapp.sh image     # active revision: this image, 100, Healthy

  2. Frontend (this machine, Node.js 22):
       cd deploy/cloudflare && npm run deploy:free

EOF
