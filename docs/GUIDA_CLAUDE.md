# Guida a ultra-ag: Claude Code che delega l'implementazione a UltraCode

`ultra-ag` avvia Claude Code in modalità *ultracode* con una divisione dei ruoli precisa: **Opus ragiona e orchestra**, **ogni task atomico di implementazione va a UltraCode di questo kit** (Gemini Pro con la skill `ultracode`, sotto-agenti Flash). Sonnet non viene mai usato.

In pratica è un Ultracode che sfrutta l'UltraCode di Antigravity. Il normale `claude` resta com'era: la modalità esiste solo dentro `ultra-ag`.

---

## 1. Come funziona

```
tu ──► ultra-ag  (Claude Code · Opus · effort ultracode)
         │  capisce, scompone, scrive lo script del workflow
         ▼
   runtime dei workflow
         ├── agent(task, { agentType: 'antigravity' })      foglie di implementazione
         │        ▼
         │   relay "antigravity"  (Haiku, un solo tool)
         │        ▼  mcp__antigravity__delegate
         │   claude/ag_bridge.py  (server MCP: coda, timeout, log)
         │        ▼  agy-ultracode -p "/ultracode <task>" --output-format json --json-schema …
         │   UltraCode:  Gemini Pro (--effort high) ──► sotto-agenti Flash
         │        ▼
         │   report JSON (status, file toccati, test, problemi aperti)
         │
         └── agent(verifica)  (Opus)   legge il diff reale, lancia i test
```

**Perché c'è un relay su Haiku.** Il runtime dei workflow di Claude Code non può eseguire comandi: può solo avviare subagenti Claude. Ogni foglia "Antigravity" è quindi un subagente minimo che ha un unico tool (la chiamata al bridge), gira su Haiku e non può fare altro. Il lavoro vero lo fa Gemini; il relay costa qualche migliaio di token Haiku per task.

**Una sola configurazione per Antigravity.** Il bridge non chiama `agy` direttamente ma `agy-ultracode`, lo stesso comando di `ultracode -p`. Modello, effort e permessi vengono quindi da `~/.config/agy-kit/config` come per il resto del kit, e il prompt riceve sempre il prefisso `/ultracode`, così la skill viene caricata.

**Cosa garantisce cosa.**

| Obiettivo | Come è ottenuto | Tipo di garanzia |
|---|---|---|
| Niente Sonnet | `availableModels: ["opus", "haiku"]` in `claude/settings.json` | Rigida: una richiesta di Sonnet ricade su Opus |
| Ragionamento su Opus | `--model opus --effort ultracode`; gli stadi di verifica ereditano Opus | Rigida |
| Implementazione ad Antigravity | `claude/policy.md`, aggiunta al system prompt solo in `ultra-ag` | Istruzione: Opus la segue, ma non è un vincolo tecnico |
| Il relay non lavora al posto di Gemini | il relay ha un solo tool (`mcp__antigravity__delegate`) | Rigida |
| Pro orchestra, Flash esegue | skill `ultracode` e flag di `agy-ultracode` | Come in UltraCode (vedi [GUIDA_ULTRACODE.md](GUIDA_ULTRACODE.md)) |

## 2. Requisiti

- Il kit installato e funzionante: `agy-kit doctor --online` senza errori.
- Claude Code **2.1.280 o successivo** (serve per Opus 5.5 e ultracode): `claude update` se sei indietro.
- `python3` 3.8 o successivo (solo libreria standard), già richiesto dal kit.

`./install.sh` installa tutto insieme al resto del kit: il comando `ultra-ag`, la cartella `claude/` e `~/.config/agy-kit/bridge.json`. Se Claude Code manca, il resto del kit funziona comunque.

## 3. Uso

```bash
cd il-tuo-progetto
ultra-ag                              # sessione interattiva
ultra-ag --permission-mode auto       # meno conferme; ogni argomento passa invariato a claude
ultra-ag -p "…" --allowedTools Workflow   # non interattivo
```

Lavori come sempre in Claude Code. Con ultracode attivo Opus pianifica un workflow per ogni richiesta sostanziale; le foglie di implementazione vanno ad Antigravity, verifica e sintesi restano su Opus.

