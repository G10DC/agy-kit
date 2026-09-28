# Guida allo script Compendio (`compendio` / `agy compendio`)

`compendio` analizza tutti i file di una cartella e produce un **unico file di riferimento**. Il file ha tracciabilità completa delle fonti e tiene separati i fatti dalle deduzioni. Alla fine viene controllato in modo deterministico da `compendio-verify`.

> **Regole epistemiche** (tassonomia a 5 livelli, 6 Iron Rules): l'unica fonte è la skill [`skills/ultracode/SKILL.md`](../skills/ultracode/SKILL.md). Qui non vengono ricopiate.

---

## 1. Cosa fa

1. Si sposta nella cartella da analizzare e avvia UltraCode (`/ultracode` + modello Pro con l'effort configurato, default `high`; con `AGY_KIT_SANDBOX=1` nel config gira con `agy --sandbox`, consigliato su documenti di provenienza esterna).
2. Chiede all'agente di:
   - censire l'albero dei file con un comando reale;
   - delegare lettura ed estrazione verbatim a sotto-agenti **Flash**;
   - tenere per il modello Pro sintesi, collegamenti e deduzioni;
   - **non aprire né trascrivere i file che possono contenere segreti** (`.env` e varianti, chiavi private, tutto ciò che sta in `.ssh/`, `.aws/`, `.gnupg/`, credenziali di gestori password, ecc.): citarli solo per nome nell'inventario, con la nota `[ESCLUSO: possibile segreto]`; se trova un segreto dentro un altro file, scrivere `[SEGRETO OMESSO]` invece del valore.
3. Il file prodotto contiene:
   - indice e scheda rapida;
   - inventario dei file con metadati reali (dimensione e data rilevate con comandi reali; SHA-256 calcolato davvero — `sha256sum` su Linux, `shasum -a 256` su macOS, `Get-FileHash -Algorithm SHA256` su Windows: il comando giusto per la piattaforma è già scritto nel prompt che riceve l'agente);
   - schede tematiche e collegamenti incrociati;
   - cronologia e registro delle deduzioni (con confidenza);
   - discrepanze `[VERIFICARE]`;
   - glossario, tabella di contatti e URL, appendice di metodo e limiti.
4. L'agente deve eseguire la verifica deterministica (il comando esatto, con `--require-coverage`, è nel prompt) e correggere ogni `ERROR` finché non esce con codice 0.
5. Terminata la sessione, **lo script stesso** esegue `compendio-verify --require-coverage` e restituisce il suo codice d'uscita. Il controllo quindi non dipende da quanto il modello sia stato diligente.

## 2. Opzioni

| Opzione | Effetto |
|---|---|
| *(nessuna)* | Analizza la cartella corrente e scrive `COMPENDIO_INTEGRALE.md` in quella cartella |
| `<directory>` | Cartella da analizzare (una sola: indicarne più di una è un errore) |
| `-o`, `--output <file>` | Nome del file finale. Un nome relativo viene preso rispetto alla cartella analizzata; un percorso assoluto (anche `C:\...` su Windows) viene usato così com'è |
| `-p`, `--print` | Esecuzione non interattiva (print mode). Il processo resta **in primo piano**: per mandarlo in background usa `&` o `nohup` |
| `--no-verify` | Salta la chiamata a `compendio-verify` a fine sessione (il controllo che il file sia stato creato/aggiornato resta comunque attivo) |
| `--force` | Consente di analizzare la home dell'utente o la radice del disco, rifiutate per default perché conterrebbero anche chiavi e credenziali |
| `-h`, `--help` | Aiuto |

Codici d'uscita:

| Codice | Significato |
|---|---|
| `0` | Verifica superata (possono restare avvisi) |
| `1` | Errori di verifica |
| `2` | Argomenti non validi: opzione sconosciuta, più di una cartella indicata, oppure cartella uguale alla home o alla radice del disco senza `--force` |
| `3` | Il file di destinazione non è stato creato, **oppure** esisteva già e la sessione non lo ha aggiornato (stessa firma prima e dopo). Controllato anche con `--no-verify` |
| `4` | `agy` è terminato con un codice di errore diverso da zero (il codice compare nel messaggio) |
| `127` | `agy` oppure un Python 3.8+ utilizzabile non sono stati trovati (controllato prima di avviare la sessione) |

```bash
compendio
compendio ~/Documenti/AltroProgetto
compendio -o BASE_CONOSCENZA_VERIFICATA.md
compendio -p ~/Documenti/AltroProgetto -o /tmp/base.md
compendio --force ~   # analizza la home: sotto la tua responsabilità, contiene chiavi e credenziali
```

## 3. `compendio-verify`

Si può usare anche su file scritti a mano o prodotti da altri strumenti:

```bash
compendio-verify FILE.md [--root CARTELLA_FONTI] [--require-coverage] [--json] [--quiet] [--all]
```

Errori (fanno fallire la verifica, exit 1):

| Codice | Cosa controlla |
|---|---|
| `E-LINK` | Link Markdown o `file://` verso file inesistenti, fuori dalla radice (`--root`) o al compendio stesso |
| `E-CIT` | Citazioni `[file#L12]`, `[file#L12-L20]` o `[doc.pdf p.N]` verso file/sigle inesistenti, fuori dalla radice, al compendio stesso, o righe/pagine fuori intervallo. Le sigle vengono lette dalle tabelle di legenda del documento (`\| **SIGLA** \| \`file\` \|`) |
| `E-HASH` | SHA-256 dichiarato accanto a un file nominato (tra backtick, in un link Markdown o in una cella di tabella) che non corrisponde al file indicato |
| `E-100` | "100%" / "INTEGRALE" / "copertura totale" dichiarati mentre ci sono punti `[VERIFICARE]` ancora aperti nel documento |
| `E-COV` | Solo con `--require-coverage`: file delle fonti sotto `--root` mai citati nel compendio, oppure compendio vuoto o senza alcuna citazione |

Avvisi (non fanno fallire la verifica):

| Codice | Cosa controlla |
|---|---|
| `W-COV` | Senza `--require-coverage`: stessa segnalazione di `E-COV`, ma solo un avviso |
| `W-DED` | `[DEDOTTO]` senza un livello di confidenza esplicito (Alta/Media/Bassa) chiaramente associato (vicino a "confidenza" o tra parentesi) |
| `W-NORM` | Riferimenti normativi (D.P.R., D.Lgs., D.L., Legge, art. … c.c., Reg./Dir. UE) assenti dalle fonti testuali (confronto tollerante a punteggiatura e spaziatura). I PDF (e i `.docx`) sono inclusi se è installato `pdftotext` |
| `W-PATH` | Percorsi assoluti tra backtick che non esistono |
| `W-AMBIG` | Citazione o nome per solo basename che combacia con più file sotto la radice: valida se lo è per almeno uno dei candidati, ma segnalata perché ambigua |
| `W-BIN` | Citazione a righe (`#Lnn`) su un file binario/documentale non verificabile contando le righe, oppure pagina PDF non verificabile perché `pdfinfo`/`pdftotext` non sono disponibili |
| `W-HASH` | SHA-256 senza alcun file nominato sulla riga che non corrisponde a nessun file sotto la radice (non è un errore: potrebbe essere un hash citato verbatim da una fonte, es. `FROM immagine@sha256:...`, checksum di un lockfile) |
| `W-FENCE` | Una recinzione di codice (tripla virgoletta inversa o `~~~`) aperta non viene mai chiusa: il testo restante nel file è escluso dai controlli (scelta conservativa: trattato come codice, non come prosa, ma la mancata chiusura viene sempre segnalata) |
| `W-CIT` | Etichetta tra parentesi quadre con `#Lnn` che non è né una sigla di legenda né un file esistente, in un documento senza alcuna legenda (con una legenda, lo stesso caso è `E-CIT`) |

Il codice non viene analizzato: blocchi recintati e testo tra backtick sono esclusi da citazioni e completezza.

`--require-coverage` (usata automaticamente da `compendio` a fine sessione) alza `W-COV` a `E-COV`: ogni file sotto `--root` deve comparire nel compendio per nome o percorso relativo, oppure dentro una nota `[ESCLUSO: ... nome-file ...]` per i file esclusi come possibili segreti.

`--all` non raggruppa gli avvisi ripetuti (di default, oltre 8 avvisi dello stesso codice vengono riassunti in una riga).

### Cosa garantisce e cosa no

`compendio-verify` è un controllo **di forma e di tracciabilità**, non di verità. Verifica che link, citazioni e hash puntino davvero a un file esistente sotto la radice indicata, con righe o pagine nell'intervallo giusto e un hash che corrisponde, e che ogni file delle fonti sia stato almeno nominato. **Non legge il contenuto citato per giudicare se il compendio lo riporta fedelmente**: una citazione `[file.py#L10]` sintatticamente corretta, ma che descrive male cosa dice davvero la riga 10, supera comunque la verifica. Il controllo è una rete contro le allucinazioni più grossolane — fonte inventata, riga inesistente, hash sbagliato, dichiarazione di completezza falsa — non una garanzia che il testo sia accurato.

**Collaudo.** La suite `tests/test_compendio_verify.py` (55 casi su questa macchina) copre ogni codice con documenti minimi costruiti per il test, inclusi gli scenari `W-AMBIG`/`W-BIN`/`W-HASH`/`W-FENCE`/`W-CIT` e le pagine PDF. Una versione precedente di questa guida citava un "collaudo sul caso reale Esselunga" (`Esselunga/COMPENDIO_INTEGRALE.md`, `BASE_CONOSCENZA_ESSELUNGA.md`): quei file **non sono inclusi nel kit**, e quell'affermazione non è verificabile da chi lo riceve.
