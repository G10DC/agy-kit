# Guida a ultra-ag: Claude Code che delega il lavoro pratico a UltraCode

`ultra-ag` avvia Claude Code in modalità *ultracode* con una divisione dei ruoli precisa: **Opus ragiona, decide, sintetizza e verifica** (con solo qualche occhiata rapida ai file), **ogni task atomico di lavoro pratico va a UltraCode di questo kit** (Gemini Pro con la skill `ultracode`, sotto-agenti Flash) — non solo implementazione, ma anche letture ed esplorazione di codice o documenti, ricerche, estrazione di dati da file (fogli di calcolo, PDF, log) e analisi. Sonnet non viene mai usato.

In pratica è un Ultracode che sfrutta l'UltraCode di Antigravity. Il normale `claude` resta com'era: la modalità esiste solo dentro `ultra-ag`.

---

## 1. Come funziona

```
tu ──► ultra-ag  (Claude Code · Opus · effort ultracode)
         │  capisce, scompone, scrive lo script del workflow
         ▼
   runtime dei workflow
         ├── agent(task, { agentType: 'antigravity' })      foglie di lavoro pratico
         │        │                                          (edit: implementazione — read-only: letture,
         │        │                                           ricerche, estrazione dati, analisi)
         │        ▼
         │   relay "antigravity"  (Haiku, un solo tool)
         │        ▼  mcp__antigravity__delegate (task, cwd, mode: edit | read-only)
         │   claude/ag_bridge.py  (server MCP: coda, timeout, log)
         │        ▼  agy-ultracode -p "/ultracode <task>" --output-format json --json-schema …
         │   UltraCode:  Gemini Pro (--effort high) ──► sotto-agenti Flash
         │        ▼
         │   report JSON (status, summary, answer, sources, file toccati, test, problemi aperti, …)
         │
         └── agent(verifica)  (Opus)   legge il diff reale (edit) o controlla a campione i dati (read-only)
```

**Perché c'è un relay su Haiku.** Il runtime dei workflow di Claude Code non può eseguire comandi: può solo avviare subagenti Claude. Ogni foglia "Antigravity" è quindi un subagente minimo che ha un unico tool (la chiamata al bridge), gira su Haiku e non può fare altro. Il lavoro vero lo fa Gemini; il relay costa qualche migliaio di token Haiku per task.

**Una sola configurazione per Antigravity.** Il bridge non chiama `agy` direttamente ma `agy-ultracode`, lo stesso comando di `ultracode -p`. Modello, effort e permessi vengono quindi da `~/.config/agy-kit/config` come per il resto del kit, e il prompt riceve sempre il prefisso `/ultracode`, così la skill viene caricata.

**Cosa garantisce cosa.**

