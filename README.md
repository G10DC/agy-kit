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
- Antigravity CLI (`agy`) installato e con login effettuato;
- `python3` (3.8 o superiore), che serve al verificatore;
- opzionale: `pdftotext` (pacchetto *poppler*), per cercare i riferimenti normativi anche dentro i PDF;
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

| Cosa | Dove |
|---|---|
| Kit installato | `~/.local/share/agy-kit/` (variabile `AGY_KIT_HOME`) |
| Comandi | `~/.local/bin/`: `ultracode`, `agy-ultracode`, `compendio`, `agy-compendio`, `compendio-verify`, `agy-kit`, `ultra-ag` (collegamenti simbolici) |
| Skill | `~/.gemini/config/skills/ultracode/SKILL.md` |
| Configurazione | `~/.config/agy-kit/config` e `~/.config/agy-kit/bridge.json` (creati solo se non esistono) |
| Log del bridge Claude Code | `~/.local/state/agy-kit/bridge-logs/` |
| Shell | blocco `# >>> agy-kit >>>` in `~/.zshrc` e/o `~/.bashrc`: aggiunge `~/.local/bin` al PATH e definisce la funzione `agy` |

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
| `AGY_KIT_MODEL` | `gemini-3.1-pro` | Modello principale. L'elenco completo si ottiene con `agy models`; con `--effort` va usato l'ID senza suffisso |
| `AGY_KIT_EFFORT` | `high` | `low`, `medium` o `high`; vuoto significa che `--effort` non viene passato |
| `AGY_KIT_SKIP_PERMISSIONS` | `1` | Con `1`, UltraCode e Compendio non chiedono conferma per i comandi |
| `AGY_KIT_PLAIN_SKIP_PERMISSIONS` | `0` | Con `1`, anche le sessioni `agy` normali saltano i permessi (sconsigliato) |
| `AGY_BIN` | `agy` nel PATH | Percorso del binario, se non è nel PATH |
| `AGY_KIT_CLAUDE_MODEL` | `opus` | Modello di Claude Code che orchestra in `ultra-ag` |
| `AGY_KIT_CLAUDE_BIN` | `claude` nel PATH | Percorso di Claude Code |

Parallelismo, timeout e cartelle permesse del bridge di `ultra-ag` stanno in `~/.config/agy-kit/bridge.json`: vedi [docs/GUIDA_CLAUDE.md](docs/GUIDA_CLAUDE.md).

Le variabili d'ambiente con lo stesso nome prevalgono sul file, ad esempio `AGY_KIT_MODEL=gemini-3.1-pro-low ultracode`.

## Come funziona (in breve)

1. `ultracode` e `compendio` avviano `agy --model $AGY_KIT_MODEL --effort $AGY_KIT_EFFORT [--dangerously-skip-permissions]`.
2. Il prompt inizia sempre con **`/ultracode`**. In Antigravity le skill si caricano "on demand": questo comando garantisce che la skill venga caricata, anche in modalità `-p`.
3. La skill impone l'uso di sotto-agenti `invoke_subagent` con modello `flash` per il lavoro operativo. Il default del tool sarebbe `inherit`, cioè Pro.
4. `compendio` si sposta nella cartella da analizzare, avvia la sessione e al termine esegue `compendio-verify`. Il codice d'uscita riflette l'esito della verifica.
5. `ultra-ag` avvia `claude --model opus --effort ultracode` con un relay `antigravity` (Haiku, un solo tool), la policy di instradamento e il bridge `claude/ag_bridge.py`, che per ogni task lancia `agy-ultracode -p` e restituisce a Opus un report JSON. Opus poi verifica il diff reale.

## Test

```bash
tests/run-tests.sh                    # test offline, con agy e claude simulati: nessuna chiamata di rete
python3 tests/test_bridge.py          # solo il bridge di ultra-ag (già incluso nel precedente)
BASH_BIN=/bin/bash tests/run-tests.sh # stessi test con la bash 3.2 di macOS
```

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
