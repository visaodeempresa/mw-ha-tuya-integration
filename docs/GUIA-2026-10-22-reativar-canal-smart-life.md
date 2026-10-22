# MW Tuya — Reativar canal Smart Life e fechar a cura (guia com checkboxes)

Gerado em 2026-10-22 a partir do diagnóstico do dia. A integração MW Tuya
**v0.4.3 já está rodando no HA** e o wrap de erro funciona — o que falta é
**assento**: o canal Smart Life (sem cota) está vazio e os aparelhos caem no
OpenAPI (com cota → `[60001001]`).

## Diagnóstico de hoje — o que já está bom

| Verificação | Resultado |
|---|---|
| Manifest rodando | ✅ 0.4.3 (0.3.1 antes) |
| Erro no log | ✅ embrulhado («Cota Tuya Cloud insuficiente … acesso Local indisponível») |
| Rota local (TCP 6668) | ✅ 50 IPs mapeados, vários aparelhos com `local_ok` |
| Canal Smart Life (`sl_devices`) | ⚠️ **0** — vazio |
| Canal Smart Life (`sl_scenes`) | ⚠️ **0** — vazio |
| Log | ⚠️ `falha parcial no catálogo Smart Life: sign invalid` (recorrente) |
| Aparelho alvo (OESTE) | ⚠️ `local_fail` no stats → cai na OpenAPI → quota `[60001001]` |

**Por isso as luzes falham:** sem rota local (key/IP vencidos no OESTE) e sem
Smart Life (assento sem cota), o `turn_off` restou no OpenAPI do Cloud Dev —
e a cota do pool não tem vaga para 133 aparelhos. Reconectar o Smart Life
devolve o canal sem cota + push em tempo real.

---

## Fase A — Reconectar o canal Smart Life (no app + no HA)

1. [ ] No app **Smart Life** (ou Tuya Smart): **Eu → Configurações → Conta e
       Segurança → User Code** — copie o código.
2. [ ] No navegador do computador, abra o Home Assistant: **Configurações →
       Dispositivos e serviços → MW Tuya** → clique em **Configurar**.
3. [ ] No menu que abre («Gerenciar Conta Tuya»), clique em
       **Conectar Smart Life (QR Code) — controle sem cota e push em tempo real**.
4. [ ] No passo «Conta Smart Life», **cole o User Code** copiado do app e
       clique em **Enviar**.
5. [ ] No passo **«Escaneie o QR Code»**: abra o app Smart Life → ícone de
       leitura de QR (canto superior direito) → escaneie o QR exibido no HA →
       **confirme o login no app**.
6. [ ] De volta ao HA, clique em **Enviar** no passo do QR para fechar.

## Fase B — Recarregar o catálogo (povoar o cache sem cota)

7.  [ ] Configurar a conta MW Tuya novamente (menu «Gerenciar Conta Tuya»).
8.  [ ] Clique em **Atualizar Catálogo, Local Keys e Varredura LAN**.
9.  [ ] Aguarde terminar a varredura (catálogo atual: 133 aparelhos, 173 cenas).
      O passo atualiza também as **local keys** — é o que corrige o
      `local_fail` do OESTE se o segredo local venceu.

## Fase C — Verificação (termômetros)

10. [ ] Ligar e desligar **light.oeste** pela tela/app do HA — deve mudar de
        estado **sem erro** (o `turn_off` por REST deixa de dar HTTP 500).
11. [ ] Ligar e desligar **light.leste** pela tela — mesma verificação.
12. [ ] Deixar a automação **«LIGAR LUZES DO ESCRITÓRIO COM OCUPAÇÃO»**
        disparar naturalmente — sem erro no log.
13. [ ] No log do HA (Configurações → Sistema → Logs), **nenhuma entrada
        nova** com `sign invalid` ou `60001001` depois do horário da reconexão.
14. [ ] Extras (me chamar para conferir): `sl_devices > 0` no arquivo de
        diagnóstico da integração (v0.4.1+ persiste no Store) e entrada no
        logbook da luz mostrando troca de estado (prova de que o aparelho
        respondeu).

---

## Se algo falhar nesta rodada

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| QR não empareilha (app não confirma) | login do app em outra conta/região | confirme que o app mostra a mesma casa/aparelhos da Conta Principal e repita o passo 5 |
| «sign invalid» reaparece no log após reconexão | sessão QR venceu de novo | repetir Fase A do zero, do passo 1 |
| Luz ainda falha com quota | cache do catálogo não salvou (carga parcial) | repetir passo 8 (Atualizar Catálogo) — o v0.4.1+ só salva cache de cargas **completas** |
| Luz ainda falha **sem** mensagem de quota | o aparelho trocou de Wi-Fi / IP mudou | conferir na tela que o aparelho está on-line no app e que o roteador não trocou o IP dele |
| Nada acima resolveu | idoso não identificado | me chamar que rastreio o traceback no log de novo |

**Referências:** entity_id de prova `light.leste` / `light.oeste`; aparelho
OESTE id `ebe6aae597f0c6ed96iwaq`; automações âncora «LIGAR LUZES DO
ESCRITÓRIO COM OCUPAÇÃO» e «DESLIGAR LUZES DO ESCRITÓRIO SEM OCUPAÇÃO».
