#!/usr/bin/env bash
# Instala a MW Tuya Integration manualmente APENAS na primeira vez no HA Yellow.
# As atualizações subsequentes são entregues automaticamente via HACS (GitHub Releases).
set -euo pipefail

HA_HOST="${HA_HOST:-192.168.1.70}"
HA_PORT="${HA_PORT:-22}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "▶ Verificando conectividade SSH com root@${HA_HOST}..."
if ssh -o ConnectTimeout=5 -p 22 root@"${HA_HOST}" "true" 2>/dev/null; then
  HA_PORT=22
elif ssh -o ConnectTimeout=5 -p 22222 root@"${HA_HOST}" "true" 2>/dev/null; then
  HA_PORT=22222
else
  echo "✖ SSH indisponível em ${HA_HOST} (portas 22 e 22222). Certifique-se de que o add-on Terminal & SSH está iniciado."
  exit 1
fi

echo "▶ Instalando custom_components/mw_tuya em root@${HA_HOST}:/config/custom_components/mw_tuya (porta ${HA_PORT})..."
ssh -p "${HA_PORT}" root@"${HA_HOST}" "mkdir -p /config/custom_components && rm -rf /config/custom_components/mw_tuya"
scp -P "${HA_PORT}" -r "${REPO_ROOT}/custom_components/mw_tuya" root@"${HA_HOST}":/config/custom_components/mw_tuya

echo "▶ Reiniciando o Home Assistant Core para carregar a integração..."
ssh -p "${HA_PORT}" root@"${HA_HOST}" "ha core restart"

echo "✔ Primeira instalação concluída! Adicione o repositório https://github.com/visaodeempresa/mw-ha-tuya-integration no HACS para receber notificações automáticas das próximas releases."
