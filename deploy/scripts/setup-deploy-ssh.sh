#!/usr/bin/env bash
# Generuje klucz deploy SSH i konfiguruje dostęp na LB + workery.
#
# Uruchom NA JEDNYM serwerze (np. LB) jako root:
#   Jeden VPS:  bash setup-deploy-ssh.sh
#   LB+workery: LB_HOST=... WORKERS=... bash setup-deploy-ssh.sh
#
# Lub z listą workerów:
#   WORKERS="167.233.115.158 167.233.116.159" bash setup-deploy-ssh.sh
set -euo pipefail

KEY_DIR="${KEY_DIR:-/root/.ssh/ytdown-deploy}"
KEY_FILE="${KEY_DIR}/id_ed25519"
DEPLOY_USER="${DEPLOY_USER:-root}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

LB_HOST="${LB_HOST:-}"
WORKERS="${WORKERS:-}"

usage() {
  cat <<EOF
Użycie:
  LB_HOST=167.233.112.233 WORKERS=167.233.115.158 bash $0

Zmienne:
  LB_HOST      IP load balancera (opcjonalnie, jeśli ten skrypt nie działa na LB)
  WORKERS      IP workerów, spacja lub przecinek
  DEPLOY_USER  domyślnie: root
  KEY_DIR      gdzie zapisać klucz (domyślnie: /root/.ssh/ytdown-deploy)

Po zakończeniu skopiuj KLUCZ PRYWATNY do GitHub Secret: DEPLOY_SSH_KEY
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

# Normalizuj WORKERS (przecinki → spacje)
WORKERS="${WORKERS//,/ }"

mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"

if [[ ! -f "$KEY_FILE" ]]; then
  echo "==> Generuję klucz: $KEY_FILE"
  ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -C "ytdown-github-actions"
else
  echo "==> Klucz już istnieje: $KEY_FILE"
fi

PUB_KEY="$(cat "${KEY_FILE}.pub")"

install_key_locally() {
  local user_home
  if [[ "$DEPLOY_USER" == "root" ]]; then
    user_home="/root"
  else
    user_home="/home/$DEPLOY_USER"
  fi
  local auth="${user_home}/.ssh/authorized_keys"
  mkdir -p "${user_home}/.ssh"
  chmod 700 "${user_home}/.ssh"
  touch "$auth"
  chmod 600 "$auth"
  if grep -qF "$PUB_KEY" "$auth" 2>/dev/null; then
    echo "    klucz już w $auth"
  else
    echo "$PUB_KEY" >> "$auth"
    echo "    dodano do $auth"
  fi
}

install_key_remote() {
  local host="$1"
  echo "==> $host"
  ssh $SSH_OPTS "${DEPLOY_USER}@${host}" bash -s <<REMOTE
set -euo pipefail
PUB='$PUB_KEY'
USER='$DEPLOY_USER'
if [[ "\$USER" == "root" ]]; then HOME_DIR="/root"; else HOME_DIR="/home/\$USER"; fi
mkdir -p "\$HOME_DIR/.ssh"
chmod 700 "\$HOME_DIR/.ssh"
touch "\$HOME_DIR/.ssh/authorized_keys"
chmod 600 "\$HOME_DIR/.ssh/authorized_keys"
grep -qF "\$PUB" "\$HOME_DIR/.ssh/authorized_keys" || echo "\$PUB" >> "\$HOME_DIR/.ssh/authorized_keys"
echo "OK: authorized_keys na \$host"
REMOTE
}

echo "==> Instaluję klucz publiczny lokalnie (ten serwer)"
install_key_locally

CURRENT_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"

for host in $WORKERS; do
  [[ -z "$host" ]] && continue
  if [[ "$host" == "$CURRENT_IP" ]]; then
    echo "==> $host (lokalny — pomijam SSH)"
    continue
  fi
  install_key_remote "$host"
done

if [[ -n "$LB_HOST" && "$LB_HOST" != "$CURRENT_IP" ]]; then
  already=false
  for host in $WORKERS; do
    [[ "$host" == "$LB_HOST" ]] && already=true
  done
  if [[ "$already" == "false" ]]; then
    install_key_remote "$LB_HOST"
  fi
fi

echo ""
echo "=============================================="
echo "GOTOWE"
echo "=============================================="
echo ""
echo "1) GitHub → Settings → Secrets → Actions → New secret"
echo "   Name:  DEPLOY_SSH_KEY"
echo "   Value: (cała zawartość poniżej)"
echo ""
echo "---------- KLUCZ PRYWATNY (skopiuj do GitHub) ----------"
cat "$KEY_FILE"
echo "---------- KONIEC KLUCZA ----------"
echo ""
echo "2) Pozostałe sekrety w GitHub:"
echo "   DEPLOY_USER = $DEPLOY_USER"
echo "   LB_HOST     = (twoje lb_public_ip)"
echo "   WORKERS     = w1:IP_WORKERA"
echo ""
echo "3) Test z innej maszyny:"
echo "   ssh -i $KEY_FILE ${DEPLOY_USER}@LB_IP 'echo OK'"
echo ""
echo "UWAGA: Nie commituj klucza prywatnego do repo!"
echo "Klucz zapisany na serwerze: $KEY_FILE"
