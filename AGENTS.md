# AGENTS.md — Regras Universais para Agentes de IA (Multi-Agent & OpenCode)

Este arquivo define os padrões universais para qualquer agente de IA (Gemini, Claude, Cursor, Copilot, Codex, Windsurf) trabalhando no repositório `mw-ha-tuya-integration`.

---

## 1. Princípios Arquiteturais Inegociáveis

1. **Prioridade Local-First Estrita:**
   - O Home Assistant Yellow se comunica diretamente com os aparelhos na porta TCP **6668** via protocolo Tuya cifrado (AES-GCM na v3.5, AES-ECB na v3.3/v3.4).
   - O uso da nuvem deve ser raro, esporádico e indesejável.
2. **Diretriz de Soberania (Air-Gapping de Dispositivos Wi-Fi):**
   - Todos os dispositivos Wi-Fi devem ser isolados da internet (WAN desativada no roteador via perfil Deco `NO-NET`).
   - Escopo: mais de 70 dispositivos na Rede 2 (`192.168.2.x`) e quase 20 na Rede 1 (`192.168.1.x`).
   - O Home Assistant é multihomed (`192.168.1.70` e `192.168.2.70`), garantindo controle local contínuo mesmo com WAN desconectada.
3. **Cota e Cooldown:**
   - Proibido qualquer bloqueio de cota sintético ou artificial localmente. Cota esgotada na Tuya Cloud (`60001001`) jamais pode impedir o tráfego local.

---

## 2. Padrões de Código e Manipulação de DPs

* **Semântica dos Datapoints (DPs):**
  - Todo DP possui tipo estrito (bool, enum, value, string, raw).
  - Nunca acoplar `switch` (força do dispositivo) com `switch_led` (luz noturna ou iluminação decorativa).
* **Versionamento do Protocolo Tuya:**
  - `v3.3`: Formato legado `0x55AA`, AES-128-ECB.
  - `v3.4`: Handshake de sessão (`0x03`), AES-128-ECB negociado.
  - `v3.5`: Formato novo `0x6699`, AES-128-GCM com IV de 12 bytes e tag de 16 bytes.
  - O fallback deve sempre testar a sequência completa: `[versão atual, 3.5, 3.4, 3.3]`.

---

## 3. Checklist Pré-Commit e Entrega

- [ ] Testes unitários passando (`pytest tests/`).
- [ ] Versionamento semântico respeitado em `manifest.json`, `pyproject.toml` e `CHANGELOG.md`.
- [ ] Nenhuma credencial ou token exposto no git (`.env` sempre no `.gitignore`).
- [ ] Alterações sincronizadas entre as branches `develop` e `main`.
