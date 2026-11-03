# CLAUDE.md — Diretrizes para Claude Code & Anthropic

Instruções para Claude Code atuando em `mw-ha-tuya-integration`:

## Filosofia e Diretrizes Principais
- **Local First Obrigatório**: Acesso direto local (TCP 6668) aos dispositivos nos IPs fixos `192.168.2.x` e `192.168.1.x`. Acesso à Cloud é fallback de última instância.
- **Air-Gapping de Dispositivos Wi-Fi**: Os dispositivos Wi-Fi da residência devem ser mantidos sem acesso à internet (perfil `NO-NET` no roteador Deco). A integração foi projetada para operar com o dispositivo com `online: false` na nuvem Tuya.
- **Ambiente Multihomed**: Home Assistant Yellow opera nas duas redes (`192.168.1.70` e `192.168.2.70`). Comandos de teste na Rede 2 partindo de estações na Rede 1 devem ser executados através da API ou SSH do Home Assistant Yellow.

## Comandos Úteis
- Testes: `.venv/bin/pytest tests/`
- Deploy HA: `scp -P 22222 -i /Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/ha-reinstall/.ssh_ha_yellow -r custom_components/mw_tuya root@192.168.1.70:/config/custom_components/`
- Reiniciar HA: `ssh -p 22222 -i /Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/ha-reinstall/.ssh_ha_yellow root@192.168.1.70 "ha core restart"`