- `/workflows` mostra le fasi e gli agenti di ogni run.
- `/tasks` mostra il modello di ogni subagente: le righe `antigravity` devono dire Haiku. Se vedi Opus, Opus ha passato un `model` al relay contro la policy; funziona, ma costa di più.
- In modalità permessi manuale Claude Code chiede conferma a ogni avvio di workflow; con `--permission-mode auto` no.
- In modalità non interattiva (`-p`) serve `--allowedTools Workflow`, altrimenti il workflow non parte.

**Prova del bridge senza Claude Code** (consigliata la prima volta, in un repository di prova):

```bash
python3 ~/.local/share/agy-kit/claude/ag_bridge.py --check
python3 ~/.local/share/agy-kit/claude/ag_bridge.py --run "Crea il file AG_TEST.md con scritto ciao"
```

Deve stampare un report con `"status": "done"` e il file deve esistere.

## 4. Configurazione

| Dove | Chiave | Default | A cosa serve |
|---|---|---|---|
| `~/.config/agy-kit/config` | `AGY_KIT_MODEL`, `AGY_KIT_EFFORT`, `AGY_KIT_SKIP_PERMISSIONS` | come UltraCode | Il lato Antigravity, identico a `ultracode` |
| `~/.config/agy-kit/config` | `AGY_KIT_CLAUDE_MODEL` | `opus` | Modello di Claude Code che orchestra |
| `~/.config/agy-kit/config` | `AGY_KIT_CLAUDE_BIN` | `claude` nel PATH | Percorso di Claude Code |
| `~/.config/agy-kit/bridge.json` | `max_parallel` | 4 | Task Antigravity contemporanei; gli altri aspettano in coda senza consumare token. Abbassalo se sbatti contro la quota Gemini |
| | `task_timeout_minutes` | 25 | Durata massima di un task |
| | `queue_wait_minutes` | 90 | Attesa massima in coda, poi il task torna come `busy` |
| | `allowed_roots` | `[]` | Dove Antigravity può lavorare. Vuoto = il progetto di Claude Code e la sua radice git; `["*"]` = ovunque |
| | `log_dir`, `keep_logs` | `~/.local/state/agy-kit/bridge-logs`, 200 | Un file JSON per task: prompt, comando, output completo di `agy`, report |
| | `command` | `agy-ultracode` del kit | Il comando per un task. Da cambiare solo per usare un altro lanciatore |
| | `extra_env` | `{}` | Variabili d'ambiente aggiuntive per `agy` |

Le variabili d'ambiente prevalgono sul file, come nel resto del kit (es. `AGY_KIT_CLAUDE_MODEL=claude-opus-5-5 ultra-ag`). `agy-kit config` mostra i valori effettivi.

Timeout lato Claude Code, già impostati: 4 ore sia per il server MCP sia per i subagenti (`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` in `claude/settings.json`), così un relay in coda non viene ucciso prima che il bridge risponda. Bastano finché `queue_wait_minutes` + `task_timeout_minutes` restano sotto i 235 minuti.

`~/.config/agy-kit/bridge.json` viene creato con i soli commenti: scrivi lì solo le chiavi che vuoi cambiare, le altre seguono i default del kit (elencati in `claude/bridge.example.json`).

## 5. Permessi

Con `AGY_KIT_SKIP_PERMISSIONS=1` (il default del kit) i task delegati girano senza richieste di permesso, come `ultracode`: Antigravity può leggere, scrivere ed eseguire comandi su tutta la macchina. Usalo in repository sotto git di cui ti fidi. Il bridge limita solo la cartella di partenza (`allowed_roots`).

Con `AGY_KIT_SKIP_PERMISSIONS=0`, in modalità headless `agy` **rifiuta in automatico** ogni azione che le sue impostazioni non permettono, lettura dei file compresa. Il bridge lo segnala con `status: "blocked"` e l'elenco in `denied_actions`. Per lavorare così, apri `agy` in modo interattivo nel repository, fagli fare le azioni tipiche e rispondi *always allow … (Persist to settings.json)*: le regole finiscono in `~/.gemini/antigravity-cli/settings.json` e valgono anche per i task delegati.

Quello che fa `agy` non passa dal sistema di permessi di Claude Code.

## 6. Cosa significa ogni `status`

