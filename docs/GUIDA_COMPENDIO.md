# Guida allo script Compendio (`compendio` / `agy compendio`)

`compendio` analizza tutti i file di una cartella e produce un **unico file di riferimento**. Il file ha tracciabilità completa delle fonti e tiene separati i fatti dalle deduzioni. Alla fine viene controllato in modo deterministico da `compendio-verify`.

> **Regole epistemiche** (tassonomia a 5 livelli, 6 Iron Rules): l'unica fonte è la skill [`skills/ultracode/SKILL.md`](../skills/ultracode/SKILL.md). Qui non vengono ricopiate.

---

## 1. Cosa fa

1. Si sposta nella cartella da analizzare e avvia UltraCode (`/ultracode` + modello Pro con `--effort high`).
2. Chiede all'agente di:
   - censire l'albero dei file con un comando reale;
   - delegare lettura ed estrazione verbatim a sotto-agenti **Flash**;
   - tenere per il modello Pro sintesi, collegamenti e deduzioni.
3. Il file prodotto contiene:
   - indice e scheda rapida;
   - inventario dei file con metadati reali (`stat`, `shasum -a 256`);
   - schede tematiche e collegamenti incrociati;
   - cronologia e registro delle deduzioni (con confidenza);
   - discrepanze `[VERIFICARE]`;
   - glossario, tabella di contatti e URL, appendice di metodo e limiti.
4. L'agente deve eseguire `compendio-verify` e correggere gli errori finché la verifica non passa.
5. Terminata la sessione, **lo script stesso** esegue `compendio-verify` e restituisce il suo codice d'uscita. Il controllo quindi non dipende da quanto il modello sia stato diligente.

## 2. Opzioni

| Opzione | Effetto |
|---|---|
| *(nessuna)* | Analizza la cartella corrente e scrive `COMPENDIO_INTEGRALE.md` in quella cartella |
| `<directory>` | Cartella da analizzare |
| `-o`, `--output <file>` | Nome del file finale. Un nome relativo viene preso rispetto alla cartella analizzata; un percorso assoluto viene usato così com'è |
| `-p`, `--print` | Esecuzione non interattiva (print mode). Il processo resta **in primo piano**: per mandarlo in background usa `&` o `nohup` |
| `--no-verify` | Salta il `compendio-verify` finale |
| `-h`, `--help` | Aiuto |

Codici d'uscita:

| Codice | Significato |
|---|---|
| `0` | Verifica superata (possono restare avvisi) |
| `1` | Errori di verifica |
| `2` | Argomenti non validi |
| `3` | File di output non creato |
| altro | Errore restituito da `agy` |

```bash
compendio
compendio ~/Documenti/AltroProgetto
compendio -o BASE_CONOSCENZA_VERIFICATA.md
compendio -p ~/Documenti/AltroProgetto -o /tmp/base.md
```

## 3. `compendio-verify`

Si può usare anche su file scritti a mano o prodotti da altri strumenti:

```bash
compendio-verify FILE.md [--root CARTELLA_FONTI] [--json] [--quiet] [--all]
```

| Codice | Livello | Cosa controlla |
|---|---|---|
| `E-LINK` | errore | Link Markdown o `file://` verso percorsi inesistenti |
| `E-CIT` | errore | Citazioni `[file#L12]`, `[file#L12-L20]` o `[SIGLA#L3]` verso file inesistenti o righe fuori intervallo. Le sigle vengono lette dalle tabelle di legenda del documento (`\| **SIGLA** \| \`file\` \|`) |
| `E-HASH` | errore | SHA-256 che non corrispondono al file nominato sulla stessa riga, o a nessun file della cartella |
| `E-100` | errore | "100%" o "INTEGRALE" dichiarati mentre ci sono punti `[VERIFICARE]` aperti. Senza punti aperti è solo un avviso. Le citazioni tra virgolette sono ignorate |
| `W-DED` | avviso | `[DEDOTTO]` senza confidenza (Alta, Media o Bassa) sulla stessa riga |
| `W-NORM` | avviso | Riferimenti normativi (D.P.R., D.Lgs., art. … c.c.) che non compaiono nelle fonti testuali. I PDF sono inclusi se è installato `pdftotext` |
| `W-PATH` | avviso | Percorsi assoluti tra backtick che non esistono |

Il codice non viene analizzato: blocchi di codice e testo tra backtick sono esclusi da citazioni e completezza.

**Collaudo sul caso reale Esselunga.** Su `Esselunga/COMPENDIO_INTEGRALE.md` segnala gli stessi **7 hash errati** individuati a mano nel post-mortem. Sulla base di conoscenza verificata `BASE_CONOSCENZA_ESSELUNGA.md` riporta 0 errori.
