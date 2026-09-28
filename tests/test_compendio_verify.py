#!/usr/bin/env python3
"""Test end-to-end per bin/compendio-verify (solo libreria standard, multipiattaforma).

Uso: python tests/test_compendio_verify.py

Ogni test crea una cartella temporanea con le fonti, scrive un compendio Markdown e invoca
compendio-verify come sottoprocesso (con l'interprete corrente, sys.executable: niente
dipendenza da 'python3' nel PATH). Stampa un esito con segno di spunta per ogni caso e un
riepilogo finale; esce con codice diverso da zero se qualcosa fallisce.

Copertura (in corrispondenza dei controlli/codici del verificatore, vedi anche i casi di
riproduzione dell'audit c1..c15):
  E-COV/W-COV   copertura delle fonti, compendio vuoto o senza citazioni, note [ESCLUSO ...],
                troncamento dell'elenco, cartella senza file sotto root
  E-CIT         nomi di file con accenti/spazi/parentesi/apostrofi/virgole, citazioni multiple
                (';' e ',' dopo una cifra), continuazione "#L1-L3, L9" e "#L1; #L5", niente
                ripiego per basename con cartelle inesistenti, sigle non definite (con/senza
                legenda), righe/pagine fuori range su ambiguità con nessun candidato valido
  W-AMBIG       basename ambiguo, valido se lo è per almeno un candidato
  W-CIT         etichetta non risolta senza legenda nel documento
  W-BIN         citazioni #L su file binari/documentali, pagine PDF senza pdfinfo/pdftotext
  E-CIT (pagina) pagine PDF verificate con pdfinfo/pdftotext quando disponibili
  E-100         dichiarazioni di completezza vs righe dato (con citazione), confini di "100%",
                intestazioni/blocchi di codice/dichiarazioni "nessun punto aperto" escluse dal
                conteggio dei punti [VERIFICARE] aperti, rilevamento di "copertura totale" /
                "analizzati integralmente", caso «A» ... «B» corretto
  E-HASH/W-HASH ignorati nel codice (anche recintato), file nominato tra backtick/link/cella di
                tabella deve corrispondere, hash senza nome che non combacia è solo avviso
  W-FENCE       recinzione non chiusa
  E-LINK        fuori radice, al compendio stesso, schema/URI e "//host" ignorati
  E-CIT/E-LINK  fuori radice o al compendio stesso
  W-PATH        percorsi assoluti in backtick inesistenti
  W-NORM        riferimenti normativi tolleranti a punteggiatura/spaziatura, [CONOSCENZA ESTERNA]
  W-DED         livello di confidenza esplicito richiesto (non un ID o un aggettivo comune)
  robustezza    symlink rotti, file non leggibili: nessun crash (COMP-15)
  prestazioni   5000 file / 2500 citazioni entro un tempo ragionevole
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)
VERIFY = os.path.join(KIT_ROOT, "bin", "compendio-verify")

# Su Windows la console usa spesso una code page che non ha ✔/✘ (es. cp1252): riconfigura
# stdout/stderr in UTF-8 con sostituzione dei caratteri non rappresentabili invece di far
# fallire lo script con UnicodeEncodeError (Python 3.7+, solo libreria standard).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

passed = 0
failed = 0


def ok(name, note=""):
    global passed
    passed += 1
    print(f"✔ {name}" + (f"  ({note})" if note else ""))


def ko(name, detail):
    global failed
    failed += 1
    print(f"✘ {name}\n    {detail}")


def check(name, condition, detail=""):
    if condition:
        ok(name)
    else:
        ko(name, detail)


def skip(name, reason):
    ok(name, f"saltato: {reason}")


# ---------- helpers ----------

def write(path, content, newline="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(content, bytes):
        with open(path, "wb") as fh:
            fh.write(content)
    else:
        with open(path, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(content)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def run_verify(md_path, root=None, require_coverage=False, extra_args=None):
    cmd = [sys.executable, VERIFY, "--all", "--json", md_path]
    if root:
        cmd += ["--root", root]
    if require_coverage:
        cmd.append("--require-coverage")
    if extra_args:
        cmd += extra_args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = {"findings": [], "errors": None, "warnings": None}
    return proc.returncode, data["findings"], proc


def has(findings, sev, code, contains=None):
    for f in findings:
        if f["severity"] == sev and f["code"] == code:
            if contains is None or contains in f["message"]:
                return True
    return False


def only_codes(findings):
    return sorted({(f["severity"], f["code"]) for f in findings})


def tmpdir():
    return tempfile.mkdtemp(prefix="cv_test_")


# ---------- COMP-1: copertura ----------

def test_coverage_all_cited_no_warning():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n2\n")
    write(os.path.join(T, "b.txt"), "1\n2\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1] e [b.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("coverage: tutte le fonti citate -> nessun avviso W-COV", rc == 0 and not has(f, "WARN", "W-COV"),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_missing_warns_without_require():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "b.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("coverage: file non citato senza --require-coverage -> W-COV, exit 0",
          rc == 0 and has(f, "WARN", "W-COV", "b.txt"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_missing_errors_with_require():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "b.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"), require_coverage=True)
    check("coverage: file non citato con --require-coverage -> E-COV, exit 1",
          rc == 1 and has(f, "ERROR", "E-COV", "b.txt"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_excluded_note():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "tecnico.bin"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\n[ESCLUSO tecnico.bin: generato].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"), require_coverage=True)
    check("coverage: nota [ESCLUSO ...] conta come copertura", rc == 0 and not has(f, "ERROR", "E-COV"),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_truncated_list():
    T = tmpdir()
    for i in range(30):
        write(os.path.join(T, f"file{i:02d}.txt"), "x\n")
    write(os.path.join(T, "c.md"), "Cito solo [file00.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    msg = next((x["message"] for x in f if x["code"] == "W-COV"), "")
    check("coverage: elenco lungo troncato con conteggio (+altri N)",
          "(+altri " in msg and "29/30" in msg, msg)
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_empty_compendio():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "empty.md"), "")
    rc, f, _ = run_verify(os.path.join(T, "empty.md"))
    check("coverage: compendio vuoto senza --require-coverage -> W-COV, exit 0",
          rc == 0 and has(f, "WARN", "W-COV"), only_codes(f))
    rc, f, _ = run_verify(os.path.join(T, "empty.md"), require_coverage=True)
    check("coverage: compendio vuoto con --require-coverage -> E-COV, exit 1",
          rc == 1 and has(f, "ERROR", "E-COV"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_no_citation_at_all():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "nocit.md"), "Testo qualunque, nessuna citazione o nome di file.\n")
    rc, f, _ = run_verify(os.path.join(T, "nocit.md"))
    check("coverage: compendio senza alcuna citazione senza --require-coverage -> W-COV",
          rc == 0 and has(f, "WARN", "W-COV"), only_codes(f))
    rc, f, _ = run_verify(os.path.join(T, "nocit.md"), require_coverage=True)
    check("coverage: compendio senza alcuna citazione con --require-coverage -> E-COV",
          rc == 1 and has(f, "ERROR", "E-COV"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_coverage_no_source_files_is_silent():
    T = tmpdir()
    write(os.path.join(T, "c.md"), "Niente da citare in questa cartella.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("coverage: nessun file sotto root (solo il compendio) -> nessun controllo di copertura",
          rc == 0 and f == [], only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-3 / COMP-18: nomi di file e citazioni multiple ----------

def test_citation_accented_and_punctuated_filenames():
    T = tmpdir()
    write(os.path.join(T, "perché.txt"), "1\n2\n")
    write(os.path.join(T, "Contratto (firmato).txt"), "1\n2\n")
    write(os.path.join(T, "l'offerta.txt"), "1\n2\n")
    write(os.path.join(T, "Rossi, Mario.txt"), "1\n2\n3\n")
    write(os.path.join(T, "c.md"),
          "Vedi [perché.txt#L2].\n"
          "Vedi [Contratto (firmato).txt#L1].\n"
          "Vedi [l'offerta.txt#L1].\n"
          "Vedi [Rossi, Mario.txt#L2].\n")
    rc, f, proc = run_verify(os.path.join(T, "c.md"))
    errs = [x for x in f if x["severity"] == "ERROR"]
    check("citazioni: nomi con accenti/parentesi/apostrofo/virgola non danno falsi E-CIT",
          rc == 0 and not errs, (errs, proc.stdout))
    shutil.rmtree(T, ignore_errors=True)


def test_citation_multi_split_semicolon_and_comma():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n2\n3\n")
    write(os.path.join(T, "b.txt"), "1\n2\n3\n")
    write(os.path.join(T, "c.md"),
          "Punto e virgola: [a.txt#L1; b.txt#L2].\n"
          "Virgola dopo cifra: [a.txt#L3, b.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("citazioni multiple: split su ';'/',' dopo una cifra, entrambi i file verificati",
          rc == 0 and not any(x["severity"] == "ERROR" for x in f), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_citation_continuation_same_file():
    T = tmpdir()
    write(os.path.join(T, "f.txt"), "\n".join(str(i) for i in range(1, 11)) + "\n")
    write(os.path.join(T, "c.md"),
          "Continuazione virgola: [f.txt#L1-L3, L9].\n"
          "Continuazione hash: [f.txt#L1; #L5].\n"
          "Continuazione fuori range: [f.txt#L1, L99].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("citazioni: 'L9' e '#L5' di continuazione riferiti all'ultimo file",
          has(f, "ERROR", "E-CIT", "L99") and
          not any(e["line"] in (1, 2) for e in f if e["severity"] == "ERROR"),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-4: niente ripiego per basename con cartelle, ambiguità ----------

def test_no_basename_fallback_with_folder_in_ref():
    T = tmpdir()
    write(os.path.join(T, "docs", "README.md"), "1\n2\n3\n")
    write(os.path.join(T, "c.md"), "Percorso inventato: [contratti/2023/README.md#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("basename: percorso con cartella inesistente NON ripiega sul nome -> E-CIT",
          rc == 1 and has(f, "ERROR", "E-CIT"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_ambiguous_basename_valid_for_one_candidate():
    T = tmpdir()
    write(os.path.join(T, "a_big", "README.md"), "\n".join(str(i) for i in range(1, 51)) + "\n")
    write(os.path.join(T, "z_small", "README.md"), "1\n")
    write(os.path.join(T, "c.md"), "Ambiguo ma valido per uno: [README.md#L40].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("basename ambiguo: valido se lo è per almeno un candidato -> W-AMBIG, non errore",
          rc == 0 and has(f, "WARN", "W-AMBIG") and not has(f, "ERROR", "E-CIT"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_ambiguous_basename_invalid_for_all_is_error():
    T = tmpdir()
    write(os.path.join(T, "a_big", "README.md"), "1\n2\n")
    write(os.path.join(T, "z_small", "README.md"), "1\n")
    write(os.path.join(T, "c.md"), "Ambiguo e fuori range per entrambi: [README.md#L99].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("basename ambiguo: fuori range per TUTTI i candidati -> E-CIT (mai 'il primo trovato')",
          rc == 1 and has(f, "ERROR", "E-CIT"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-5: sigle e nomi senza estensione ----------

def test_undefined_sigla_with_legend_is_error():
    T = tmpdir()
    write(os.path.join(T, "f.txt"), "1\n")
    write(os.path.join(T, "c.md"), "| **CONTR** | `f.txt` |\nCitazione [ALLEGATO_B#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("sigla non definita CON legenda nel documento -> E-CIT (non ignorata)",
          rc == 1 and has(f, "ERROR", "E-CIT", "ALLEGATO_B"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_undefined_token_without_legend_is_warning():
    T = tmpdir()
    write(os.path.join(T, "f.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [f.txt#L1].\nEtichetta libera: [ALLEGATO_X#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("token non risolto SENZA legenda nel documento -> almeno W-CIT (non silenzio)",
          rc == 0 and has(f, "WARN", "W-CIT", "ALLEGATO_X"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_nonexistent_extensionless_name_not_silently_ignored():
    T = tmpdir()
    write(os.path.join(T, "f.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [f.txt#L1].\nFile senza estensione: [Dockerfile#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("nome senza estensione inesistente -> segnalato (avviso o errore), non ignorato",
          has(f, "WARN", "W-CIT", "Dockerfile") or has(f, "ERROR", "E-CIT", "Dockerfile"),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-6: binari e PDF ----------

def test_binary_line_citation_is_warning_not_wrong_count():
    T = tmpdir()
    write(os.path.join(T, "doc.pdf"), ("%PDF fake\n" * 5).encode("ascii"))
    write(os.path.join(T, "doc.docx"), (b"PK\x03\x04 fake\n" * 5))
    write(os.path.join(T, "c.md"), "Cita pdf per riga: [doc.pdf#L2].\nCita docx per riga: [doc.docx#L2].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("citazione #L su PDF/DOCX -> W-BIN, non conteggio sui byte grezzi",
          rc == 0 and has(f, "WARN", "W-BIN", "doc.pdf") and has(f, "WARN", "W-BIN", "doc.docx"),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def _make_minimal_pdf(n_pages):
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {n_pages} >> endobj",
    ]
    for i in range(n_pages):
        page_num = 3 + 2 * i
        content_num = page_num + 1
        objs.append(f"{page_num} 0 obj << /Type /Page /Parent 2 0 R "
                    f"/Resources << >> /MediaBox [0 0 200 200] /Contents {content_num} 0 R >> endobj")
        objs.append(f"{content_num} 0 obj << /Length 20 >>\nstream\nBT /F1 12 Tf (p) Tj ET\nendstream\nendobj")
    body = "%PDF-1.4\n" + "\n".join(objs) + f"\nxref\n0 {3 + 2 * n_pages}\ntrailer << /Root 1 0 R /Size {3 + 2 * n_pages} >>\n%%EOF\n"
    return body.encode("ascii")


def test_pdf_page_citation():
    tools_available = shutil.which("pdfinfo") or shutil.which("pdftotext")
    T = tmpdir()
    write(os.path.join(T, "doc.pdf"), _make_minimal_pdf(2))
    write(os.path.join(T, "c.md"),
          "Pagina 1: [doc.pdf p.1].\nPagina 2: [doc.pdf p.2].\nFuori intervallo: [doc.pdf p.9].\n")
    rc, f, proc = run_verify(os.path.join(T, "c.md"))
    if not tools_available:
        skip("pdf: citazione [doc.pdf p.N]", "pdfinfo/pdftotext non disponibili in questo ambiente")
        shutil.rmtree(T, ignore_errors=True)
        return
    if has(f, "WARN", "W-BIN", "p.1") and has(f, "WARN", "W-BIN", "p.9"):
        # il tool è presente ma non riesce a leggere questo PDF minimale: comportamento
        # comunque corretto e prudente (nessun crash, nessun falso negativo silenzioso).
        skip("pdf: citazione [doc.pdf p.N]", "pdfinfo/pdftotext non hanno letto il PDF di prova")
        shutil.rmtree(T, ignore_errors=True)
        return
    check("pdf: pagine valide (p.1, p.2) non danno errore",
          not any(e["line"] in (1, 2) and e["severity"] == "ERROR" for e in f), only_codes(f))
    check("pdf: pagina fuori intervallo (p.9) -> E-CIT",
          has(f, "ERROR", "E-CIT", "p.9"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-7: E-100 ----------

def test_100_percent_with_citation_is_data_not_error():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "Rimborso: 100% del prezzo\n")
    write(os.path.join(T, "c.md"),
          "## Discrepanze [VERIFICARE]\nNessun punto [VERIFICARE] aperto qui.\n"
          "Dato citato: Rimborso: 100% del prezzo [fonte.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-100: riga con citazione a fonte è un dato, non una dichiarazione",
          rc == 0 and not has(f, "ERROR", "E-100"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_100_left_boundary_excludes_1100():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "x\n")
    write(os.path.join(T, "c.md"), "Vedi [fonte.txt#L1].\nCrescita del 1100%.\n[VERIFICARE] aperto\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-100: '1100%' non è '100%' con confine sinistro",
          not has(f, "ERROR", "E-100") and not has(f, "WARN", "E-100"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_100_headings_and_code_blocks_excluded_from_open_points():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "x\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\n"
          "## Discrepanze [VERIFICARE]\n"
          "```\n[VERIFICARE] dentro codice\n```\n"
          "Copertura totale del progetto.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-100: intestazioni e blocchi di codice non contano come punti [VERIFICARE] aperti "
          "(dichiarazione senza punti aperti -> solo avviso, non errore)",
          not has(f, "ERROR", "E-100") and has(f, "WARN", "E-100"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_100_no_open_points_sentence_excluded():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "x\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\nNessun punto [VERIFICARE] aperto.\nAnalizzati integralmente tutti i file.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-100: dichiarazione esplicita 'nessun punto aperto' non conta come aperto",
          not has(f, "ERROR", "E-100"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_100_asymmetric_quotes_not_treated_as_quoted():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "x\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\n[VERIFICARE] punto vero aperto.\n"
          "Il documento «A» e completo al 100% come indicato in «B».\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-100: caso «A» ... «B» non è una citazione letterale tra virgolette -> rilevato",
          has(f, "ERROR", "E-100"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_100_genuinely_quoted_is_ignored():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "x\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\n[VERIFICARE] punto vero aperto.\n"
          "Il file dichiara «completo al 100%» testualmente.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-100: dato riportato letteralmente tra virgolette non è una dichiarazione",
          not has(f, "ERROR", "E-100"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-8: E-HASH / W-HASH ----------

def test_hash_in_code_is_ignored():
    T = tmpdir()
    write(os.path.join(T, "f.txt"), "1\n2\n")
    fake_hash = hashlib.sha256(b"qualcosa").hexdigest()
    write(os.path.join(T, "c.md"),
          f"Vedi [f.txt#L1].\n```\nFROM img@sha256:{fake_hash}\n```\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-HASH: hash dentro codice recintato ignorato del tutto",
          rc == 0 and not has(f, "ERROR", "E-HASH") and not has(f, "WARN", "W-HASH"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_hash_named_file_must_match():
    T = tmpdir()
    p = os.path.join(T, "f.txt")
    write(p, "1\n2\n")
    real = sha256_of(p)
    wrong = hashlib.sha256(b"altro").hexdigest()
    write(os.path.join(T, "c.md"),
          f"Corretto: `f.txt` {real}\nSbagliato: `f.txt` {wrong}\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-HASH: file nominato tra backtick con hash sbagliato -> errore",
          rc == 1 and has(f, "ERROR", "E-HASH"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_hash_named_via_link_and_table_cell():
    T = tmpdir()
    p = os.path.join(T, "f.txt")
    write(p, "1\n2\n")
    real = sha256_of(p)
    write(os.path.join(T, "c.md"),
          f"Link: [f.txt](f.txt) {real}\nTabella: | f.txt | {real} |\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-HASH: nome riconosciuto anche da link Markdown e cella di tabella",
          rc == 0 and not has(f, "ERROR", "E-HASH"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_hash_unnamed_mismatch_is_warning_not_error():
    T = tmpdir()
    write(os.path.join(T, "f.txt"), "1\n2\n")
    zero = "0" * 64
    write(os.path.join(T, "c.md"), f"Vedi [f.txt#L1].\nImpronta isolata: {zero}\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("W-HASH: hash senza file nominato che non combacia -> avviso, non errore",
          rc == 0 and has(f, "WARN", "W-HASH") and not has(f, "ERROR", "E-HASH"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_hash_ambiguous_named_file_valid_for_one_candidate():
    T = tmpdir()
    write(os.path.join(T, "d1", "README.md"), "a\n")
    p2 = os.path.join(T, "d2", "README.md")
    write(p2, "b\n")
    h2 = sha256_of(p2)
    write(os.path.join(T, "c.md"), f"Inventario: `README.md` {h2}\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-HASH: nome ambiguo tra backtick, hash valido per uno dei candidati -> nessun errore",
          rc == 0 and not has(f, "ERROR", "E-HASH") and has(f, "WARN", "W-AMBIG"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_hash_unnamed_match_is_silent():
    T = tmpdir()
    p = os.path.join(T, "f.txt")
    write(p, "1\n2\n")
    real = sha256_of(p)
    write(os.path.join(T, "c.md"), f"Vedi [f.txt#L1].\nImpronta isolata che combacia: {real}\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("hash isolato che combacia con un file -> nessuna segnalazione",
          rc == 0 and not has(f, "WARN", "W-HASH") and not has(f, "ERROR", "E-HASH"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-9: recinzione non chiusa ----------

def test_unclosed_fence_warns_and_masks_rest():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "c.md"),
          "Prima della recinzione [a.txt#L1].\n```\n[manca.txt#L9]\n[VERIFICARE] aperto\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("W-FENCE: recinzione non chiusa segnalata e resto del file non genera altri errori",
          rc == 0 and has(f, "WARN", "W-FENCE") and not any(x["severity"] == "ERROR" for x in f),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-10: fuori radice / autocitazione ----------

def test_citation_outside_root_and_self():
    T = tmpdir()
    root = os.path.join(T, "root")
    outside = os.path.join(T, "outside")
    write(os.path.join(root, "a.txt"), "1\n")
    write(os.path.join(outside, "secret.txt"), "1\n")
    write(os.path.join(root, "base.md"),
          "Fuori radice: [../outside/secret.txt#L1].\n"
          "Autocitazione: [base.md#L1].\n"
          "Link fuori: [x](../outside/secret.txt).\n"
          "Link self: [y](base.md).\n"
          "Vedi [a.txt#L1].\n")
    rc, f, _ = run_verify(os.path.join(root, "base.md"), root=root)
    check("E-CIT/E-LINK: fonte fuori dalla radice -> errore",
          has(f, "ERROR", "E-CIT", "fuori dalla radice") and has(f, "ERROR", "E-LINK", "fuori dalla radice"),
          only_codes(f))
    check("E-CIT/E-LINK: autocitazione al compendio stesso -> errore",
          has(f, "ERROR", "E-CIT", "compendio stesso") and has(f, "ERROR", "E-LINK", "compendio stesso"),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-11: E-LINK e schemi URI ----------

def test_link_schemes_and_protocol_relative_ignored():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "c.md"),
          "Vedi [z](a.txt).\n"
          "[a](ftp://files.example.com/x.zip)\n"
          "[b](HTTPS://Example.com/x)\n"
          "[c](sftp://host/path)\n"
          "[d](doi:10.1000/xyz123)\n"
          "[e](//cdn.example.com/lib.js)\n"
          "[f](mailto:a@b.com)\n"
          "[g](tel:+391234567)\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-LINK: schemi non http(s) (ftp/sftp/doi/mailto/tel), maiuscoli e //host non "
          "generano falsi E-LINK",
          rc == 0 and not has(f, "ERROR", "E-LINK"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_link_genuinely_broken_still_detected():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [z](a.txt).\n[x](manca-davvero.md)\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("E-LINK: un link relativo davvero rotto resta un errore",
          rc == 1 and has(f, "ERROR", "E-LINK", "manca-davvero.md"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-15: robustezza ----------

def test_broken_symlink_no_crash():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    try:
        os.symlink(os.path.join(T, "manca_target.txt"), os.path.join(T, "rotto.txt"))
        symlink_ok = True
    except (OSError, NotImplementedError):
        symlink_ok = False
    if not symlink_ok:
        skip("robustezza: symlink rotto sotto root non causa crash",
             "impossibile creare symlink in questo ambiente (Windows senza privilegio)")
        shutil.rmtree(T, ignore_errors=True)
        return
    write(os.path.join(T, "c.md"),
          "D.P.R. 430/2001 citato per forzare la lettura del corpus.\nVedi [a.txt#L1].\n")
    rc, f, proc = run_verify(os.path.join(T, "c.md"))
    check("robustezza: un symlink rotto sotto root non fa andare in crash il verificatore",
          proc.returncode in (0, 1) and "Traceback" not in proc.stderr, proc.stderr[:400])
    shutil.rmtree(T, ignore_errors=True)


def test_unreadable_file_no_crash():
    if os.name != "posix":
        skip("robustezza: file non leggibile non causa crash", "test POSIX-only (permessi Windows non simulabili)")
        return
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    p = os.path.join(T, "segreto.txt")
    write(p, "1\n2\n3\n")
    os.chmod(p, 0)
    try:
        write(os.path.join(T, "c.md"), "D.P.R. 430/2001 per forzare corpus.\nVedi [a.txt#L1].\n")
        rc, f, proc = run_verify(os.path.join(T, "c.md"))
        check("robustezza: file senza permesso di lettura non fa andare in crash il verificatore",
              proc.returncode in (0, 1) and "Traceback" not in proc.stderr, proc.stderr[:400])
    finally:
        os.chmod(p, 0o644)
        shutil.rmtree(T, ignore_errors=True)


def test_only_regular_files_indexed_fifo_or_dir_skipped():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    os.makedirs(os.path.join(T, "unadir.txt"), exist_ok=True)  # una "cartella" con nome da file
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\n[unadir.txt#L1]\n")
    rc, f, proc = run_verify(os.path.join(T, "c.md"))
    check("robustezza: una cartella con nome da file non è indicizzata come file (nessun crash)",
          "Traceback" not in proc.stderr and has(f, "ERROR", "E-CIT", "unadir.txt"), proc.stderr[:400])
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-16: W-NORM tollerante ----------

def test_norm_tolerant_to_punctuation_variants():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "Si applica il DPR n. 430/2001 e il D. Lgs. 196/2003.\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\n"
          "Norma 1: D.P.R. 430/2001.\n"
          "Norma 2: D.Lgs. 196/2003.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("W-NORM: varianti di punteggiatura/spaziatura (DPR/D.P.R., D.Lgs./D. Lgs.) tollerate",
          not has(f, "WARN", "W-NORM"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_norm_absent_warns_and_external_knowledge_silences():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "Nessuna norma qui.\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\n"
          "Norma inventata: Legge 190/2012.\n"
          "Norma esterna: [CONOSCENZA ESTERNA] Reg. UE 2016/679.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("W-NORM: norma assente dalle fonti segnalata",
          has(f, "WARN", "W-NORM", "190/2012"), only_codes(f))
    check("W-NORM: [CONOSCENZA ESTERNA] non genera avviso",
          not has(f, "WARN", "W-NORM", "2016/679"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- COMP-17: W-DED confidenza esplicita ----------

def test_dedotto_requires_real_confidence():
    T = tmpdir()
    write(os.path.join(T, "fonte.txt"), "x\n")
    write(os.path.join(T, "c.md"),
          "Vedi [fonte.txt#L1].\n"
          "[DEDOTTO] confidenza: Alta, dal titolo.\n"
          "[DEDOTTO] valore (Bassa).\n"
          "[DEDOTTO] la soglia e alta perche lo dice il titolo.\n"
          "[DEDOTTO] vedi D03.\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    ded_lines = {x["line"] for x in f if x["code"] == "W-DED"}
    check("W-DED: 'confidenza: Alta' e '(Bassa)' soddisfano il requisito -> nessun avviso",
          2 not in ded_lines and 3 not in ded_lines, ded_lines)
    check("W-DED: un aggettivo comune non legato a 'confidenza' NON basta",
          4 in ded_lines, ded_lines)
    check("W-DED: un rimando a un ID ('D03') non è una confidenza dichiarata",
          5 in ded_lines, ded_lines)
    shutil.rmtree(T, ignore_errors=True)


# ---------- W-PATH ----------

def test_wpath_absolute_backtick_path():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "c.md"),
          "Vedi [a.txt#L1].\nPercorso: `/home/utente/sicuramente_non_esiste_xyz.txt`\n")
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("W-PATH: percorso assoluto inesistente in backtick segnalato",
          has(f, "WARN", "W-PATH"), only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


# ---------- uso generale / codici d'uscita ----------

def test_exit_code_file_not_found():
    T = tmpdir()
    proc = subprocess.run([sys.executable, VERIFY, os.path.join(T, "manca.md")],
                          capture_output=True, text=True)
    check("uso: file inesistente -> exit 2", proc.returncode == 2, proc.stderr)
    shutil.rmtree(T, ignore_errors=True)


def test_exit_code_root_not_found():
    T = tmpdir()
    write(os.path.join(T, "a.md"), "x\n")
    proc = subprocess.run([sys.executable, VERIFY, os.path.join(T, "a.md"),
                           "--root", os.path.join(T, "manca")], capture_output=True, text=True)
    check("uso: --root inesistente -> exit 2", proc.returncode == 2, proc.stderr)
    shutil.rmtree(T, ignore_errors=True)


def test_exit_code_warnings_only_is_zero():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "b.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\n")  # b.txt non citato -> solo W-COV
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    check("uso: solo avvisi -> exit 0", rc == 0 and any(x["severity"] == "WARN" for x in f),
          only_codes(f))
    shutil.rmtree(T, ignore_errors=True)


def test_json_output_shape():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\n")
    proc = subprocess.run([sys.executable, VERIFY, "--json", os.path.join(T, "c.md")],
                          capture_output=True, text=True)
    data = json.loads(proc.stdout)
    check("--json: struttura dell'output (file/root/errors/warnings/findings)",
          all(k in data for k in ("file", "root", "errors", "warnings", "findings")), data)
    shutil.rmtree(T, ignore_errors=True)


def test_quiet_shows_only_errors():
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "b.txt"), "1\n")
    write(os.path.join(T, "c.md"), "Vedi [a.txt#L1].\nRotto: [g.txt#L1].\n")
    proc = subprocess.run([sys.executable, VERIFY, "--quiet", os.path.join(T, "c.md")],
                          capture_output=True, text=True)
    check("--quiet: nessuna riga WARN nell'output testuale",
          "WARN" not in proc.stdout and "ERROR" in proc.stdout, proc.stdout)
    shutil.rmtree(T, ignore_errors=True)


# ---------- prestazioni ----------

def test_performance_5000_files():
    T = tmpdir()
    n = 5000
    for i in range(n):
        write(os.path.join(T, f"f{i:05d}.txt"), "riga\n" * 20)
    lines = [f"Vedi [f{i:05d}.txt#L3]." for i in range(0, n, 2)]
    write(os.path.join(T, "c.md"), "\n".join(lines) + "\n")
    t0 = time.time()
    rc, f, proc = run_verify(os.path.join(T, "c.md"))
    elapsed = time.time() - t0
    check(f"prestazioni: 5000 file / 2500 citazioni in tempo ragionevole ({elapsed:.1f}s)",
          elapsed < 30 and "Traceback" not in proc.stderr, proc.stderr[:400])
    shutil.rmtree(T, ignore_errors=True)


def test_performance_unbalanced_brackets():
    # regressione: RE_MDLINK con [^\]]* era O(n²) su righe piene di "[" non chiuse (~44 s)
    T = tmpdir()
    write(os.path.join(T, "a.txt"), "1\n")
    write(os.path.join(T, "c.md"), "[" * 200000 + "\nVedi [a.txt#L1].\n")
    t0 = time.monotonic()
    rc, f, _ = run_verify(os.path.join(T, "c.md"))
    dt = time.monotonic() - t0
    check("prestazioni: riga con 200000 '[' non chiuse verificata in fretta (%.1fs)" % dt, dt < 10, dt)
    shutil.rmtree(T, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
        except Exception as exc:  # non deve mai bloccare l'intera suite
            ko(t.__name__, f"eccezione non gestita: {exc!r}")
    print(f"\nEsito: {passed} superati, {failed} falliti")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
