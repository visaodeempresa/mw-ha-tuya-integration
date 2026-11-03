# Arquitetura Air-Gapped Wi-Fi & Estratégia de Soberania Local

> **Documento Oficial de Engenharia e Diretriz Estratégica**  
> **Data:** 03 de Novembro de 2026  
> **Escopo:** MW Tuya Integration (`mw_tuya`) & Home Assistant Yellow CM4  

---

## 1. Contexto e Motivação Estratégica

Em instalações inteligentes com dezenas ou centenas de dispositivos baseados no ecossistema Tuya (lâmpadas, fitas LED, tomadas, purificadores, umidificadores e atuadores), a dependência de servidores de nuvem apresenta riscos severos:
1. **Limitações e Exaustão de Cotas:** Contas de desenvolvedor na Tuya IoT Platform impõem restrições de cota para o pool de dispositivos controláveis (ex: erro `[60001001] Your controllable device pool quota is insufficient`).
2. **Latência Elevada e Interrupções Externas:** Chamadas à nuvem dependem da integridade do link WAN e dos servidores globais da Tuya, introduzindo latências de 300 ms a 2000 ms.
3. **Privacidade e Segurança:** Dispositivos IoT com acesso irrestrito à internet realizam envio contínuo de telemetria externa e ficam suscetíveis a atualizações remotas de firmware (OTA) que podem remover recursos locais ou revogar chaves criptográficas (`local_key`).

### A Diretriz Estratégica Mandatória
> **Isolar ao máximo da internet todos os dispositivos Wi-Fi da residência, garantindo controle puramente local (LAN First) pelo Home Assistant Yellow.**
> - **Fase 1 (Prioritária):** Todos os mais de **70 dispositivos Wi-Fi da Rede 2 (`192.168.2.x`)**.
> - **Fase 2:** Quase **20 dispositivos Wi-Fi da Rede 1 (`192.168.1.x`)**.

---

## 2. Topologia de Rede e Isolamento no Roteador (TP-Link Deco)

### Como funciona o Air-Gapping no Roteador
* **Perfil "NO-NET" (Controle dos Pais / Hora de Dormir o Dia Inteiro):**
  * Cada dispositivo Wi-Fi é cadastrado no Deco com endereço MAC reservado e IP DHCP estático na faixa `192.168.2.x` (ou `192.168.1.x`).
  * O roteador Deco bloqueia todo o tráfego de entrada e saída destinado à WAN (internet).
  * O tráfego de Camada 2 (Ethernet/ARP) e Camada 3 (roteamento local TCP/UDP) na LAN interna **continua 100% ativo e desbloqueado**.

### Papel Multihomed do Home Assistant Yellow
* O Home Assistant Yellow opera simultaneamente em duas interfaces de rede:
  1. `end0` (Ethernet cabo): IP `192.168.1.70/24` — Conexão principal à Rede 1.
  2. `wlan0` (Wi-Fi interno): IP `192.168.2.70/24` (SSID `Ark@Three#3`) — Conexão dedicada à Rede 2.
* Como o Home Assistant possui perna física direta dentro da Rede 2, ele trafega pacotes TCP na porta `6668` diretamente para os dispositivos, com latência típica de **40 ms a 60 ms**, sem passar por roteadores externos ou conexões de internet.

---

## 3. Comportamento do Protocolo Local Tuya sem Internet

Ao cortar a conexão de internet de um dispositivo Tuya:
1. **Status na Tuya Cloud:** O servidor da Tuya detecta o encerramento do túnel MQTT/TLS e reporta `"online": false`.
2. **Porta Local TCP 6668:** O servidor embutido do chip (ESP32/ESP8266/RTL8710) continua escutando na porta local TCP `6668`.
3. **Sessão Criptográfica:** A chave simétrica (`local_key` de 16 bytes) fica gravada na memória flash não-volátil do aparelho. A negociação de sessão local (AES-GCM na v3.5 ou AES-ECB na v3.3/v3.4) ocorre diretamente entre o Home Assistant e o aparelho.
4. **Resiliência a Quedas:** A integração `mw_tuya` mantém os sockets abertos (`client pooling`), grava em cache a versão funcional (`v3.3`, `v3.4` ou `v3.5`) e nunca bloqueia requisições localmente.

---

## 4. Resultados Comprovados em Produção

* **Luz da Mesa do Quarto (`192.168.2.77`, MAC `38-2c-e5-54-10-c5`):**
  * Isolada da internet no perfil Deco NO-NET.
  * Status na nuvem: `"online": false`.
  * Controle local pelo Home Assistant: **100% funcional** via protocolo v3.5 (latência de 55 ms).
* **Lâmpadas e Fitas do Escritório (6 Dispositivos):**
  * `BIBLIOTECH` (`192.168.2.63`, MAC `7C-F6-66-BB-48-14`) — v3.3 OK.
  * `MÍSTICA` (`192.168.2.14`, MAC `7C-F6-66-BB-3E-C5`) — v3.3 OK.
  * `OESTE` (`192.168.2.135`, MAC `38-1F-8D-CC-36-9E`) — v3.3 OK.
  * `LESTE` (`192.168.2.136`, MAC `38-1F-8D-D2-8B-05`) — v3.3 OK.
  * `LED DA JANELA` (`192.168.2.139`, MAC `7C-F6-66-BB-44-B5`) — v3.4 OK.
  * `LED DO ESPELHO` (`192.168.2.140`, MAC `7C-F6-66-BB-B0-59`) — v3.3 OK.
* **Grupos de Iluminação (`mw-tab-lights-card`):**
  * `light.coluninhas` (LESTE + OESTE): ~120 ms.
  * `light.estantes` (BIBLIOTECH + MÍSTICA): ~130 ms.
  * `light.led_da_mesa` (LED DO ESPELHO + LED DA JANELA): ~125 ms.
  * **Zero chamadas para a Tuya Cloud (`cloud_hits: 0`)**.
