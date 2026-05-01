#!/usr/bin/env bash
set -Eeuo pipefail

DEFAULT_UPSTREAM="https://media.misaya.org"
WEBROOT="/var/www/misaya-certbot"
MAP_CONF="/etc/nginx/conf.d/misaya-stream-proxy-map.conf"

usage() {
  cat <<'USAGE'
Usage:
  sudo bash setup_stream_reverse_proxy.sh <proxy-domain> [upstream]

Examples:
  sudo bash setup_stream_reverse_proxy.sh jp.misaya.org
  sudo LE_EMAIL=admin@example.com bash setup_stream_reverse_proxy.sh jp.misaya.org https://media.misaya.org

Notes:
  - DNS for <proxy-domain> must already point to this server.
  - [upstream] defaults to https://media.misaya.org.
  - Put https://<proxy-domain> into the miniapp line config after this succeeds.
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      exec sudo -E bash "$0" "$@"
    fi
    die "Please run as root, or install sudo."
  fi
}

normalize_upstream() {
  local upstream="$1"
  if [[ "${upstream}" != http://* && "${upstream}" != https://* ]]; then
    upstream="https://${upstream}"
  fi
  upstream="${upstream%/}"
  echo "${upstream}"
}

validate_domain() {
  local domain="$1"
  [[ -n "${domain}" ]] || die "Missing proxy-domain."
  [[ "${domain}" != *"://"* ]] || die "proxy-domain must be a domain only, not a URL."
  [[ "${domain}" != *"/"* ]] || die "proxy-domain must not contain a path."
  [[ "${domain}" =~ ^[A-Za-z0-9.-]+$ ]] || die "Invalid proxy-domain: ${domain}"
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y nginx certbot curl ca-certificates
    return
  fi
  die "Only Debian/Ubuntu apt-get systems are supported by this script."
}

reload_nginx() {
  nginx -t
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable nginx >/dev/null 2>&1 || true
    systemctl reload nginx 2>/dev/null || systemctl restart nginx
    return
  fi
  service nginx reload 2>/dev/null || nginx -s reload 2>/dev/null || nginx
}

write_map_conf() {
  cat > "${MAP_CONF}" <<'EOF'
map $http_upgrade $misaya_stream_connection_upgrade {
    default upgrade;
    '' close;
}
EOF
}

write_http_challenge_conf() {
  local domain="$1"
  local conf="/etc/nginx/sites-available/${domain}.conf"

  mkdir -p "${WEBROOT}"
  cat > "${conf}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${domain};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }

    location / {
        return 200 "misaya stream proxy bootstrap\n";
        add_header Content-Type text/plain;
    }
}
EOF
  ln -sfn "${conf}" "/etc/nginx/sites-enabled/${domain}.conf"
  rm -f /etc/nginx/sites-enabled/default
}

request_certificate() {
  local domain="$1"
  local email="${LE_EMAIL:-}"
  local contact_args=(--register-unsafely-without-email)

  if [[ -n "${email}" ]]; then
    contact_args=(--email "${email}")
  fi

  certbot certonly \
    --webroot \
    -w "${WEBROOT}" \
    -d "${domain}" \
    --agree-tos \
    --non-interactive \
    "${contact_args[@]}"
}

write_proxy_conf() {
  local domain="$1"
  local upstream="$2"
  local conf="/etc/nginx/sites-available/${domain}.conf"

  cat > "${conf}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${domain};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${domain};

    ssl_certificate /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    client_max_body_size 0;
    proxy_max_temp_file_size 0;

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }

    location / {
        proxy_pass ${upstream};
        proxy_http_version 1.1;

        proxy_set_header Host \$proxy_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Original-Host \$host;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$misaya_stream_connection_upgrade;

        proxy_set_header Range \$http_range;
        proxy_set_header If-Range \$http_if_range;
        proxy_force_ranges on;

        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;

        proxy_connect_timeout 30s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
        send_timeout 3600s;

        proxy_ssl_server_name on;
        proxy_ssl_name \$proxy_host;
    }
}
EOF
}

allow_firewall_ports() {
  if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi "Status: active"; then
    ufw allow 80/tcp >/dev/null || true
    ufw allow 443/tcp >/dev/null || true
  fi
}

main() {
  need_root "$@"

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  local domain="${1:-}"
  local upstream
  upstream="$(normalize_upstream "${2:-${DEFAULT_UPSTREAM}}")"

  validate_domain "${domain}"

  echo "Proxy domain : ${domain}"
  echo "Upstream     : ${upstream}"

  install_packages
  allow_firewall_ports
  write_map_conf
  write_http_challenge_conf "${domain}"
  reload_nginx
  request_certificate "${domain}"
  write_proxy_conf "${domain}" "${upstream}"
  reload_nginx

  echo
  echo "Done."
  echo "Line URL : https://${domain}"
  echo "Upstream : ${upstream}"
  echo "Config   : /etc/nginx/sites-available/${domain}.conf"
}

main "$@"