| status | Significato | Cosa fa Opus (da `policy.md`) |
|---|---|---|
| `done` | Antigravity dice di aver finito | Verifica diff e test, poi prosegue |
| `partial`, `failed` | Finito in parte o per niente | Chiarisce o spezza il task e lo rimanda, al massimo due volte |
| `unverified` | Nessun report strutturato, solo il testo finale | Come sopra, verificando tutto |
| `blocked` | I permessi di Antigravity hanno rifiutato azioni | Si ferma e ti dice cosa sbloccare (sezione 5) |
| `timeout` | Oltre `task_timeout_minutes` | Spezza il task |
| `busy` | Coda piena troppo a lungo | Manda meno task alla volta |
| `error`, `empty` | Errore di `agy` o del modello, oppure risposta vuota | Riprova una volta se `retryable`, altrimenti te lo segnala |

## 7. Limiti da conoscere

- **File in parallelo.** Due task Antigravity paralleli non devono toccare gli stessi file: la policy dice a Opus di separarli o di metterli in sequenza. L'isolamento in worktree non si usa per le foglie Antigravity, perché le modifiche resterebbero nel worktree.
- **La policy è un'istruzione.** "L'implementazione va ad Antigravity" non è un vincolo tecnico: se lo chiedi esplicitamente, il codice lo scrive Opus. Il divieto di Sonnet invece è rigido.
- **Costo per task.** Ogni foglia paga un giro del relay Haiku e l'avvio di `agy`: per modifiche di una riga conviene chiederle direttamente.
- **Quota Gemini.** Un workflow grande può lanciare molti task: `max_parallel` è il freno.
- **Il report è una dichiarazione.** Per questo ogni fase di implementazione è seguita da una verifica su Opus basata sul diff reale.
- **Flag che sostituiscono quelli del kit.** Gli argomenti di `ultra-ag` passano a `claude` dopo quelli del kit: un tuo `--settings`, `--mcp-config`, `--model` o `--agents` può scavalcare esclusione di Sonnet, bridge o relay. Usali solo se sai cosa cambiano.
- **Classificatore della modalità `auto`.** Senza Sonnet, il classificatore dei permessi di Claude Code gira su Opus e costa di più. Vale solo dentro `ultra-ag`.

## 8. File

| File | Ruolo |
|---|---|
| `bin/ultra-ag` | Launcher: `claude --model opus --effort ultracode` con i file qui sotto; genera a ogni avvio la configurazione MCP |
| `claude/ag_bridge.py` | Server MCP (tool `delegate`) che lancia `agy-ultracode` headless; anche `--check` e `--run` da terminale |
| `claude/agents.json` | Il relay `antigravity` (Haiku, un solo tool) |
| `claude/policy.md` | Regole di instradamento per Opus, aggiunte al system prompt |
| `claude/settings.json` | `availableModels` senza Sonnet, permesso al tool del bridge, timeout dei subagenti |
| `claude/bridge.example.json` | Modello di `~/.config/agy-kit/bridge.json` |
| `tests/test_bridge.py`, `tests/fake_agy.py` | Test offline del bridge (chiamati da `tests/run-tests.sh`) |

## 9. Come è stato testato

- **Bridge**: 49 controlli offline con un `agy` finto, attraverso la catena reale bridge → `agy-ultracode` → `agy`. Handshake MCP, report strutturati, flag e prefisso `/ultracode` passati ad `agy`, azioni negate, errori con codice 3, risposte vuote, JSON con a capo non validi (difetto noto di `agy`), processi in background che tengono aperto l'output, coda con `max_parallel`, annullamento, chiusura su EOF e SIGINT.
- **Claude Code reale** (2.1.283) avviato con `ultra-ag` da un'installazione del kit, contro un'API Anthropic simulata in locale (nessun token speso): il workflow avvia il relay su Haiku, il relay chiama il bridge, `agy` riceve `--model gemini-3.1-pro --effort high --dangerously-skip-permissions -p "/ultracode …"` e il file viene creato; la verifica gira su Opus con effort `xhigh`; una richiesta esplicita di Sonnet finisce su Opus.
- **Non testato**: il tuo `agy` reale con Gemini, perché da qui non ci arrivo. È quello che controllano `agy-kit doctor --online` e la prova con `--run` della sezione 3.
