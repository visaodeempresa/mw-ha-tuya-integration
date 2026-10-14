# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) ·
Versionamento: [SemVer](https://semver.org/lang/pt-BR/).

## [0.3.0] — 2026-10-14

### Adicionado

- **Substituição Definitiva da Tuya Nativa e LocalTuya**:
  - Serviço `mw_tuya.migrate_legacy` com plano e execução atômica de troca de `entity_id`, nome, ícone, área e exposição à assistente Letícia (`should_expose: true`).
  - Herança dos identificadores canônicos sem quebra de automações, scripts ou dashboards.
  - Renomeação segura de entidades legadas para `<entity_id>_legacy` e desabilitação preventiva (100% reversível).
  - 0 pendências no painel de reparos do Home Assistant (`/config/repairs`).
- **Canal Smart Life por QR Code**:
  - Autenticação por leitura de QR Code direto no app Smart Life (mesmo mecanismo oficial da Tuya nativa).
  - Push MQTT em tempo real (`mq_connected`) sem limites de cota ou necessidade de conta developer OpenAPI.
  - Extração automatizada de `local_key` para operação Local-First (TCP 6668).
- **Thing Model v2.0**:
  - Geração dinâmica de entidades dirigida pela especificação dos DPs no catálogo da Tuya.
  - Resolução de conformidade para sensores TVOC (`volatile_organic_compounds_parts` em `ppm`), evitando conflitos de unidade no recorder.
- **Novas Plataformas**:
  - Adicionado suporte a `camera`, `siren`, `vacuum`, `event` e botões de reinício de dispositivo.

## [0.2.1] — 2026-10-13

### Corrigido

- Correção no parsing de plataformas com `_` no unique ID da migração (`binary_sensor`).
- Otimização do catálogo e leitura paralela na inicialização do coordenador.

## [0.2.0] — 2026-10-13

### Adicionado

- Suporte ao serviço de push (Message Service) em tempo real e telemetria por entidade.
- Thing Model dinâmico para controle preciso de luzes, ventiladores e seletores.



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
