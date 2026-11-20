#!/usr/bin/env bash
# =============================================================================
# One-time VPS setup: read-only GitHub deploy key + first clone.
#
# Run ON THE VPS as the user that will run the app (not root):
#   bash vps-setup-deploy-key.sh
#
# The private key is generated on the server and never leaves it. You add the
# printed PUBLIC key to GitHub as a read-only Deploy key:
#   GitHub -> repo -> Settings -> Deploy keys -> Add deploy key
#   (title: "production VPS", leave "Allow write access" UNCHECKED)
# =============================================================================
set -euo pipefail

REPO="${REPO:-Youssef-Shakir/construction-erp}"
APP_DIR="${APP_DIR:-/srv/construction-erp/app}"
BRANCH="${DEPLOY_BRANCH:-main}"
KEY="$HOME/.ssh/erp_deploy"
HOST_ALIAS="github-erp"
# GitHub's published ed25519 host key fingerprint (docs.github.com "GitHub's SSH key fingerprints")
GITHUB_ED25519_FP="SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"

mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"

# 1. Deploy key (ed25519, no passphrase so updates can run unattended)
if [ ! -f "$KEY" ]; then
    ssh-keygen -t ed25519 -N "" -f "$KEY" -C "erp-production-deploy@$(hostname)"
    echo "Created $KEY"
else
    echo "Deploy key already exists: $KEY"
fi
chmod 600 "$KEY"

# 2. Pin GitHub's host key (verified against the published fingerprint)
if ! ssh-keygen -F github.com -f "$HOME/.ssh/known_hosts" >/dev/null 2>&1; then
    scanned="$(ssh-keyscan -t ed25519 github.com 2>/dev/null)"
    fp="$(printf '%s\n' "$scanned" | ssh-keygen -lf - | awk '{print $2}')"
    if [ "$fp" != "$GITHUB_ED25519_FP" ]; then
        echo "ERROR: github.com host key fingerprint mismatch ($fp). Aborting." >&2
        exit 1
    fi
    printf '%s\n' "$scanned" >> "$HOME/.ssh/known_hosts"
    echo "Pinned github.com host key"
fi

# 3. SSH alias so only this repo uses this key
if ! grep -q "^Host $HOST_ALIAS\$" "$HOME/.ssh/config" 2>/dev/null; then
    cat >> "$HOME/.ssh/config" <<EOF

Host $HOST_ALIAS
    HostName github.com
    User git
    IdentityFile $KEY
    IdentitiesOnly yes
EOF
    chmod 600 "$HOME/.ssh/config"
    echo "Added SSH alias '$HOST_ALIAS'"
fi

echo
echo "================ PUBLIC deploy key (add to GitHub, read-only) ================"
cat "$KEY.pub"
echo "==============================================================================="
echo "GitHub -> https://github.com/$REPO/settings/keys -> Add deploy key"
echo
if [ -t 0 ]; then
    read -r -p "Press Enter once the key is added on GitHub... " _
fi

# 4. Verify access (GitHub answers with exit code 1 even on success)
if ssh -T "git@$HOST_ALIAS" 2>&1 | grep -q "successfully authenticated"; then
    echo "GitHub access OK"
else
    echo "GitHub does not accept the key yet. Add it on GitHub, then run this script again." >&2
    exit 2
fi

# 5. First clone (or switch an existing HTTPS clone to the deploy key)
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" remote set-url origin "git@$HOST_ALIAS:$REPO.git"
    echo "Existing clone now uses the deploy key: $APP_DIR"
else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$BRANCH" "git@$HOST_ALIAS:$REPO.git" "$APP_DIR"
fi
chmod +x "$APP_DIR/scripts/"*.sh 2>/dev/null || true

cat <<EOF

Next steps:
  cd $APP_DIR
  cp .env.docker.example .env && nano .env      # set DOMAIN, passwords (openssl rand -base64 36)
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
Later updates:
  $APP_DIR/scripts/update.sh
EOF
