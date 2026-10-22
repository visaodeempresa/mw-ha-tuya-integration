# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) ·
Versionamento: [SemVer](https://semver.org/lang/pt-BR/).

## [0.4.5] — 2026-10-22

### Corrigido

- **Sensores de Tensão (`cur_voltage`) e Corrente (`cur_current`) em "Sensores"**:
  - Ajustada a especificação de catálogo (`catalog.py`) para habilitar `cur_voltage` e `cur_current` por padrão (`enabled_default=True`).
  - Remoção automática da categoria de diagnóstico (`entity_category=None`), fazendo com que o Home Assistant agrupe a Tensão (V) e a Corrente (mA/A) no bloco principal de Sensores junto à Potência (W), e permitindo que seletores em cards (como o MW Power Button Card) identifiquem os sensores imediatamente sem necessidade de ativação manual.

## [0.4.4] — 2026-10-22

### Adicionado / Corrigido

- **Independência Total da Tuya Cloud & Resiliência Offline**:
  - `async_setup_entry` e `async_load_catalog` agora operam de forma autônoma a partir do catálogo persistido em cache (`.storage/mw_tuya_catalog_*`), não bloqueando a inicialização do Home Assistant caso a nuvem Tuya apresente erro de autenticação, cota esgotada (`60001001`), bloqueio ou ausência total de internet.
  - O polling em `_async_update_data()` ignora falhas de autenticação (`TuyaAuthError`) em modo híbrido/local, preservando as entidades locais e mantendo o poller local ativo.
- **Roteamento Local First Prioritário com Chaveamento Transparente**:
  - Toda operação de controle prioritariamente tenta envio direto via socket efêmero TCP 6668 na LAN.
  - Se a rota local falhar, chaveia de forma transparente para nuvem; se a nuvem também falhar ou recusar por cota, tenta recuperação imediata via rota local direta.
  - Transições de canal tratadas como eventos operacionais em nível `DEBUG`, eliminando ruído e IO desnecessário em logs.
- **Topologia de Rede Sub-rede 2 (192.168.2.x via wlan0 192.168.2.70)**:
  - Mapeamento definitivo e auto-provisionamento de IPs reservados DHCP em `DEFAULT_LOCAL_HOSTS` para todas as luzes e bocais do apartamento.
  - Correção de import de `DEFAULT_LOCAL_HOSTS` no coordenador prevenindo `NameError`.
  - Auto-recuperação de protocolo local (versões 3.3, 3.4 e 3.5 com fallback automático).

## [0.4.1] — 2026-10-21

### Corrigido

- **Diagnóstico das luzes LESTE e OESTE do escritório** (rastreamento integral no log do HA):
  - `OESTE` executava `light/turn_on` sem rota local (local_key inválida) e sem o canal Smart Life, caía na OpenAPI e recebia `TuyaApiError [60001001] Your controllable device pool quota is insufficient` cru — matando o serviço com 500 e quebrando as automações `LIGAR LUZES DO ESCRITÓRIO COM OCUPAÇÃO` (14 falhas) e `DESLIGAR LUZES DO ESCRITÓRIO SEM OCUPAÇÃO` (28 falhas).
  - Falha parcial no catálogo Smart Life (`network error:(-9999999) sign invalid`) apagava `sl_devices` inteiro no meio do carregamento, forçando **todos** os aparelhos para a rota limitada da OpenAPI.
- **Erros de nuvem agora chegam como erro de serviço tratável**: `async_send_device_commands` e `async_trigger_scene` embrulham `TuyaApiError`/`TuyaAuthError`/`SmartLifeError` em `HomeAssistantError` da própria HA (`homeassistant.exceptions`), com mensagem clara e sem traceback cru.
- **Canal Smart Life sobrevive a falhas parciais e a reinícios**: o cache `sl_devices`/`sl_scenes` é gravado no storage junto do catálogo e restaurado antes do `load`; os conjuntos só são descartados após uma carga completa bem-sucedida — aparelhos ficam de volta no canal sem cota OpenAPI mesmo que o CAM/QR relogue falhe.

### Notas

- A correção mora no `custom_components/mw_tuya` e o cache do canal é recarregado do `Store` no boot: após atualizar pelo HACS e reiniciar o HA, nada é perdido entre religar/desligar o Home Assistant.
- `homeassistant.exceptions.HomeAssistantError` agora é re-exportado pelo coordenador (antes era um `RuntimeError` local que a HA não reconhecia como erro de serviço).

## [0.3.1] — 2026-10-20

### Corrigido

- **Resolução de Aliases v1/v2 em Lâmpadas e Fitas LED**:
  - Mapeamento bidirecional `DP_ALIASES` entre especificações do Thing Model (`bright_value`, `temp_value`, `colour_data`, `scene_data`, `countdown`) e os códigos de plataforma (`bright_value_v2`, `temp_value_v2`, etc.).
  - Correção no `resolve_dp_id()` para identificar o ID numérico do DP local (ex.: DP 22 para brilho, DP 23 para temperatura, DP 24 para cor), prevenindo que comandos de brilho/temperatura/cor sofram desvio indevido para a nuvem Tuya.
  - Mitigação definitiva do erro `[60001001] Your controllable device pool quota is insufficient` da Tuya OpenAPI, mantendo 100% dos comandos de lâmpadas na rota local TCP 6668 com resposta instantânea.
  - Sincronização em tempo real de `dev.status` e `local_hex_len` entre códigos principais e seus respectivos aliases após pacotes locais TCP 6668.
  - Fallback de nuvem em `coordinator.py` adaptado para mapear dinamicamente os códigos v2 para o código registrado no Thing Model antes de despachar chamadas OpenAPI.

### Adicionado

- **Câmeras IP com RTSP Local LAN e tmpfs**:
  - Auto-healing de ONVIF via TCP 6668 local nas 6 câmeras IP Tuya, permitindo streaming RTSP direto na rede local com cache em tmpfs RAM sem consumo de disco.

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
