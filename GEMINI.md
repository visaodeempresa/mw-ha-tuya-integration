# GEMINI.md — Diretrizes para Google Gemini & Antigravity (MW Tuya Integration)

Este documento define as regras arquiteturais, diretrizes de desenvolvimento e invariantes obrigatórias para agentes **Google Gemini**, **Antigravity (AGY)** e ambientes de IA autônomos que operam na integração `mw_tuya`.

---

## 1. Visão Geral da Arquitetura

O **MW Tuya Integration (`mw_tuya`)** é um componente customizado para o Home Assistant focado em estabilidade, soberania de dados e velocidade ultrabaixa (<60 ms):
* **Roteador Híbrido (`hybrid_local_first`)**: Toda requisição prioriza estritamente a porta TCP **6668** na rede local. A Tuya Cloud OpenAPI é apenas um fallback de contingência para recursos exclusivos de nuvem.
* **Isolamento de Internet (Air-Gapping de IoT)**: Dispositivos Wi-Fi operam sem acesso à internet (WAN bloqueada no roteador Deco via perfil `NO-NET`), comunicando-se exclusivamente com o Home Assistant Yellow via sub-redes locais.
* **Topologia de Rede Multihomed**:
  * **Home Assistant Yellow**: Multihomed (`192.168.1.70` via Ethernet `end0` e `192.168.2.70` via Wi-Fi `wlan0` no SSID `Ark@Three#3`).
  * **Rede 2 (`192.168.2.x`)**: Sub-rede Wi-Fi dedicada para mais de 70 dispositivos IoT (lâmpadas, fitas LED, tomadas, purificadores, umidificadores).
  * **Rede 1 (`192.168.1.x`)**: Sub-rede principal cabeada com quase 20 dispositivos IoT de infraestrutura.
  * **Estações de Desenvolvimento (ex: Mac)**: Geralmente conectadas apenas à Rede 1 (`192.168.1.x`). Comunicação com a Rede 2 deve ser realizada via SSH ou API do Home Assistant Yellow.

---

## 2. Diretriz Estratégica Obrigatória (Soberania IoT)

> [!IMPORTANT]
> **DIRETRIZ DE ARQUITETURA AIR-GAPPED:**
> Devemos colocar ao máximo os dispositivos Wi-Fi **SEM INTERNET** e com **CONTROLE 100% LOCAL** pelo Home Assistant Yellow.
> - **Fase 1 (Prioridade Absoluta)**: Todos os mais de **70 dispositivos da Rede 2 (`192.168.2.x`)**.
> - **Fase 2**: Quase **20 dispositivos da Rede 1 (`192.168.1.x`)**.
> 
> Dispositivos no perfil Deco `NO-NET` continuam 100% operacionais na LAN, eliminando riscos de vazamento de telemetria, updates indesejados de firmware (OTA) e bloqueios de cota externa.

---

## 3. Invariantes de Código e Regras Estritas

1. **PROIBIDO Sintetizar Bloqueios de Cota Localmente:**
   - Nunca reimplementar cooldowns artificiais em caso de erro da Tuya Cloud (`[60001001]`).
   - Se a cota da nuvem estiver esgotada ou a internet estiver bloqueada, o tráfego local deve fluir sem nenhum obstáculo.
   - Só abortar a ação e avisar ao usuário caso **AMBOS** os acessos (Local e Nuvem) falhem fisicamente.
2. **Auto-Recuperação Completa de Versão (`3.5`, `3.4`, `3.3`):**
   - Toda rotina de envio de comandos (`async_set_dps`) e consulta (`async_get_dps`) deve ser resiliente e iterar de forma adaptativa por todas as versões suportadas do protocolo Tuya.
   - Uma vez identificada a versão funcional, persistir em cache e em `lan_map` para garantir latência sub-60 ms.
3. **Isolamento Estrito de Datapoints:**
   - Jamais cruzar aliases de DPs com funções distintas (ex: `switch` [DP 1 para ligar aparelho] e `switch_led` [DP 5 para ligar luz/noturno]).
4. **Preservação do Socket TCP (LWIP):**
   - Comandos sem ACK de retorno não devem derrubar o socket TCP, prevenindo o lockout de reconexão do stack LWIP dos chips Tuya/Espressif.

---

## 4. Comandos e Testes do Harness

* **Execução de Testes Unitários**:
  ```bash
  .venv/bin/pytest tests/ -v
  ```
* **Deploy no Home Assistant Yellow**:
  ```bash
  scp -P 22222 -i /Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/ha-reinstall/.ssh_ha_yellow -r custom_components/mw_tuya root@192.168.1.70:/config/custom_components/
  ssh -p 22222 -i /Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/ha-reinstall/.ssh_ha_yellow root@192.168.1.70 "ha core restart"
  ```
