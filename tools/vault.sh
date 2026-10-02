#!/usr/bin/env bash
# Encrypted video files live on the repo's "vault" branch (one snapshot commit, replaced each time,
# so removed videos don't pile up in history). Used by the workflows:
#   tools/vault.sh pull   -> ./vault holds the current encrypted files
#   tools/vault.sh push   -> publish ./vault as the new "vault" branch, then check GitHub really has it
# ./vault is always a worktree of the checked-out repo, so pushes use the workflow's GitHub login.
# push fails loudly (exit 1) if GitHub doesn't end up with exactly this snapshot, so nothing that
# runs afterwards (like deleting older copies) can run on a failed save.
set -euo pipefail
case "${1:-}" in
  pull)
    git worktree remove --force vault 2>/dev/null || rm -rf vault
    git worktree prune
    rc=0; git ls-remote --exit-code --heads origin vault >/dev/null 2>&1 || rc=$?
    if [ "$rc" = 0 ]; then
      git fetch -q --depth=1 origin vault
      git worktree add -q --detach vault FETCH_HEAD
    elif [ "$rc" = 2 ]; then                                          # no vault branch yet
      git worktree add -q --orphan -b "vault-new-$(date +%s)" vault
    else                    # couldn't reach GitHub: stop, never start from an empty vault by mistake
      echo "::error::vault: could not read the vault branch from GitHub"; exit 1
    fi
    ;;
  push)
    cd vault
    git checkout -q --orphan "vault-$(date +%s)"
    git add -A
    git -c user.name=review-bot -c user.email=review-bot@users.noreply.github.com \
        commit -qm "Encrypted video files" || { echo "vault: nothing to save"; exit 0; }
    for i in 1 2 3; do git push -q -f origin HEAD:refs/heads/vault && break; sleep 5; done
    remote=$(git ls-remote origin refs/heads/vault | cut -f1)
    if [ "$remote" != "$(git rev-parse HEAD)" ]; then
      echo "::error::vault: the encrypted files could NOT be saved to GitHub (nothing was deleted)"; exit 1
    fi
    echo "vault: $(git ls-files | wc -l) encrypted files saved and verified on GitHub"
    ;;
  *) echo "usage: tools/vault.sh pull|push"; exit 2 ;;
esac
