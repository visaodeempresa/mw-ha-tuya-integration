# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) ·
Versionamento: [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [0.1.0] — 2026-10-13

### Adicionado

- **Arquitetura Multi-Conta Simultânea**: suporte a múltiplas contas Tuya IoT
  ativas em paralelo no Home Assistant, cada uma com seu próprio `TokenManager`,
  `SignatureBuilder` (HMAC-SHA256) e catálogo isolado.
- **Seleção Granular de Dispositivos e Cenas em Duas Etapas**:
  1. Cadastro e validação da conta Tuya OpenAPI com extração automática de
     `local_key`, `category`, `product_id`, `sub`/`node_id` e varredura UDP LAN,
     sem criar entidades automaticamente.
  2. Seleção sob demanda na tela da integração (**Configurar**) de quais
     dispositivos e quais cenas (*Tap-to-Run*) entram no Home Assistant.
- **Motor Híbrido Local & Cloud Inteligente (Zero Duplicação)**:
  - Um único dispositivo no Device Registry do Home Assistant.
  - Prioridade automática para o protocolo local Tuya 3.3/3.4 (TCP 6668 +
    descoberta UDP 6666/6667) com *fallback* transparente para a Tuya Cloud
    OpenAPI caso o aparelho esteja ocupado ou fora de alcance local.
  - Execução direta via nuvem para recursos exclusivos Cloud (cenas Tap-to-Run,
    sensores a bateria adormecidos, sub-dispositivos remotos).
- **Plataformas Suportadas**: `switch`, `light`, `cover`, `fan`, `humidifier`,
  `climate`, `sensor`, `binary_sensor`, `button` e `scene`.
- **Serviços**: `mw_tuya.refresh_catalog`, `mw_tuya.scan_lan`,
  `mw_tuya.send_command` e `mw_tuya.trigger_scene`.
- **Marca própria** em `custom_components/mw_tuya/brand/` dentro das regras do
  `home-assistant/brands`.