| Obiettivo | Come è ottenuto | Tipo di garanzia |
|---|---|---|
| Niente Sonnet | `availableModels: ["opus", "haiku"]` in `claude/settings.json` | Rigida **salvo** altre liste `availableModels` in settings utente o di progetto (`~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`): fuori dai managed settings dell'organizzazione questi array si uniscono invece di sostituirsi, quindi un `"sonnet"` in uno qualsiasi di quei file lo riabilita in `ultra-ag` |
| Ragionamento su Opus | `--model opus --effort ultracode`; gli stadi di verifica senza `model` esplicito ereditano il parent | Rigida anche con un `CLAUDE_CODE_SUBAGENT_MODEL` diverso impostato altrove (per esempio nella shell dell'utente): senza modello esplicito, un subagente guarda prima quella variabile e solo se assente eredita il parent, quindi `ultra-ag` la forza a `inherit` — sia nell'ambiente con cui lancia `claude`, sia nell'`env` di `claude/settings.json` |
| Workflow attivi | `"enableWorkflows": true` in `claude/settings.json` | Rigida in `ultra-ag`, salvo che l'organizzazione li disattivi esplicitamente. Senza questo flag, su un piano dove i Workflow sono spenti di default `--effort ultracode` verrebbe comunque accettato ma senza orchestrazione: l'intera architettura `agent(..., {agentType:'antigravity'})` salterebbe in silenzio (sul piano Pro, per esempio, i workflow sarebbero spenti finché non li si attiva) |
| Il lavoro pratico ad Antigravity | `claude/policy.md`, aggiunta al system prompt solo in `ultra-ag` | **Istruzione, non un vincolo tecnico**: Opus la segue (implementazione, ma anche letture, ricerche, estrazione dati e analisi vanno ad Antigravity), ma se glielo chiedi esplicitamente il codice o l'analisi li fa lui stesso. Il tool `mcp__antigravity__delegate` resta comunque richiamabile direttamente, anche da un subagente di verifica che non vede la policy (vedi Permessi) |
| Il relay non lavora al posto di Gemini | il relay ha due tool: `mcp__antigravity__delegate` più `ToolSearch`, che gli serve a caricare il primo quando non è già visibile | Rigida: nessuno dei due esegue codice o scrive file da solo |
| Pro orchestra, Flash esegue | skill `ultracode` e flag di `agy-ultracode` | Come in UltraCode (vedi [GUIDA_ULTRACODE.md](GUIDA_ULTRACODE.md)) |

## 2. Requisiti

- Il kit installato e funzionante: `agy-kit doctor --online` senza errori.
- Claude Code **2.1.280 o successivo** (serve per Opus 5.5 e ultracode): `claude update` se sei indietro.
- Un Python 3.8+ **reale** (solo libreria standard), già richiesto dal kit. Su Windows non l'alias `python3`/`python` dello Store Microsoft: vedi [README.md](../README.md), sezione Requisiti.
- Su Windows: [Git for Windows](https://git-scm.com/downloads/win) (Git Bash), che il bridge usa per lanciare `agy-ultracode` (vedi la sezione Windows più sotto).

`./install.sh` installa tutto insieme al resto del kit: il comando `ultra-ag`, la cartella `claude/` e `~/.config/agy-kit/bridge.json`. Se Claude Code manca, il resto del kit funziona comunque.

## 3. Uso

```bash
cd il-tuo-progetto
ultra-ag                              # sessione interattiva
ultra-ag --permission-mode auto       # meno conferme; ogni argomento passa invariato a claude
ultra-ag -p "…" --allowedTools Workflow   # non interattivo
```

Lavori come sempre in Claude Code. Con ultracode attivo Opus pianifica un workflow per ogni richiesta sostanziale; le foglie di lavoro pratico vanno ad Antigravity — `mode: edit` per implementazione, fix, test; `mode: read-only` per letture, ricerche, estrazione di dati, analisi, con il risultato completo nel campo `answer` del report — mentre verifica e sintesi restano su Opus.

- `/workflows` mostra le fasi e gli agenti di ogni run.
- `/tasks` mostra il modello di ogni subagente: le righe `antigravity` devono dire Haiku. Se vedi Opus, Opus ha passato un `model` al relay contro la policy; funziona, ma costa di più.
- In modalità permessi manuale Claude Code chiede conferma a ogni avvio di workflow; con `--permission-mode auto` no.
- In modalità non interattiva (`-p`) serve `--allowedTools Workflow`, altrimenti il workflow non parte.
- **Verificare che sia davvero Gemini a lavorare** (e non Opus di nascosto): `/tasks` (le righe `antigravity` devono dire Haiku: è il relay, il lavoro vero lo fa Gemini dietro), `/workflows` (ogni fase con `agentType: 'antigravity'` passa dal relay), e i log del bridge in `~/.local/state/agy-kit/bridge-logs/` (un file JSON per task, con il prompt mandato ad Antigravity, il suo output e il report — vedi sezione 8).

**Prova del bridge senza Claude Code** (consigliata la prima volta, in un repository di prova):

```bash
python3 ~/.local/share/agy-kit/claude/ag_bridge.py --check
python3 ~/.local/share/agy-kit/claude/ag_bridge.py --run "Crea il file AG_TEST.md con scritto ciao"
```

Su Windows usa `python` al posto di `python3` (che spesso è l'alias dello Store, non un Python vero) e lancia il comando da Git Bash; se hai impostato `AGY_KIT_PYTHON` nel config, usa quell'interprete.

Deve stampare un report con `"status": "done"` e il file deve esistere.

## 4. Configurazione

| Dove | Chiave | Default | A cosa serve |
|---|---|---|---|
| `~/.config/agy-kit/config` | `AGY_KIT_MODEL`, `AGY_KIT_EFFORT`, `AGY_KIT_SKIP_PERMISSIONS`, `AGY_KIT_SANDBOX` | come UltraCode | Il lato Antigravity, identico a `ultracode` (vedi [GUIDA_ULTRACODE.md](GUIDA_ULTRACODE.md)) |
| `~/.config/agy-kit/config` | `AGY_KIT_PYTHON` | *(vuoto: ricerca automatica)* | Python usato dal bridge e per generare la configurazione MCP di `ultra-ag` |
| `~/.config/agy-kit/config` | `AGY_KIT_CLAUDE_MODEL` | `opus` | Modello di Claude Code che orchestra |
| `~/.config/agy-kit/config` | `AGY_KIT_CLAUDE_BIN` | `claude` nel PATH | Percorso di Claude Code |
| `~/.config/agy-kit/config` | `AGY_KIT_BASH` | *(ricerca automatica)* | Solo Windows: percorso di `bash.exe` di Git for Windows. `ultra-ag` lo passa al bridge nell'ambiente del server MCP; se non è impostata, il bridge risale da `git.exe` o dalle cartelle Program Files tipiche |
| `~/.config/agy-kit/bridge.json` | `max_parallel` | 4 | Task Antigravity contemporanei; gli altri aspettano in coda senza consumare token. Abbassalo se sbatti contro la quota Gemini |
| | `task_timeout_minutes` | 25 | Durata massima di un task, fino a un tetto di 120 minuti (oltre viene tagliato) |
| | `queue_wait_minutes` | 90 | Attesa massima in coda, poi il task torna come `busy` (nessun tetto superiore) |
| | `allowed_roots` | `[]` | Cartelle da cui un task **può partire**, non un sandbox: una volta avviato con `AGY_KIT_SKIP_PERMISSIONS=1` (il default) Antigravity può leggere/scrivere ovunque sulla macchina, e anche con i permessi non saltati valgono le regole globali di `agy`. Vuoto = il progetto di Claude Code e la sua radice git; `["*"]` = ovunque |
| | `log_dir`, `keep_logs` | `~/.local/state/agy-kit/bridge-logs`, 200 | Un file JSON per task: prompt, comando, fino a 200 KB di stdout e 50 KB di stderr di `agy`, report. **Deve essere un percorso assoluto** (anche con `~`): altrimenti `--check` e l'avvio del server falliscono con un errore di configurazione. I log possono contenere segreti letti dai comandi che Antigravity esegue: su macOS/Linux i file sono creati `0600` in una cartella `0700`. La rotazione tocca solo i file con il nome del bridge (`AAAAMMGG-HHMMSS-microsecondi-id.json`), mai altri `.json` che tieni nella stessa cartella |
| | `command` | `agy-ultracode` del kit | Il comando per un task. Da cambiare solo per usare un altro lanciatore |
| | `extra_env` | `{}` | Variabili d'ambiente aggiuntive per `agy`. **Non è il posto per i segreti**: tutto l'ambiente del bridge, token compresi se presenti nella tua shell, passa comunque ad `agy` e ai comandi che esegue |
| | `answer_max_chars` | 20000 | Lunghezza massima (caratteri) del campo `answer` nel report che torna a Claude Code (obbligatorio per i task read-only, note facoltative per i task edit). Oltre, `answer` viene tagliato con una nota di troncamento: la risposta **completa** resta comunque salvata per intero accanto al log, in un file `<log>.answer.md` il cui percorso torna nel report come `answer_file` |

Le variabili `AGY_KIT_*` d'ambiente prevalgono sul file di config, come nel resto del kit (es. `AGY_KIT_CLAUDE_MODEL=claude-opus-5-5 ultra-ag`), e `agy-kit config` ne mostra i valori effettivi. Questo **non** vale per le chiavi di `bridge.json`: non hanno variabili d'ambiente omonime e `agy-kit config` non le stampa. Per un override rapido di sole tre chiavi esistono `AG_MAX_PARALLEL`, `AG_TASK_TIMEOUT_MINUTES` e `AG_QUEUE_WAIT_MINUTES`; `AG_BRIDGE_CONFIG` punta a un `bridge.json` alternativo. Per vedere i valori effettivi di `bridge.json` usa `"$AGY_KIT_PY" claude/ag_bridge.py --check`.

Ogni delega accetta un `conversation_id` opzionale (per continuare una conversazione Antigravity precedente): deve iniziare con una lettera o una cifra, mai con `-`, altrimenti il bridge lo rifiuta prima ancora di avviare `agy`.

Ogni delega accetta anche un `mode`: `edit` (il default) o `read-only`. Con `read-only` il preambolo dice ad Antigravity di non creare, modificare, spostare o cancellare nulla nel workspace e di mettere il risultato completo in `answer`; se `cwd` è dentro un repository git, il bridge fotografa `git status` (più mtime e dimensione dei file elencati) prima e dopo il task, così un file toccato comunque — anche uno che era già modificato prima del task — finisce in `unexpected_changes` nel report, con un `open_issues` e un `hint` che lo segnalano. Un `mode` diverso da `edit`/`read-only` è un errore non ritentabile, prima ancora di avviare `agy`. Un valore non valido di `mode` passato a `--run` da riga di comando viene invece rifiutato subito da `argparse`.

Timeout lato Claude Code, già impostato: 4 ore per il server MCP (`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` in `claude/settings.json`), il limite hard oltre il quale una chiamata al bridge viene comunque interrotta. La regola pratica è `queue_wait_minutes + max(task_timeout_minutes, 120)` sotto i 235 minuti: 120 è il tetto che il bridge applica sia a `task_timeout_minutes` sia al `timeout_minutes` che Opus può chiedere per la singola chiamata (fino a quel valore, indipendentemente dal default di 25), quindi il margine va calcolato su 120 e non sul default.

`~/.config/agy-kit/bridge.json` viene creato con i soli commenti: scrivi lì solo le chiavi che vuoi cambiare, le altre seguono i default del kit (elencati in `claude/bridge.example.json`).

## 5. Permessi

**Il tool `delegate` è pre-approvato, non passa dai permessi di Claude Code.** `claude/settings.json` mette `mcp__antigravity__delegate` in `permissions.allow`: una regola allow si risolve subito, quindi in modalità permessi **manuale** ogni delega parte **senza chiedere conferma**. In modalità `auto`, Claude Code scarta di proposito le regole allow più ampie che darebbero esecuzione di codice arbitrario (`Bash(*)`, interpreti, `Agent`, `Monitor`), facendole valutare dal classificatore; `mcp__antigravity__delegate` non è in quell'elenco, quindi resta pre-approvato anche in `auto` e il classificatore non lo vede. Con `AGY_KIT_SKIP_PERMISSIONS=1` (il default) questo equivale, di fatto, a poter eseguire comandi arbitrari sulla macchina a ogni delega: l'unica barriera è il testo del task che Opus scrive (il PREAMBLE dice di restare nel workspace e di non fare commit/push), che un'iniezione di prompt nei contenuti letti da Opus potrebbe aggirare.

Con `AGY_KIT_SKIP_PERMISSIONS=1`, i task delegati girano senza richieste di permesso, come `ultracode`: Antigravity può leggere, scrivere ed eseguire comandi su tutta la macchina. Usalo in repository sotto git di cui ti fidi. Il bridge limita solo la cartella **di partenza** (`allowed_roots`): non è un sandbox (vedi sezione 4).

Con `AGY_KIT_SKIP_PERMISSIONS=0`, in modalità headless `agy` **rifiuta in automatico** ogni azione che le sue impostazioni non permettono, lettura dei file compresa. Il bridge lo segnala con `status: "blocked"` e l'elenco in `denied_actions`. Per lavorare così, apri `agy` in modo interattivo nel repository, fagli fare le azioni tipiche e rispondi *always allow … (Persist to settings.json)*: le regole finiscono in `~/.gemini/antigravity-cli/settings.json` e valgono anche per i task delegati.

`AGY_KIT_SANDBOX=1` aggiunge `--sandbox` alla chiamata di `agy-ultracode` che il bridge lancia (stesso flag di UltraCode/Compendio, vedi [GUIDA_ULTRACODE.md](GUIDA_ULTRACODE.md)): un confine in più, utile insieme a `AGY_KIT_SKIP_PERMISSIONS=0` quando vuoi restringere cosa Antigravity può toccare.

## 6. Cosa significa ogni `status`

| status | Significato | Cosa fa Opus (da `policy.md`) |
|---|---|---|
| `done` | Antigravity dice di aver finito | Verifica diff e test (task edit) o controlla a campione i dati in `answer` (task read-only), poi prosegue |
| `partial`, `failed` | Finito in parte o per niente | Chiarisce, aggiunge contesto o spezza il task e lo rimanda **una sola volta** |
| `unverified` | Nessun report strutturato, solo il testo finale | Come sopra, verificando tutto. Per un task read-only, il testo finale finisce comunque in `answer`/`answer_file` |
| `blocked` | I permessi di Antigravity hanno rifiutato azioni | Si ferma e ti dice cosa sbloccare (sezione 5) |
| `timeout` | `agy` è stato fermato oltre il timeout — anche dal proprio `--print-timeout`, che lo fa uscire con codice 0 e un avviso su stderr a metà turno | Il task può aver lasciato modifiche a metà: controlla `git status`/`git diff` prima di tutto, poi continua con `conversation_id` o spezza quello che resta |
| `cancelled` | Il run è stato annullato (da Opus o dall'utente) | Come `timeout`: può aver lasciato modifiche parziali, controlla il diff prima di decidere se il task serve ancora |
| `busy` | Coda piena troppo a lungo | Manda meno task alla volta, poi rimanda |
| `error`, `empty` | Errore di `agy`/del modello, oppure risposta vuota | Rimanda **una sola volta** se `retryable` è vero (per `empty`, accorciando il task come dice `hint`), altrimenti te lo segnala |

Il relay Haiku **non ritenta mai da solo**: un solo livello di retry, deciso sempre da Opus, che rimanda un task al massimo una volta dopo il primo tentativo.

**Altri campi del report**, oltre a `status`/`summary`/`files_changed`/`commands_run`/`tests`/`open_issues`:

| Campo | Presente quando | Contenuto |
|---|---|---|
| `answer` | Task `read-only` (obbligatorio nella richiesta ad Antigravity); facoltativo su un task `edit` | Il risultato completo in Markdown, con riferimenti a file/riga/pagina per ogni numero o citazione. Tagliato ad `answer_max_chars` con una nota di troncamento se supera il limite |
| `answer_file` | Ogni volta che il report ha un `answer` e il log è stato scritto | Percorso di `<log>.answer.md`, accanto al log: la copia **completa** e mai troncata di `answer`. Utile a Opus se la copia inoltrata dal relay è incompleta |
| `sources` | Il report di Antigravity include `sources` | File o URL consultati per rispondere |
| `unexpected_changes` | Task `read-only`, `cwd` dentro un repository git, e almeno un file toccato comunque | Percorsi (relativi alla radice del repository) risultati diversi tra la fotografia di `git status` prima e dopo il task. Il report include anche un `open_issues` e un `hint` dedicati |

Se `cwd` di un task `read-only` non è dentro un repository git (o `git` non è disponibile), il bridge non fa la rilevazione: nessun `unexpected_changes` nel report, e il log del task lo annota esplicitamente.

## 7. Limiti da conoscere

- **File in parallelo.** Due task Antigravity paralleli non devono toccare gli stessi file: la policy dice a Opus di separarli o di metterli in sequenza. L'isolamento in worktree non si usa per le foglie Antigravity, perché le modifiche resterebbero nel worktree.
- **La policy è un'istruzione.** "Il lavoro pratico va ad Antigravity" (implementazione, ma anche letture, ricerche, estrazione dati, analisi) non è un vincolo tecnico: se lo chiedi esplicitamente, il codice o l'analisi li fa Opus. Il divieto di Sonnet invece è rigido.
- **`mode: read-only` è un'istruzione ad Antigravity, non un sandbox.** Il bridge non impedisce le scritture: le rileva *a posteriori* confrontando `git status` prima e dopo (solo dentro un repository git). Un task read-only su una cartella che non è un repository git non ha questa rete di sicurezza.
- **Costo per task.** Ogni foglia paga un giro del relay Haiku e l'avvio di `agy`: per modifiche di una riga conviene chiederle direttamente.
- **Quota Gemini.** Un workflow grande può lanciare molti task: `max_parallel` è il freno.
- **Il report è una dichiarazione.** Per questo ogni fase di implementazione è seguita da una verifica su Opus basata sul diff reale.
- **Flag che sostituiscono quelli del kit.** Gli argomenti di `ultra-ag` passano a `claude` dopo quelli del kit: un tuo `--settings`, `--mcp-config`, `--model` o `--agents` può scavalcare esclusione di Sonnet, bridge o relay. Usali solo se sai cosa cambiano.
- **Classificatore della modalità `auto`.** Senza Sonnet, il classificatore dei permessi di Claude Code gira su Opus e costa di più. Vale solo dentro `ultra-ag`.
- **Limiti di lunghezza del task.** Su Linux e macOS il prompt (preambolo + task) viaggia come un unico argomento verso `agy-ultracode` e poi verso `agy`: su Linux ogni singolo argomento deve restare sotto 128 KiB (macOS non ha questo limite per argomento). Su Windows il bridge passa il prompt ad `agy-ultracode` su **stdin**, perché il runtime MSYS tronca a 8186 caratteri ogni argomento che un processo nativo passa a `bash.exe`; il limite effettivo è quindi la riga di comando da `bash` ad `agy.exe`, circa 30.000 caratteri. Gli altri argomenti che attraversano quel confine (per esempio un `{prompt}` dentro un argomento composto come `--prompt={prompt}` in un `command` personalizzato) restano limitati a circa 8.000 caratteri. Oltre soglia il bridge rifiuta il task con un errore chiaro e **non ritentabile**, prima ancora di avviare `agy`: fai riferire ad Antigravity ai file invece di incollarne il contenuto, o spezza il task.

## 8. File

| File | Ruolo |
|---|---|
| `bin/ultra-ag` | Launcher: `claude --model opus --effort ultracode` con i file qui sotto; genera a ogni avvio la configurazione MCP; su Windows forza anche `AGY_KIT_BASH` nell'ambiente del server MCP |
| `claude/ag_bridge.py` | Server MCP (tool `delegate`) che lancia `agy-ultracode` headless; anche `--check` e `--run` da terminale |
| `claude/agents.json` | Il relay `antigravity` (Haiku, tool `delegate` + `ToolSearch` per caricarlo) |
| `claude/policy.md` | Regole di instradamento per Opus, aggiunte al system prompt |
| `claude/settings.json` | `availableModels` senza Sonnet, `enableWorkflows`, `CLAUDE_CODE_SUBAGENT_MODEL=inherit`, permesso al tool del bridge, timeout del server MCP |
| `claude/bridge.example.json` | Modello di `~/.config/agy-kit/bridge.json` |
| `tests/test_bridge.py`, `tests/fake_agy.py` | Test offline del bridge (chiamati da `tests/run-tests.sh`) |

## 9. Windows

`ultra-ag` si avvia da Git Bash, ma anche da PowerShell o dal prompt dei comandi tramite il launcher nativo `ultra-ag.exe` (o, in ripiego se manca `csc.exe`, lo shim `.cmd` — vedi il README): il bridge (`claude/ag_bridge.py`) gira sempre con il Python nativo di Windows, non con quello di Git Bash.

- **Git Bash.** Gli script del kit lanciati dal bridge (`agy-ultracode` e gli altri) restano script bash: su Windows il bridge li avvia tramite `bash.exe` di Git for Windows, mai `C:\Windows\System32\bash.exe` (quello è WSL). Lo trova da solo risalendo da `git.exe` o dalle cartelle Program Files tipiche.
- **`AGY_KIT_BASH`.** Se l'individuazione automatica fallisce, o vuoi puntare a un'installazione specifica di Git for Windows, impostala nel config (vedi sezione 4): `ultra-ag` la passa al bridge nell'ambiente del server MCP.
- **Percorsi.** Il bridge converte da solo i percorsi in stile Git Bash (`/c/...`) che riceve per `cwd`, `AGY_BIN`, le variabili `XDG_*` e `AG_BRIDGE_CONFIG`, prima di usarli con le API native di Windows.
- **Job Object: `agy` muore con il bridge.** Ogni albero di processi di `agy` vive in un Job Object di Windows: un timeout o un annullamento lo termina tutto con `TerminateJobObject`, e se il bridge stesso viene ucciso — Claude Code ferma i server MCP con `taskkill /T /F`, non con SIGINT — `agy` muore con lui grazie a `KILL_ON_JOB_CLOSE`. Se la creazione del Job Object fallisce, il bridge ripiega su `taskkill /T /F` per PID: un tentativo più debole, perché la catena reale dei processi da bash ad `agy.exe` non sempre è ricostruibile in quel modo.

## 10. Come è stato testato

Su Windows 11 con Git Bash, Python 3.12.10, agy 1.2.8 e Claude Code 2.1.283 (aggiornato per `mode: read-only`, `answer`/`answer_file`/`sources`/`unexpected_changes`):

```
tests/run-tests.sh → Esito: 123 superati, 0 falliti
```

che aggrega, nello stesso run:

| Suite | Copre | Esito |
|---|---|---|
| script principale di `run-tests.sh` | parsing di `agy-ultracode` e `agy-compendio`, `agy-kit doctor`/`config`, funzione di shell, `ultra-ag`; su Windows un eseguibile nativo finto verifica che `/ultracode` arrivi intatto e che `MSYS_NO_PATHCONV` non finisca nell'ambiente di `agy`; contenuto di `claude/agents.json` e `claude/policy.md` per `mode: read-only` | 120 superati, 0 falliti |
| `tests/test_bridge.py` | handshake MCP, timeout reale di `agy` via `--print-timeout`, rotazione e permessi dei log (compresi i `.answer.md` compagni), limiti di lunghezza, annullamento, chiusura su EOF/SIGINT/SIGTERM (POSIX) e Ctrl+Break (Windows); `mode` non valido, preamboli edit/read-only, `answer`/`sources` nel report, troncamento di `answer` con `answer_file` completo, rilevazione di `unexpected_changes` in un repository git (anche su un file già modificato) e nessun falso positivo; su Windows Job Object, Git Bash, prompt su stdin (task di oltre 12.000 caratteri ricevuto identico da un `agy.exe` nativo finto), mai `.cmd` eseguiti direttamente | 135 superati, 0 falliti |
| `tests/test_compendio_verify.py` | tutti i codici E-\*/W-\*, casi limite, prestazioni (anche righe con 200.000 `[` non chiuse) | 56 superati, 0 falliti |
| `tests/test_install.sh` | installazione e disinstallazione in sandbox; launcher `.exe` provati da una PowerShell reale (argomenti `a&b`, `50%PATH%`, `a^b`, `sp aces` intatti); ripiego `.cmd` | 66 superati, 0 falliti |

**Prove reali sulla stessa macchina** (installazione vera con `./install.sh`, poi):

- `agy-kit doctor --online`: 37 controlli ok, il modello `gemini-3.1-pro` risponde e la skill viene caricata tramite `/ultracode`.
- `ag_bridge.py --run "Crea il file AG_TEST.md …"` in un repository di prova: `status: done` in 14 s, report strutturato con `conversation_id`, file creato con il contenuto richiesto e nient'altro modificato.
- `ultra-ag -p "Rispondi solo con la parola OK"`: Claude Code parte con le impostazioni del kit, il server MCP `antigravity` si collega via stdio e alla chiusura viene terminato in modo pulito.

**Non provato in questa revisione:**

- **macOS e Linux.** Nessuna delle due piattaforme è stata eseguita. Il comportamento specifico di POSIX (symlink invece di wrapper, permessi `0600`/`0700` dei log, limite di 128 KiB per argomento su Linux, compatibilità con la bash 3.2 di macOS) è stato riletto e ragionato sul codice, non rieseguito.
- **Un workflow completo di `ultra-ag`** con più deleghe ad Antigravity in parallelo: provati separatamente il bridge reale e l'avvio di `ultra-ag`, non l'intera orchestrazione.
- **`mode: read-only` contro il vero Antigravity.** `agy-ultracode`/`agy` reali non sono stati eseguiti in questa revisione: solo `tests/fake_agy.py`, che simula un report con `answer`/`sources` e un agy che viola la regola read-only. La rilevazione via `git status` prima/dopo è verificata contro un vero repository git, ma con l'agy finto, non con Gemini.
