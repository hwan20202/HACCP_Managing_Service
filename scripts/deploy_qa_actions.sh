#!/usr/bin/env bash
# GitHub-hosted Linux runner only. Server secrets and DB stay on the server.
set -euo pipefail
umask 077

for name in DEPLOY_COMMIT QA_SSH_HOST QA_SSH_PORT QA_SSH_USER QA_SSH_KNOWN_HOSTS QA_SSH_PRIVATE_KEY RUNNER_TEMP GITHUB_RUN_ID GITHUB_RUN_ATTEMPT; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing GitHub Actions setting: $name" >&2
    exit 1
  fi
done
[[ "$DEPLOY_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid deployment commit' >&2; exit 1; }
[[ "$QA_SSH_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'Invalid SSH host' >&2; exit 1; }
[[ "$QA_SSH_PORT" =~ ^[0-9]{1,5}$ ]] && (( 10#$QA_SSH_PORT >= 1 && 10#$QA_SSH_PORT <= 65535 )) || { echo 'Invalid SSH port' >&2; exit 1; }
[[ "$QA_SSH_USER" == root ]] || { echo 'Current QA deployment requires the existing root account' >&2; exit 1; }
[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ && "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]] || exit 1

# Avoid deploying an old queued run after a newer main commit is available.
ensure_latest_main() {
  local latest
  latest="$(git ls-remote --exit-code origin refs/heads/main | cut -f1)" || { echo 'Cannot verify current main commit' >&2; exit 1; }
  if [[ "$latest" != "$DEPLOY_COMMIT" ]]; then
    echo 'A newer main commit exists; this deployment is skipped.'
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
      echo 'QA deployment skipped: main advanced after this run started.' >> "$GITHUB_STEP_SUMMARY"
    fi
    exit 0
  fi
}
ensure_latest_main
[[ "$(git rev-parse HEAD)" == "$DEPLOY_COMMIT" ]] || { echo 'Checkout does not match the checked commit' >&2; exit 1; }

work="$(mktemp -d "$RUNNER_TEMP/haccp-qa.XXXXXXXX")"
trap 'rm -f -- "$work/id_ed25519" "$work/known_hosts"' EXIT
printf '%s\n' "$QA_SSH_PRIVATE_KEY" | tr -d '\r' > "$work/id_ed25519"
printf '%s\n' "$QA_SSH_KNOWN_HOSTS" | tr -d '\r' > "$work/known_hosts"
chmod 600 "$work/id_ed25519" "$work/known_hosts"
unset QA_SSH_PRIVATE_KEY
ssh-keygen -y -P '' -f "$work/id_ed25519" > /dev/null
host_key="$QA_SSH_HOST"
if (( 10#$QA_SSH_PORT != 22 )); then host_key="[$QA_SSH_HOST]:$QA_SSH_PORT"; fi
ssh-keygen -F "$host_key" -f "$work/known_hosts" > /dev/null || { echo 'Verified SSH host key is missing' >&2; exit 1; }

git archive --format=tar.gz --output="$work/source.tar.gz" "$DEPLOY_COMMIT"
digest="$(sha256sum "$work/source.tar.gz" | cut -d ' ' -f1)"
git show "$DEPLOY_COMMIT:scripts/redeploy_cafe24_qa.py" > "$work/redeploy_cafe24_qa.py"
remote="/root/biodot-actions-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
target="$QA_SSH_USER@$QA_SSH_HOST"
options=(-F /dev/null -i "$work/id_ed25519" -o BatchMode=yes -o IdentitiesOnly=yes
  -o "UserKnownHostsFile=$work/known_hosts" -o StrictHostKeyChecking=yes
  -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
ssh "${options[@]}" -p "$QA_SSH_PORT" "$target" "umask 077; mkdir '$remote'"
scp "${options[@]}" -P "$QA_SSH_PORT" "$work/source.tar.gz" "$work/redeploy_cafe24_qa.py" "$target:$remote/"
ensure_latest_main
ssh "${options[@]}" -p "$QA_SSH_PORT" "$target" \
  "set -eu; if [ -x /opt/biodot-qa/current/.venv/bin/python ]; then python=/opt/biodot-qa/current/.venv/bin/python; else python=/opt/biodot-qa/bin/python3.14; fi; exec \"\$python\" '$remote/redeploy_cafe24_qa.py' --archive '$remote/source.tar.gz' --sha256 '$digest' --commit '$DEPLOY_COMMIT' --branch main --code-only"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf 'QA code deployed: `%s`\n\nExisting DB/uploads retained; no migration or seeder executed.\n' "$DEPLOY_COMMIT" >> "$GITHUB_STEP_SUMMARY"
fi
