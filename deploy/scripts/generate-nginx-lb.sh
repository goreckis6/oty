#!/usr/bin/env bash
# Generuje nginx config dla LB z listy workerów.
# WORKERS="w1:10.0.0.1,w2:10.0.0.2" ./deploy/scripts/generate-nginx-lb.sh > /tmp/ytdown-lb.conf
set -euo pipefail

WORKERS="${WORKERS:?WORKERS required, format w1:IP,w2:IP}"

map_block=""
upstream_block=""

IFS=',' read -ra entries <<< "$WORKERS"
for entry in "${entries[@]}"; do
  wid="${entry%%:*}"
  ip="${entry#*:}"
  map_block+="    ~/(?:status|file)/${wid}-  ${ip}:8082;"$'\n'
  upstream_block+="    server ${ip}:8082 max_fails=2 fail_timeout=10s;"$'\n'
done

cat <<EOF
map \$request_uri \$job_worker {
${map_block}    default                "";
}

upstream ytdown_pool {
${upstream_block}}

server {
    listen 80;
    server_name _;

    client_max_body_size 10m;

    location ~ ^/api/download/(status|file)/ {
        if (\$job_worker = "") { return 404; }
        proxy_pass http://\$job_worker;
        proxy_http_version 1.1;
        proxy_read_timeout 3600s;
        proxy_buffering off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location / {
        proxy_pass http://ytdown_pool;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF
