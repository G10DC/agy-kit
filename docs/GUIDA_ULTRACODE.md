# Guida a UltraCode in Antigravity (`agy`)

UltraCode è la modalità di Antigravity a massima intensità: ragionamento profondo, esecuzione autonoma e un protocollo rigido contro le allucinazioni. Si ispira alla modalità *Ultracode* di Claude Code.

> **Regole:** l'unica fonte è la skill [`skills/ultracode/SKILL.md`](../skills/ultracode/SKILL.md), installata in `~/.gemini/config/skills/ultracode/`. Questa guida spiega come usarla e non ne ricopia il testo.

---

## 1. Componenti

| Componente | Ruolo |
|---|---|
| `ultracode` / `agy-ultracode` | Avvia `agy` con il modello principale, l'effort configurato (default `high`) e, se configurato, senza richieste di permesso |
| Skill `ultracode` | Contiene la divisione dei ruoli tra i modelli, la tassonomia a 5 livelli, le 6 Iron Rules, la sequenza Plan → Reproduce → Build → Verify, la revisione da 3 prospettive e la verifica deterministica |
| `/ultracode` | Comando che carica la skill. Lo script lo mette sempre in testa al prompt, perché in Antigravity le skill sono "on demand" e la sola parola chiave non garantisce che vengano caricate |
| `~/.config/agy-kit/config` | Modello, effort e permessi (vedi il README) |

## 2. Ripartizione dei modelli

| Ruolo | Modello | Come viene imposto |
|---|---|---|
| Agente principale: architettura, sintesi, deduzioni, verifica | `AGY_KIT_MODEL` (default `gemini-3.1-pro`) con `AGY_KIT_EFFORT` (default `high`) | Flag della CLI, quindi in modo deterministico |
| Sotto-agenti: scansione, lettura massiva, estrazione verbatim, test | Flash | La skill prescrive `invoke_subagent` con modello `flash`. Il default del tool è `inherit`, cioè Pro |
| Vietato | `flash_lite` | Regola della skill |

Il modello dei sotto-agenti viene scelto dall'agente principale seguendo la skill: non esiste un flag della CLI che lo imponga.

## 3. Uso

```bash
ultracode                                       # sessione interattiva
ultracode "risolvi il memory leak nel worker websocket"
ultracode -p "esegui un security audit sugli endpoint di autenticazione"   # non interattivo
echo "controlla i test rossi" | ultracode -p    # prompt letto da stdin
ultracode -c                                    # riprende l'ultima conversazione
ultracode -c "continua da dove eri rimasto"     # riprende E aggiunge subito un task
ultracode --model gemini-3.1-pro-low --effort low "task veloce"   # sostituisce modello/effort del kit
agy ultracode …                                 # stessa cosa, tramite la funzione di shell
```

`/ultracode` viene anteposto **sempre**, qualunque sia la forma con cui indichi il task, e non viene aggiunto due volte se il testo comincia già con `/ultracode`:

| Comando | Cosa riceve `agy` |
|---|---|
| `ultracode` (nessun argomento) | `-i '/ultracode Sessione UltraCode attiva. Attendi il mio primo task.'` |
| `ultracode "task"` | `-i '/ultracode task'` |
| `ultracode -p "task"` | `-p '/ultracode task'` |
| `echo "task" \| ultracode -p` | `-p '/ultracode task'` (letto da stdin; con `--input-format stream-json` lo stdin resta ad `agy`, che lo legge da sé riga per riga, e il prefisso non si applica) |
| `ultracode -c` | `-c -i '/ultracode'` (carica la skill senza inviare messaggi nella conversazione ripresa; lo stesso con `--conversation <id>`) |
| `ultracode -c "task"` | `-c -i '/ultracode task'` |
| `ultracode --model M --effort E "task"` | `--model M --effort E -i '/ultracode task'` (sostituiscono modello/effort del kit, senza duplicati) |
| `ultracode -p "task" altro-argomento` | **errore, exit 2**: il prompt è già indicato con `-p`; metti tutto il task in un solo argomento tra virgolette |
| `ultracode -- "-task che inizia per trattino"` | tutto ciò che segue `--` è testo del task, passato invariato |

Un valore di `-p`/`-i` che inizia per `-` riceve comunque il prefisso (non viene scambiato per un flag), a meno che sia esattamente un altro flag noto di `agy` — in quel caso il prompt arriva dall'argomento successivo, oppure da stdin se non ce n'è uno.

## 4. Permessi e sandbox

- `ultracode` e `compendio` passano `--dangerously-skip-permissions` **solo** se `AGY_KIT_SKIP_PERMISSIONS` vale esattamente `1` (il default quando la variabile non è impostata affatto). Un valore vuoto o diverso da `1`, in ambiente o nel file di config, fa chiedere conferma dei comandi come di consueto: la regola è fail-closed, non fail-open.
- Le sessioni `agy` normali **chiedono i permessi** come di consueto. Per il vecchio comportamento, che salta i permessi ovunque, imposta `AGY_KIT_PLAIN_SKIP_PERMISSIONS=1`; non è consigliato. La variabile d'ambiente, se impostata anche a `0`, prevale sempre sul file di config.
- `AGY_KIT_SANDBOX=1` fa aggiungere `--sandbox` (restrizioni sul terminale imposte da `agy` stesso) dopo il flag dei permessi. Utile in aggiunta a `AGY_KIT_SKIP_PERMISSIONS=0` quando vuoi un confine più netto, per esempio con Compendio su documenti di terzi (vedi [GUIDA_COMPENDIO.md](GUIDA_COMPENDIO.md)).

## 5. Verifica dell'installazione

```bash
agy-kit doctor            # binario, comandi, skill, Python, shell (su Windows anche wrapper e shim .cmd)
agy-kit doctor --online   # in più: il modello risponde e la skill viene caricata
```
