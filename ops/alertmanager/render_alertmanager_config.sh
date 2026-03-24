#!/bin/sh
set -eu

OUT_FILE="${1:-/tmp/alertmanager.yml}"

WEBHOOK_URL="${OPENMIURA_ALERT_WEBHOOK_URL:-}"
SLACK_WEBHOOK="${OPENMIURA_ALERT_SLACK_WEBHOOK_URL:-}"
SLACK_CHANNEL="${OPENMIURA_ALERT_SLACK_CHANNEL:-#openmiura-alerts}"
EMAIL_ENABLED="false"
if [ -n "${OPENMIURA_ALERT_EMAIL_TO:-}" ] && [ -n "${OPENMIURA_ALERT_EMAIL_FROM:-}" ] && [ -n "${OPENMIURA_ALERT_EMAIL_SMARTHOST:-}" ]; then
  EMAIL_ENABLED="true"
fi

mkdir -p "$(dirname "$OUT_FILE")"
{
  echo 'global:'
  echo '  resolve_timeout: 5m'
  if [ "$EMAIL_ENABLED" = "true" ]; then
    echo '  smtp_smarthost: '"${OPENMIURA_ALERT_EMAIL_SMARTHOST}"
    echo '  smtp_from: '"${OPENMIURA_ALERT_EMAIL_FROM}"
    if [ -n "${OPENMIURA_ALERT_EMAIL_AUTH_USERNAME:-}" ]; then
      echo '  smtp_auth_username: '"${OPENMIURA_ALERT_EMAIL_AUTH_USERNAME}"
    fi
    if [ -n "${OPENMIURA_ALERT_EMAIL_AUTH_PASSWORD:-}" ]; then
      echo '  smtp_auth_password: '"${OPENMIURA_ALERT_EMAIL_AUTH_PASSWORD}"
    fi
    if [ -n "${OPENMIURA_ALERT_EMAIL_REQUIRE_TLS:-}" ]; then
      echo '  smtp_require_tls: '"${OPENMIURA_ALERT_EMAIL_REQUIRE_TLS}"
    fi
  fi
  echo ''
  echo 'route:'
  echo '  receiver: default-log'
  echo '  group_by: [alertname, service, severity]'
  echo '  group_wait: 15s'
  echo '  group_interval: 1m'
  echo '  repeat_interval: 2h'
  echo '  routes:'
  if [ -n "$WEBHOOK_URL" ]; then
    echo '    - matchers:'
    echo '        - severity="critical"'
    echo '      receiver: webhook-primary'
    echo '      continue: true'
  fi
  if [ -n "$SLACK_WEBHOOK" ]; then
    echo '    - matchers:'
    echo '        - severity=~"warning|critical"'
    echo '      receiver: slack-primary'
    echo '      continue: true'
  fi
  if [ "$EMAIL_ENABLED" = "true" ]; then
    echo '    - matchers:'
    echo '        - severity="critical"'
    echo '      receiver: email-primary'
    echo '      continue: true'
  fi
  echo ''
  echo 'receivers:'
  echo '  - name: default-log'
  if [ -n "$WEBHOOK_URL" ]; then
    echo '  - name: webhook-primary'
    echo '    webhook_configs:'
    echo '      - url: '"${WEBHOOK_URL}"
    echo '        send_resolved: true'
    if [ -n "${OPENMIURA_ALERT_WEBHOOK_HTTP_CONFIG_BEARER_TOKEN:-}" ]; then
      echo '        http_config:'
      echo '          bearer_token: '"${OPENMIURA_ALERT_WEBHOOK_HTTP_CONFIG_BEARER_TOKEN}"
    fi
  fi
  if [ -n "$SLACK_WEBHOOK" ]; then
    echo '  - name: slack-primary'
    echo '    slack_configs:'
    echo '      - api_url: '"${SLACK_WEBHOOK}"
    echo '        channel: '"${SLACK_CHANNEL}"
    echo '        send_resolved: true'
    echo '        title: "[{{ .Status | toUpper }}] {{ .CommonLabels.alertname }}"'
    echo '        text: >-'
    echo '          {{ range .Alerts }}{{ .Annotations.summary }} - {{ .Annotations.description }}{{ "\n" }}{{ end }}'
  fi
  if [ "$EMAIL_ENABLED" = "true" ]; then
    echo '  - name: email-primary'
    echo '    email_configs:'
    echo '      - to: '"${OPENMIURA_ALERT_EMAIL_TO}"
    echo '        send_resolved: true'
  fi
} > "$OUT_FILE"

printf 'Rendered Alertmanager config to %s\n' "$OUT_FILE"
