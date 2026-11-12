#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'EOF'
Usage: generate-lan-cert.sh [LAN_IP] [OUTPUT_DIR]

Generates or replaces the default self-signed LAN certificate for MetaList.

Arguments:
  LAN_IP      Optional explicit LAN IP. If omitted, the script auto-detects one.
  OUTPUT_DIR  Optional certificate directory. Defaults to ~/MetaList/certs.
EOF
}

detect_lan_ip() {
  if [[ -n "${METALIST_LAN_IP:-}" ]]; then
    printf '%s\n' "${METALIST_LAN_IP}"
    return
  fi

  if command -v ipconfig >/dev/null 2>&1; then
    local interface
    for interface in en0 en1; do
      if ipconfig getifaddr "${interface}" >/dev/null 2>&1; then
        ipconfig getifaddr "${interface}"
        return
      fi
    done
  fi

  if command -v hostname >/dev/null 2>&1; then
    local hostname_ip
    hostname_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [[ -n "${hostname_ip}" ]]; then
      printf '%s\n' "${hostname_ip}"
      return
    fi
  fi

  if command -v ifconfig >/dev/null 2>&1; then
    local ifconfig_ip
    ifconfig_ip="$(
      ifconfig \
        | awk '/inet / && $2 != "127.0.0.1" { print $2; exit }'
    )"
    if [[ -n "${ifconfig_ip}" ]]; then
      printf '%s\n' "${ifconfig_ip}"
      return
    fi
  fi

  echo "Could not detect a LAN IP. Pass it as the first argument." >&2
  exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

LAN_IP="${1:-$(detect_lan_ip)}"
OUTPUT_DIR="${2:-${HOME}/MetaList/certs}"
CERT_PATH="${OUTPUT_DIR}/metalist-cert.pem"
KEY_PATH="${OUTPUT_DIR}/metalist-key.pem"
CONF_PATH="${OUTPUT_DIR}/metalist-cert.cnf"
HOSTNAME_VALUE="$(hostname 2>/dev/null || printf 'metalist.local')"

mkdir -p "${OUTPUT_DIR}"

cat > "${CONF_PATH}" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
x509_extensions = v3_req
distinguished_name = dn

[dn]
CN = ${LAN_IP}

[v3_req]
subjectAltName = @alt_names
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = localhost
DNS.2 = ${HOSTNAME_VALUE}
IP.1 = 127.0.0.1
IP.2 = ${LAN_IP}
EOF

openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -sha256 \
  -days 825 \
  -keyout "${KEY_PATH}" \
  -out "${CERT_PATH}" \
  -config "${CONF_PATH}" \
  -extensions v3_req

cat <<EOF
Generated:
  cert: ${CERT_PATH}
  key:  ${KEY_PATH}
  conf: ${CONF_PATH}

Run MetaList with dual HTTP/HTTPS listeners:
  metalist
  # source checkout compatibility (single namespace):
  python main.py --namespace default

From the other machine, open:
  https://${LAN_IP}:8443
EOF
