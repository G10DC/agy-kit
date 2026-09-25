# Guida a UltraCode in Antigravity (`agy`)

UltraCode è la modalità di Antigravity a massima intensità: ragionamento profondo, esecuzione autonoma e un protocollo rigido contro le allucinazioni. Si ispira alla modalità *Ultracode* di Claude Code.

> **Regole:** l'unica fonte è la skill [`skills/ultracode/SKILL.md`](../skills/ultracode/SKILL.md), installata in `~/.gemini/config/skills/ultracode/`. Questa guida spiega come usarla e non ne ricopia il testo.

---

## 1. Componenti

| Componente | Ruolo |
|---|---|
| `ultracode` / `agy-ultracode` | Avvia `agy` con il modello principale, `--effort high` e, se configurato, senza richieste di permesso |
| Skill `ultracode` | Contiene la divisione dei ruoli tra i modelli, la tassonomia a 5 livelli, le 6 Iron Rules, la sequenza Plan → Reproduce → Build → Verify, la revisione da 3 prospettive e la verifica deterministica |
| `/ultracode` | Comando che carica la skill. Lo script lo mette sempre in testa al prompt, perché in Antigravity le skill sono "on demand" e la sola parola chiave non garantisce che vengano caricate |
| `~/.config/agy-kit/config` | Modello, effort e permessi (vedi il README) |

## 2. Ripartizione dei modelli

| Ruolo | Modello | Come viene imposto |
|---|---|---|
| Agente principale: architettura, sintesi, deduzioni, verifica | `AGY_KIT_MODEL` (default `gemini-3.1-pro`) con `--effort high` | Flag della CLI, quindi in modo deterministico |
| Sotto-agenti: scansione, lettura massiva, estrazione verbatim, test | Flash | La skill prescrive `invoke_subagent` con modello `flash`. Il default del tool è `inherit`, cioè Pro |
| Vietato | `flash_lite` | Regola della skill |

Il modello dei sotto-agenti viene scelto dall'agente principale seguendo la skill: non esiste un flag della CLI che lo imponga.

## 3. Uso

```bash
ultracode                                   # sessione interattiva
ultracode "risolvi il memory leak nel worker websocket"
ultracode -p "esegui un security audit sugli endpoint di autenticazione"   # non interattivo
ultracode -c                                # riprende l'ultima conversazione (flag di agy passati invariati)
agy ultracode …                             # stessa cosa, tramite la funzione di shell
```

Con `-p`, `--print` o `--prompt`, il testo che segue il flag riceve automaticamente il prefisso `/ultracode`.

## 4. Permessi

- `ultracode` e `compendio` passano `--dangerously-skip-permissions` se `AGY_KIT_SKIP_PERMISSIONS=1` (il default). Per farti chiedere conferma dei comandi, impostalo a `0`.
- Le sessioni `agy` normali **chiedono i permessi** come di consueto. Per il vecchio comportamento, che salta i permessi ovunque, imposta `AGY_KIT_PLAIN_SKIP_PERMISSIONS=1`; non è consigliato.

## 5. Verifica dell'installazione

```bash
agy-kit doctor            # binario, comandi, skill, python3, shell
agy-kit doctor --online   # in più: il modello risponde e la skill viene caricata
```
