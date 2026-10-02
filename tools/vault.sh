#!/usr/bin/env bash
# Encrypted video files live on the repo's "vault" branch (one snapshot commit, replaced each time,
# so removed videos don't pile up in history). Used by the workflows:
#   tools/vault.sh pull   -> ./vault holds the current encrypted files
#   tools/vault.sh push   -> publish ./vault as the new "vault" branch
set -euo pipefail
case "${1:-}" in
  pull)
    git worktree remove --force vault 2>/dev/null || rm -rf vault
    if git ls-remote --exit-code --heads origin vault >/dev/null 2>&1; then
      git fetch -q --depth=1 origin vault
      git worktree add -q --detach vault FETCH_HEAD
    else
      mkdir -p vault
    fi
    ;;
  push)
    cd vault
    if [ ! -e .git ]; then git init -q; git remote add origin "$(git -C .. remote get-url origin)"; fi
    git checkout -q --orphan "vault-$(date +%s)"
    git add -A
    git -c user.name=review-bot -c user.email=review-bot@users.noreply.github.com \
        commit -qm "Encrypted video files" || { echo "vault: nothing to save"; exit 0; }
    for i in 1 2 3; do git push -q -f origin HEAD:refs/heads/vault && break; sleep 5; done
    echo "vault: $(git ls-files | wc -l) encrypted files saved"
    ;;
  *) echo "usage: tools/vault.sh pull|push"; exit 2 ;;
esac
