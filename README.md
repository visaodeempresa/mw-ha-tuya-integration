# MW Tuya Integration (`mw_tuya`)

Integração híbrida **Local & Cloud**, **Multi-Conta Simultânea** e com **Seleção Granular de Dispositivos e Cenas** para o Home Assistant, projetada para ambientes de grande porte (200+ dispositivos e 100+ cenas) sem poluição de entidades nem duplicação de aparelhos.

---

## Por que esta integração existe?

A integração nativa Tuya do Home Assistant e o LocalTuya tradicional apresentam três limitações severas em instalações residenciais grandes:

| Limitação na Abordagem Tradicional | Solução na **MW Tuya Integration (`mw_tuya`)** |
| :--- | :--- |
| **1. Poluição de Entidades (Tudo ou Nada)**: Ao autenticar uma conta com 200+ dispositivos e 100+ cenas, centenas de entidades desnecessárias são despejadas de uma vez no Home Assistant. | **Fluxo em Duas Etapas (Catálogo → Seleção Sob Demanda)**: Adicionar a conta apenas valida as credenciais, coleta todas as `local_key` e escaneia a LAN (criando **zero** dispositivos inicialmente). Depois, no botão **Configurar** da conta, você marca exatamente quais *Devices* e quais *Cenas* entram no HA. |
| **2. Uma Conta por Vez / Conflito de Sessão**: Não permite operar múltiplas contas Tuya em paralelo de forma limpa. | **Multi-Conta Simultânea**: Cada conta adicionada possui seu próprio `MwTuyaCoordinator`, `SignatureBuilder` (HMAC-SHA256) e `TokenManager` isolados. Você pode manter 2, 3 ou mais contas ativas simultaneamente. |
| **3. Duplicação Cloud vs Local (`LocalTuya`)**: Usar Tuya Cloud + LocalTuya duplica dispositivos (`"Aparelho"` e `"Aparelho LOCAL"`) e entidades. | **Roteador Híbrido Unificado (`Local First + Cloud Fallback`)**: Cada aparelho selecionado gera **um único dispositivo** no Home Assistant. Comandos priorizam automaticamente o protocolo local **TCP 6668 (v3.3/v3.4)** (~60–150 ms) e caem de forma transparente para a **Tuya Cloud OpenAPI** quando necessário, enquanto recursos exclusivos de nuvem (como cenas *Tap-to-Run* e sensores adormecidos) usam a nuvem diretamente. |

---

## Como Funciona o Fluxo de Uso

### Etapa 1 — Adicionar uma Conta Tuya IoT
1. Vá em **Configurações → Dispositivos e Serviços → Adicionar Integração → MW Tuya Integration**.
2. Informe:
   - **Nome da Conta** (ex.: `Casa Principal`, `Escritório`)
   - **Região do Data Center** (`us`, `eu`, `cn`, `in`, `sg`, `we`, `ue`)
   - **Access ID / Client ID** (do projeto na Tuya IoT Platform)
   - **Access Secret / Client Secret**
   - **UID** do aplicativo Tuya / Smart Life
3. A integração valida a conta, extrai e armazena todas as `local_key`, descobre os IPs na LAN via broadcast UDP (`6666`/`6667`) e cataloga todas as cenas *Tap-to-Run* das casas vinculadas.

### Etapa 2 — Selecionar Dispositivos, Cenas e Modo Híbrido
Na tela da integração **MW Tuya Integration**, clique em **Configurar** ao lado da conta desejada:
- **Selecionar Dispositivos que entram no Home Assistant**: Lista completa com nome, categoria e indicador `[Local+Cloud (IP)]` ou `[Cloud]`. Apenas os marcados são criados no HA (desmarcar remove imediatamente do *Device Registry*).
- **Selecionar Cenas (Tap-to-Run) que entram no Home Assistant**: Marque apenas as cenas que deseja expor como entidades `scene.*`.
- **Configurar Modo Híbrido (Local & Cloud) e IPs Locais**: Escolha entre `hybrid_local_first` (padrão), `local_only` ou `cloud_only` e ajuste IPs locais se desejar.
- **Atualizar Catálogo, Local Keys e Varredura LAN**: Reconsulta a nuvem e o broadcast UDP sem precisar recriar a conta.

---

## Instalação via HACS e Esteira DevOps

1. Adicione `https://github.com/visaodeempresa/mw-ha-tuya-integration` como repositório customizado (categoria **Integration**) no **HACS**.
2. Este repositório utiliza branches padronizadas (`develop` → `main`) e automação de releases (`.github/workflows/auto-release.yml` e `ci.yml`):
   - Todo merge na `main` que altere `custom_components/mw_tuya/**` calcula automaticamente a próxima versão semântica (`feat:` → minor, `fix:` → patch, `BREAKING` → major), atualiza o `manifest.json` e o `pyproject.toml`, assina a tag `vX.Y.Z`, sincroniza de volta com `develop` e publica a Release com `mw_tuya.zip`.
   - O **HACS** detecta a nova tag/release e sinaliza a atualização diretamente nas notificações do Home Assistant.
