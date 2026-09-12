#!/usr/bin/env bash
# Install a Civic Node on Raspberry Pi OS / Debian 12.
#
#   sudo ./deploy/pi/install.sh [--pack /path/to/pack]
#
# Installs into /opt/cak, /etc/cak and /var/lib/cak, creates an unprivileged
# user, and enables the service. It does not touch the network configuration and
# does not download a model.
set -euo pipefail

PREFIX=/opt/cak
CONFIG_DIR=/etc/cak
STATE_DIR=/var/lib/cak
DOC_DIR=/usr/share/doc/cak
SERVICE_USER=cak
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACK_SOURCE="${REPO_ROOT}/packs/dev-fixture"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack) PACK_SOURCE="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "This script must run as root (try: sudo $0)" >&2
  exit 1
fi

if [[ ! -f "${PACK_SOURCE}/pack.yaml" ]]; then
  echo "No pack.yaml in ${PACK_SOURCE}" >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -qq
# python3-venv for the virtualenv; the rest are WeasyPrint's runtime libraries,
# needed only for PDF output. HTML printing works without them.
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip \
  libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
  fonts-dejavu-core

echo "==> Creating ${SERVICE_USER} user"
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${STATE_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

echo "==> Installing the application into ${PREFIX}"
install -d -m 0755 "${PREFIX}" "${CONFIG_DIR}" "${DOC_DIR}"
install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_DIR}" "${STATE_DIR}/state"
python3 -m venv "${PREFIX}/venv"
"${PREFIX}/venv/bin/pip" install --upgrade --quiet pip setuptools wheel
"${PREFIX}/venv/bin/pip" install --quiet "${REPO_ROOT}[pdf]"

echo "==> Installing print templates and documentation"
install -d -m 0755 /usr/share/cak/print
cp -r "${REPO_ROOT}/print/templates" /usr/share/cak/print/
cp "${REPO_ROOT}/docs/steward-runbook.md" "${REPO_ROOT}/docs/hardware.md" "${DOC_DIR}/"

echo "==> Installing the locale pack"
if [[ -d "${STATE_DIR}/pack" ]]; then
  echo "    ${STATE_DIR}/pack already exists; leaving it alone."
  echo "    Update official files with: cak-node load-folder --config ${CONFIG_DIR}/node.toml /media/cak-usb"
else
  cp -r "${PACK_SOURCE}" "${STATE_DIR}/pack"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}/pack"
fi

echo "==> Writing ${CONFIG_DIR}/node.toml"
if [[ -f "${CONFIG_DIR}/node.toml" ]]; then
  echo "    Config already exists; leaving it alone."
else
  # Generate a steward password rather than shipping a default one. A default
  # password on an appliance is the same as no password.
  STEWARD_PASSWORD="$("${PREFIX}/venv/bin/python" -c \
    'from cak_node.config import new_steward_password; print(new_steward_password())')"
  PASSWORD_HASH="$("${PREFIX}/venv/bin/python" -c \
    "from cak_node.config import hash_password; print(hash_password('${STEWARD_PASSWORD}'))")"

  cat > "${CONFIG_DIR}/node.toml" <<EOF
locale_pack = "${STATE_DIR}/pack"

# Localhost only until someone deliberately opens this to the LAN.
bind = "127.0.0.1"
port = 8080
steward_password_hash = "${PASSWORD_HASH}"

generator = "extractive"
model = "llama3.2:3b"
ollama_host = "http://127.0.0.1:11434"
retrieval_backend = "sqlite_fts"
top_k = 6
log_queries = false

db_path = "${STATE_DIR}/state/cak.db"
changelog_path = "${STATE_DIR}/state/changelog.jsonl"
changelog_key = "${CONFIG_DIR}/steward.ed25519"
steward_inbox = "/media/cak-usb"
log_id = "caklog_$(hostname -s)"
EOF
  chmod 0640 "${CONFIG_DIR}/node.toml"
  chown root:"${SERVICE_USER}" "${CONFIG_DIR}/node.toml"

  echo
  echo "    ############################################################"
  echo "    #  Steward password: ${STEWARD_PASSWORD}"
  echo "    #  Write this down now. It is not stored anywhere in plain"
  echo "    #  text and cannot be recovered — only replaced."
  echo "    ############################################################"
  echo
fi

# The signing key lives in /etc/cak and is created by the node on first boot.
install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${CONFIG_DIR}"
chown root:"${SERVICE_USER}" "${CONFIG_DIR}"
chmod 0750 "${CONFIG_DIR}"

echo "==> Installing systemd units"
install -m 0644 "${REPO_ROOT}/deploy/pi/cak-node.service" /etc/systemd/system/
install -m 0644 "${REPO_ROOT}/deploy/pi/cak-usb-load.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cak-node.service

echo "==> Waiting for the node to come up"
for _ in $(seq 1 30); do
  if "${PREFIX}/venv/bin/python" -c \
      "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health').read()" \
      >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo
"${PREFIX}/venv/bin/cak-node" health --config "${CONFIG_DIR}/node.toml" || true
echo
echo "Civic Node installed."
echo
echo "  Kiosk:    http://127.0.0.1:8080"
echo "  Logs:     journalctl -u cak-node -f"
echo "  Verify:   ${PREFIX}/venv/bin/cak-node verify --config ${CONFIG_DIR}/node.toml"
echo "  Runbook:  ${DOC_DIR}/steward-runbook.md"
echo
echo "Next steps:"
echo "  1. Read ${DOC_DIR}/steward-runbook.md, and print a copy for the box."
echo "  2. Replace the fixture pack with your jurisdiction's official files."
echo "  3. Work through DEPLOYMENT.md before this serves anyone."
