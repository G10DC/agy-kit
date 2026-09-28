# agy-kit: UltraCode e Compendio per Antigravity CLI

Kit portabile che aggiunge ad Antigravity CLI (`agy`) due modalità, più un ponte da Claude Code:

- **UltraCode** (`ultracode` / `agy ultracode`): sessione a massimo sforzo con Gemini Pro (`--effort high`). Sotto-agenti Flash per il lavoro operativo e protocollo anti-allucinazione.
- **Compendio** (`compendio` / `agy compendio`): genera da una cartella una base di conoscenza unica e verificata. Alla fine la controlla con **`compendio-verify`**, che fa controlli deterministici su link, citazioni, hash e dichiarazioni di completezza.
- **ultra-ag** (`ultra-ag`): Claude Code in modalità ultracode in cui **Opus ragiona e orchestra** e **ogni task atomico di implementazione va a UltraCode** (Gemini Pro + Flash), tramite un relay Haiku e un bridge MCP. Sonnet non viene mai usato. Facoltativo: serve Claude Code 2.1.280 o successivo.

Versione: vedi `VERSION`. Documentazione: [docs/GUIDA_ULTRACODE.md](docs/GUIDA_ULTRACODE.md), [docs/GUIDA_COMPENDIO.md](docs/GUIDA_COMPENDIO.md), [docs/GUIDA_CLAUDE.md](docs/GUIDA_CLAUDE.md). Le regole si trovano in un solo file: [skills/ultracode/SKILL.md](skills/ultracode/SKILL.md).

---

## Installazione su un altro computer

**Requisiti:**

