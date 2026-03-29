#!/usr/bin/env bash
# check-upstream.sh — Compare local fork against upstream Martian-Engineering/maniple.
#
# Usage:
#   bash scripts/check-upstream.sh          # summary
#   bash scripts/check-upstream.sh --detail  # show commit messages + file overlap

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

DETAIL=false
if [[ "$1" == "--detail" ]]; then
    DETAIL=true
fi

# Ensure upstream remote exists
if ! git remote get-url upstream > /dev/null 2>&1; then
    echo "ERROR: No 'upstream' remote. Add it:"
    echo "  git remote add upstream https://github.com/Martian-Engineering/maniple.git"
    exit 1
fi

echo "Fetching upstream..."
git fetch upstream --quiet

LOCAL_VERSION=$(grep 'version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
AHEAD=$(git log --oneline upstream/main..HEAD | wc -l | tr -d ' ')
BEHIND=$(git log --oneline HEAD..upstream/main | wc -l | tr -d ' ')

echo ""
echo "Fork status:"
echo "  Local version:  $LOCAL_VERSION"
echo "  Commits ahead:  $AHEAD"
echo "  Commits behind: $BEHIND"

if [[ "$BEHIND" -eq 0 ]]; then
    echo ""
    echo "OK: Up to date with upstream. No new upstream commits."
    exit 0
fi

echo ""
echo "WARNING: Upstream has $BEHIND new commit(s) since our fork point."

if $DETAIL; then
    echo ""
    echo "=== Upstream commits we don't have ==="
    git log --oneline HEAD..upstream/main

    echo ""
    echo "=== File overlap (files modified by both us and upstream) ==="
    OUR_FILES=$(git diff --name-only upstream/main HEAD)
    THEIR_FILES=$(git diff --name-only HEAD upstream/main)
    OVERLAP=$(comm -12 <(echo "$OUR_FILES" | sort) <(echo "$THEIR_FILES" | sort))

    if [[ -z "$OVERLAP" ]]; then
        echo "  No overlap — safe to merge."
    else
        echo "  CONFLICT RISK in:"
        echo "$OVERLAP" | sed 's/^/    /'
        echo ""
        echo "  These files were modified by both us and upstream."
        echo "  Cherry-pick individual upstream commits and test each."
    fi
fi

echo ""
echo "Next steps:"
echo "  1. Review: bash scripts/check-upstream.sh --detail"
echo "  2. If safe: git merge upstream/main"
echo "  3. If overlap: cherry-pick individual commits"
echo "  4. See FORK.md for merge policy"