- macOS o Linux, con `bash` (vanno bene anche la 3.2 di macOS e `zsh`);
- **oppure Windows 10/11 con [Git for Windows](https://git-scm.com/downloads/win)** (Git Bash): serve per installare il kit e per usare `ultra-ag`; i comandi installati funzionano poi anche da PowerShell e dal prompt dei comandi (vedi sotto);
- Antigravity CLI (`agy`) installato e con login effettuato;
- **Python 3.8 o superiore, reale**, che serve a `compendio-verify` e al bridge di `ultra-ag`. Su Windows l'alias `python3`/`python` dello Store Microsoft non è un Python vero: il kit lo rileva e lo segnala (`agy-kit doctor`). Per disattivarlo: Impostazioni → App → Impostazioni app avanzate → Alias di esecuzione delle app, spegni `python.exe` e `python3.exe`; poi installa Python da [python.org](https://python.org), oppure imposta `AGY_KIT_PYTHON=/percorso/del/tuo/python` in `~/.config/agy-kit/config` senza disinstallare nulla;
- opzionale: `pdftotext` (pacchetto *poppler*), per cercare i riferimenti normativi anche dentro i PDF e per contare le pagine nelle citazioni `[doc.pdf p.N]`;
- opzionale: Claude Code 2.1.280 o successivo, per `ultra-ag`.

```bash
# 0. installa Antigravity CLI ed effettua l'accesso almeno una volta (apri `agy` e completa il login)

# 1. scarica il kit ed entra nella cartella
git clone https://github.com/G10DC/agy-kit.git   # oppure: gh repo clone G10DC/agy-kit
cd agy-kit

# 2. (facoltativo) guarda cosa verrà fatto, senza modificare nulla
./install.sh --dry-run

# 3. installa
./install.sh

# 4. apri un nuovo terminale e controlla
agy-kit doctor            # controlli locali
agy-kit doctor --online   # prova anche il modello con una richiesta minima
```

L'installer non richiede privilegi di amministratore, può essere rieseguito senza effetti collaterali e salva una copia di ogni file che sostituisce in `~/.local/share/agy-kit-backups/<data>/`.

### Installazione su Windows

I passi 1-3 vanno eseguiti da **Git Bash** (cercalo nel menu Start dopo aver installato Git for Windows; non PowerShell né il prompt dei comandi):

```bash
git clone https://github.com/G10DC/agy-kit.git
cd agy-kit
./install.sh
```

Poi apri un **nuovo terminale** — Git Bash, PowerShell o il prompt dei comandi vanno bene tutti, i comandi installati funzionano da ciascuno — ed esegui:

```
agy-kit doctor
```

Git Bash (MSYS) non crea collegamenti simbolici senza la Developer Mode di Windows attiva: `ln -s` copierebbe semplicemente il file, e gli script del kit che risalgono alla propria cartella di installazione seguendo il collegamento otterrebbero un percorso sbagliato. Per questo su Windows l'installer crea, per ogni comando, un **wrapper bash** marcato in `~/.local/bin/<comando>` che richiama lo script vero nel kit, più un **launcher nativo `<comando>.exe`** accanto, compilato al volo da `lib/win-launcher.cs` con `csc.exe` di .NET Framework (già presente su ogni Windows con .NET Framework 4, nessuna installazione aggiuntiva): è quell'`.exe` che rende i comandi utilizzabili da **PowerShell e dal prompt dei comandi**, non solo da Git Bash, passando gli argomenti a `bash.exe` di Git for Windows così come li riceve da Windows — senza farli reinterpretare dal parser di PowerShell o di `cmd`, quindi `&`, `%VAR%`, `^`, le virgolette e gli spazi arrivano intatti.

Se `csc.exe` o `bash.exe` di Git for Windows non si trovano, l'installer ripiega su un vecchio **shim `.cmd`** (`<comando>.cmd`) che richiama il wrapper tramite `bash.exe` con `%*`: funziona per un uso semplice, ma da PowerShell o da `cmd` **`&`, `%VAR%`, `^` e le virgolette vengono interpretati dal loro parser** prima di raggiungere il comando (`%PATH%` viene espanso da `cmd` come per qualsiasi altro comando; PowerShell 5.1 inoltre perde le virgolette interne e gli argomenti vuoti, un limite comune a ogni `.exe` chiamato da lì). Per i prompt liberi con questi caratteri, in quel caso conviene Git Bash. `agy-kit doctor` verifica quale dei due è installato e segnala se `bash.exe` di Git for Windows non si trova (puoi indicarlo esplicitamente con `AGY_KIT_BASH`).

| Cosa | Dove |
|---|---|
| Kit installato | `~/.local/share/agy-kit/` (variabile `AGY_KIT_HOME`) |
| Comandi | `~/.local/bin/`: `ultracode`, `agy-ultracode`, `compendio`, `agy-compendio`, `compendio-verify`, `agy-kit`, `ultra-ag`. Collegamenti simbolici su macOS/Linux; su Windows un wrapper bash marcato più un launcher nativo `<comando>.exe` (o, in ripiego, uno shim `<comando>.cmd`) per ciascun comando (vedi sopra) |
| Manifesto dell'installazione | `$AGY_KIT_HOME/.install-paths`: i percorsi scelti da `install.sh` (kit, comandi, skill), riletti da `uninstall.sh` e da `agy-kit` quando girano dalla copia installata senza `AGY_KIT_HOME` nell'ambiente |
| Skill | `~/.gemini/config/skills/ultracode/SKILL.md` |
| Configurazione | `~/.config/agy-kit/config` e `~/.config/agy-kit/bridge.json` (creati solo se non esistono) |
| Log del bridge Claude Code | `~/.local/state/agy-kit/bridge-logs/`: un file per task, con prompt e output completi di `agy` — su macOS/Linux i file sono `0600` in una cartella `0700` perché possono contenere segreti (vedi [docs/GUIDA_CLAUDE.md](docs/GUIDA_CLAUDE.md)) |
| Shell | blocco `# >>> agy-kit >>>` in `~/.zshrc` e/o `~/.bashrc`: aggiunge `~/.local/bin` al PATH e definisce la funzione `agy`. Se manca `~/.bash_profile` e la shell è bash su macOS o su Windows/Git Bash, l'installer ne crea uno minimo (blocco `# >>> agy-kit-profile >>>`) che carica `~/.bashrc`, perché le shell di login leggono quello e non `~/.bashrc` |

**Aggiornare:** `git pull` nella cartella del kit, poi `./install.sh`.

**Disinstallare:** `~/.local/share/agy-kit/uninstall.sh`. Aggiungi `--purge` per eliminare anche configurazione e log.

## Uso rapido

```bash
ultracode                                  # sessione interattiva UltraCode
ultracode "risolvi il memory leak nel worker e aggiungi i test"
ultracode -p "security audit di lib/auth.ts"   # non interattivo
agy ultracode …                            # equivalente, tramite la funzione di shell

compendio                                  # compendio della cartella corrente → COMPENDIO_INTEGRALE.md
compendio ~/Documenti/Progetto -o BASE.md -p
compendio-verify BASE.md --root ~/Documenti/Progetto   # verifica di un file esistente
agy verify BASE.md                                     # equivalente

agy-kit config                             # configurazione effettiva

ultra-ag                                   # Claude Code: Opus orchestra, UltraCode implementa
ultra-ag --permission-mode auto            # ogni argomento passa invariato a claude
```

## Configurazione (`~/.config/agy-kit/config`)

| Variabile | Default | Significato |
|---|---|---|
| `AGY_KIT_MODEL` | `gemini-3.1-pro` | Modello principale. L'elenco completo si ottiene con `agy models`; con `--effort` (il default) va usato l'ID **senza** suffisso di sforzo, es. `gemini-3.1-pro`. Un ID **con** il suffisso (es. `gemini-3.1-pro-low`) va abbinato a `AGY_KIT_EFFORT` vuoto, altrimenti agy rifiuta la combinazione (vedi Risoluzione dei problemi) |
| `AGY_KIT_EFFORT` | `high` | `low`, `medium` o `high`; vuoto significa che `--effort` non viene passato (allora usa un `AGY_KIT_MODEL` con il suffisso) |
| `AGY_KIT_SKIP_PERMISSIONS` | `1` | Salta i permessi di UltraCode/Compendio solo con il valore **esatto** `1`; vuoto o qualunque altro valore fa chiedere conferma come di consueto. Se la variabile non è impostata affatto, il default resta `1` |
| `AGY_KIT_SANDBOX` | `0` | Con `1`, UltraCode e Compendio girano con `agy --sandbox` (restrizioni sul terminale, vedi `agy --help`); consigliato quando Compendio legge documenti di terzi |
| `AGY_KIT_PLAIN_SKIP_PERMISSIONS` | `0` | Con `1`, anche le sessioni `agy` normali (funzione di shell `agy`) saltano i permessi (sconsigliato). Se la variabile d'ambiente è impostata, anche a `0`, prevale sempre sul file; altrimenti conta l'ultima assegnazione `AGY_KIT_PLAIN_SKIP_PERMISSIONS=` trovata nel file di config |
| `AGY_KIT_PYTHON` | *(vuoto)* | Percorso di un interprete Python 3.8+. Vuoto = ricerca automatica (`python3`, poi `python`, poi `py -3`), scartando gli interpreti che non si avviano davvero — come l'alias dello Store su Windows |
| `AGY_BIN` | `agy` nel PATH | Percorso del binario, se non è nel PATH |
| `AGY_KIT_CLAUDE_MODEL` | `opus` | Modello di Claude Code che orchestra in `ultra-ag` |
| `AGY_KIT_CLAUDE_BIN` | `claude` nel PATH | Percorso di Claude Code |

Parallelismo, timeout e cartelle permesse del bridge di `ultra-ag` stanno in `~/.config/agy-kit/bridge.json`: vedi [docs/GUIDA_CLAUDE.md](docs/GUIDA_CLAUDE.md).

Le variabili d'ambiente con lo stesso nome prevalgono sul file di config, ad esempio `AGY_KIT_EFFORT=medium ultracode` usa il modello del config ma con sforzo medio.

## Come funziona (in breve)

1. `ultracode` e `compendio` avviano `agy --model $AGY_KIT_MODEL --effort $AGY_KIT_EFFORT [--dangerously-skip-permissions] [--sandbox]`.
2. Il prompt inizia **sempre** con **`/ultracode`**, qualunque sia il modo in cui indichi il task: `-p`, `-i`, `-c`, argomenti posizionali o testo letto da stdin. In Antigravity le skill si caricano "on demand": questo comando garantisce che la skill venga caricata in ogni caso.
3. La skill impone l'uso di sotto-agenti `invoke_subagent` con modello `flash` per il lavoro operativo. Il default del tool sarebbe `inherit`, cioè Pro.
4. `compendio` si sposta nella cartella da analizzare, avvia la sessione e al termine esegue `compendio-verify`. Il codice d'uscita riflette l'esito della verifica.
5. `ultra-ag` avvia `claude --model opus --effort ultracode` con un relay `antigravity` (Haiku, un solo tool), la policy di instradamento e il bridge `claude/ag_bridge.py`, che per ogni task lancia `agy-ultracode -p` e restituisce a Opus un report JSON. Opus poi verifica il diff reale.

## Test

```bash
tests/run-tests.sh   # tutte le suite, offline: agy e claude sono sostituiti da stub, nessuna chiamata di rete
```

`tests/run-tests.sh` esegue in sequenza quattro suite:

| Suite | Cosa copre |
|---|---|
| script principale (`run-tests.sh`) | parsing di `agy-ultracode`/`agy-compendio`, `agy-kit doctor`/`config`, blocco shell |
| `tests/test_bridge.py` | il bridge MCP di `ultra-ag`: handshake, timeout, log, limiti di riga di comando, Windows |
| `tests/test_compendio_verify.py` | `compendio-verify`: tutti i codici E-*/W-*, casi limite |
| `tests/test_install.sh` | `install.sh`/`uninstall.sh` in una sandbox (HOME temporanea), inclusi wrapper e launcher `.exe` su Windows (con una PowerShell reale) e il ripiego `.cmd` quando `csc.exe` non è disponibile |

Puoi anche lanciare una singola suite Python, per esempio `"$AGY_KIT_PY" tests/test_bridge.py` (su Windows non usare `python3` a mano: potrebbe essere l'alias dello Store; il kit trova da sé un Python vero).

`BASH_BIN=/bin/bash tests/run-tests.sh` fa girare con un'altra bash solo le chiamate dirette dello script principale (utile per provare la bash 3.2 di macOS): `test_bridge.py` lancia comunque `agy-ultracode` seguendo il suo shebang, quindi **non** cambia l'interprete usato dalla catena reale del bridge (bridge → Git Bash/bash di sistema → `agy-ultracode`).

## Risoluzione dei problemi

| Sintomo | Causa e rimedio |
|---|---|
| `invalid model selection … --effort is not supported for model …` | Il nome del modello non è valido per `--effort`. Esegui `agy models` e imposta in config un ID come `gemini-3.1-pro` |
| `agy non ha effettuato l'accesso` (doctor) | Avvia `agy`, completa il login Google nel browser, poi `agy-kit doctor --online` |
| `ultracode: command not found` | `~/.local/bin` non è nel PATH: apri un nuovo terminale o esegui `source ~/.zshrc` |
| `agy ultracode` avvia un'altra cosa | Nel file rc c'è una vecchia funzione `agy()` o un vecchio alias fuori dal blocco agy-kit. `agy-kit doctor` la segnala |
| `ultra-ag`: i task tornano `blocked` | `AGY_KIT_SKIP_PERMISSIONS=0` e Antigravity rifiuta le azioni in modalità headless: vedi [docs/GUIDA_CLAUDE.md](docs/GUIDA_CLAUDE.md), sezione Permessi |
| `ultra-ag`: in `/tasks` il relay `antigravity` gira su Opus | Opus gli ha passato un `model` contro la policy: funziona ma costa di più |
| Il compendio esce con codice 1 | `compendio-verify` ha trovato errori: leggi il report stampato e correggi, oppure chiedi all'agente di farlo |
| Windows: `agy-kit doctor` segnala Python "trovato ma non utilizzabile" | Di solito è l'alias `python3`/`python` dello Store Microsoft. Disattivalo (Impostazioni → App → Impostazioni app avanzate → Alias di esecuzione delle app) o imposta `AGY_KIT_PYTHON` nel config |
| Windows: `comando non trovato` subito dopo l'installazione | PowerShell e il prompt dei comandi rileggono il PATH solo all'avvio: apri un **nuovo terminale**. Se persiste, controlla che `~/.local/bin` (in genere `C:\Users\<utente>\.local\bin`) sia nel PATH utente |
| Windows: un argomento con `/` passato a `claude` o ad `agy` da Git Bash appare trasformato in un percorso stile `C:/Program Files/Git/...` | Conversione automatica dei percorsi di MSYS. Nelle proprie chiamate ad `agy` il kit esclude dalla conversione solo il prompt (che inizia con `/ultracode`), gli altri argomenti vengono convertiti come per qualsiasi programma Windows; per un tuo argomento manuale, anteponi `MSYS_NO_PATHCONV=1` al comando oppure raddoppia la barra iniziale (`//testo`) |
| Windows: `agy-kit doctor` segnala "solo lo shim .cmd" | `csc.exe` di .NET Framework (Framework64 o Framework, `v4.0.30319`) o `bash.exe` di Git for Windows non sono stati trovati durante l'installazione: il comando funziona ma da PowerShell/cmd `&`, `%VAR%`, `^` e le virgolette vengono interpretati dal loro parser prima di arrivare al comando. Rilancia `./install.sh` dopo aver installato .NET Framework o Git for Windows, oppure usa Git Bash per i prompt con questi caratteri |
| Windows: da PowerShell un argomento con virgolette interne (`"`) o un argomento vuoto (`""`) arriva alterato anche al launcher `.exe` | Limite di PowerShell 5.1 stesso (non del kit): perde le virgolette interne e gli argomenti vuoti prima ancora di avviare qualunque `.exe`. Per quei casi usa Git Bash. Da `cmd`, ricorda anche che `%VAR%` viene espanso da `cmd` stesso, come per qualsiasi altro comando |

## Novità della 1.2.0

- **Windows 10/11** con Git for Windows: installazione, comandi (wrapper bash + launcher nativo `.exe`, usabili anche da PowerShell/cmd con argomenti `&`/`%`/`^`/virgolette intatti; ripiego `.cmd` se manca `csc.exe`), `compendio`, il bridge di `ultra-ag` e l'intera suite di test funzionano senza WSL.
- **Ricerca automatica di un Python reale** (`AGY_KIT_PY`/`AGY_KIT_PYTHON`): scarta l'alias del Microsoft Store e gli shim che non si avviano; usata da `compendio-verify`, dal bridge e da `agy-kit doctor`.
- **`/ultracode` davvero sempre in testa al prompt**, con `-p`, `-i`, `-c`, argomenti posizionali o testo letto da stdin.
- **`AGY_KIT_SANDBOX`** per far girare UltraCode/Compendio con `agy --sandbox`.
- **`AGY_KIT_SKIP_PERMISSIONS`** ora fail-closed: solo il valore esatto `1` salta i permessi.
- **Compendio**: opzione `--force` per analizzare la home o la radice del disco, file con probabili segreti citati solo per nome, nuovi codici d'uscita (`3` anche per output non aggiornato, `4` = `agy` terminato con errore, `127` = `agy`/Python mancanti).
- **`compendio-verify`**: copertura delle fonti opzionale (`--require-coverage`, E-COV/W-COV) e nuovi controlli (W-AMBIG, W-BIN, pagine PDF, W-HASH, W-FENCE, W-CIT).
- **`ultra-ag`**: un solo livello di retry (lo decide Opus, il relay non ritenta più da solo), `enableWorkflows` forzato, `CLAUDE_CODE_SUBAGENT_MODEL=inherit` forzato, stato `cancelled` nel report, log del bridge protetti (`0600`/`0700` su macOS/Linux) e rotazione che tocca solo i file del bridge.
- **Installer/disinstaller più sicuri**: manifesto `.install-paths`, mai un `rm -rf` su una cartella non riconoscibile come il kit o con un `.git`, backup dei file rc prima di modificarli, `~/.bash_profile` creato quando manca.
