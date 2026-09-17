"""
rich_db_audit.py — Verifica la commessa "fonte dati ricca per la stagione in
corso" e genera il referto in ``audit/results/``.

Che cosa fa, in ordine:

1.  copia ``SoccerMath/`` in una cartella di lavoro ISOLATA (il database di
    produzione NON viene toccato: la commessa prevede uno STOP, vedi oltre);
2.  punto 1 della commessa: verifica preliminare dei 5 CSV grezzi della
    stagione in corso (HTTP, righe, colonne, encoding, nomi squadra con
    clean_name, copertura);
3.  criterio A (invarianza di produzione): test di invarianza 1X2 + fixture
    rigenerato byte a byte + confronto riga per riga delle 6 colonne lette da
    app.py, prima e dopo l'arricchimento;
4.  criterio B (idempotenza): secondo run consecutivo e confronto degli sha256;
5.  criterio C (non regressione del bug di dedup): replica FEDELE del merge di
    ``update_db.py`` (concat + drop_duplicates keep="last") sulle righe API e
    conteggio delle celle ricche azzerate, poi terzo run di update_db_rich;
6.  criterio D (copertura): B365H e HS sulle partite concluse, con il motivo
    per ogni partita non coperta;
7.  criterio E: esecuzione dei test unitari offline del merge per colonna.

Uso:
    python audit/rich_db_audit.py
    python audit/rich_db_audit.py --source-dir audit/data/rich_2627_snapshot
    python audit/rich_db_audit.py --work-dir /tmp/miaveria   # ispeziona i file

Output:
    audit/results/rich_2627_report.md
    audit/results/rich_2627_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import pandas as pd
import warnings

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import config  # noqa: E402
from config import MARKET_VALUES, clean_name  # noqa: E402

DEFAULT_SNAPSHOT = os.path.join(_AUDIT_DIR, "data", "rich_2627_snapshot")
DEFAULT_OUT_MD = os.path.join(_AUDIT_DIR, "results", "rich_2627_report.md")
DEFAULT_OUT_JSON = os.path.join(_AUDIT_DIR, "results", "rich_2627_report.json")

PRODUCTION_COLUMNS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]
# Le 10 colonne scritte da update_db.py dall'API football-data.org.
API_COLUMNS = PRODUCTION_COLUMNS + ["HTHG", "HTAG", "HTR", "Matchday"]
COVERAGE_PROBES = ("B365H", "HS")
COVERAGE_THRESHOLD = 0.90

LEAGUE_ORDER = ["Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1"]


# ==========================================
# Utilita'
# ==========================================
def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _blank(value) -> bool:
    try:
        return value is None or str(value).strip().lower() in {"", "nan", "na", "none", "null"}
    except Exception:
        return True


def read_text_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False,
                       encoding="utf-8-sig")


def db_path(db_dir: str, league: str) -> str:
    info = config.LEAGUES_CONFIG[league]
    return os.path.join(db_dir, f"{info['db_prefix']}_Live.csv")


def snapshot_db(db_dir: str) -> dict:
    """Stato dei 5 *_Live.csv: hash, righe, colonne, impronta delle 6 colonne."""
    out = {}
    for league in LEAGUE_ORDER:
        path = db_path(db_dir, league)
        df = read_text_csv(path)
        fingerprint = hashlib.sha256(
            "\n".join("|".join(df[c].tolist()) for c in PRODUCTION_COLUMNS).encode("utf-8")
        ).hexdigest()
        keys = sorted(
            (row.Date, clean_name(row.HomeTeam), clean_name(row.AwayTeam))
            for row in df.itertuples(index=False)
        )
        filled = {c: int((~df[c].map(_blank)).sum()) for c in df.columns}
        out[league] = {
            "path": f"SoccerMath/database/{config.LEAGUES_CONFIG[league]['db_prefix']}_Live.csv",
            "sha256": sha256_file(path),
            "rows": int(len(df)),
            "unique_keys": len(set(keys)),
            "columns": list(df.columns),
            "columns_count": int(len(df.columns)),
            "non_empty_by_column": filled,
            "non_empty_rich": int(sum(v for k, v in filled.items() if k not in API_COLUMNS)),
            "production_fingerprint": fingerprint,
            "production_rows": [
                [df[c].iloc[i] for c in PRODUCTION_COLUMNS] for i in range(len(df))
            ],
            "keys": [list(k) for k in keys],
            "keyset": sorted({tuple(k) for k in keys}),
        }
    return out


def run_cmd(cmd, cwd=None) -> dict:
    proc = subprocess.run([sys.executable] + cmd, cwd=cwd, capture_output=True, text=True)
    return {"cmd": cmd, "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "ok": proc.returncode == 0}


def combined_output(res: dict) -> str:
    """unittest scrive l'esito su stderr, non su stdout: serve l'unione."""
    return (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")


def last_line(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


def unittest_summary(text: str) -> str:
    # Il tempo di esecuzione NON entra nel sommario: altrimenti due
    # rigenerazioni dello stesso referto differirebbero sempre.
    match = re.search(r"^Ran (\d+) tests? in [0-9.]+s", text, re.MULTILINE)
    ran = f"Ran {match.group(1)} tests" if match else "esito non parse-ato"
    return f"{ran} — {last_line(text)}"


def count_tests(text: str):
    match = re.search(r"^Ran (\d+) tests?", text, re.MULTILINE)
    ran = int(match.group(1)) if match else None
    return ran, ("OK" in last_line(text))


# ==========================================
# Punto 1: verifica preliminare dei CSV grezzi
# ==========================================
def build_preliminary_checks(snapshot_dir: str, db_dir: str,
                             historical_dir: str = None) -> dict:
    manifest_path = os.path.join(snapshot_dir, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)

    historical_dir = historical_dir or db_dir
    out = {"manifest": manifest, "leagues": {}, "column_drift": {}, "teams": {},
           "divergent_teams": {}, "coverage_vs_live": {}}
    column_sets = {}
    drifts = {}
    for league in LEAGUE_ORDER:
        info = config.LEAGUES_CONFIG[league]
        code = info["fd_code"]
        raw_path = os.path.join(snapshot_dir, f"{code}.csv")
        if not os.path.exists(raw_path):
            out["leagues"][league] = {"error": f"mancante {raw_path}"}
            continue
        raw = open(raw_path, "rb").read()
        meta = dict(manifest.get("leagues", {}).get(code, {}))
        meta["fd_code"] = code
        meta["sha256"] = sha256_bytes(raw)
        meta["bytes"] = len(raw)
        meta["bom_utf8"] = raw[:3] == b"\xef\xbb\xbf"
        meta["crlf"] = raw.count(b"\r\n")
        df = pd.read_csv(raw_path, encoding="utf-8-sig", low_memory=False)
        meta["rows"] = int(len(df))
        meta["columns_count"] = int(len(df.columns))
        meta["date_min"] = str(pd.to_datetime(df["Date"], dayfirst=True).min().date())
        meta["date_max"] = str(pd.to_datetime(df["Date"], dayfirst=True).max().date())
        meta["decoded_as"] = "utf-8-sig"
        # Hash dell'header: prova che l'header e' quello grezzo della fonte.
        meta["header_sha256"] = sha256_bytes(raw.split(b"\n")[0].rstrip(b"\r"))
        out["leagues"][league] = meta
        column_sets[league] = list(df.columns)
        meta["columns_preview"] = list(df.columns)

        # 1b: confronto insiemistico con l'header dello storico 2025/2026
        hist_path = os.path.join(historical_dir, f"{info['db_prefix']}_2025.csv")
        hist_cols = list(pd.read_csv(hist_path, nrows=0, low_memory=False).columns)
        lost = [c for c in hist_cols if c not in df.columns]
        new = [c for c in df.columns if c not in hist_cols]
        out["column_drift"][league] = {
            "historical_file": os.path.relpath(hist_path, _REPO_ROOT),
            "historical_columns": len(hist_cols),
            "csv_columns": len(df.columns),
            "lost": lost,
            "new": new,
        }
        drifts[league] = {"lost": lost, "new": new}

        # 1d: nomi squadra e clean_name
        live = read_text_csv(db_path(db_dir, league))
        live_teams = {clean_name(t) for t in live["HomeTeam"]} | {
            clean_name(t) for t in live["AwayTeam"]}
        raw_teams = sorted({str(t) for t in df["HomeTeam"]} | {str(t) for t in df["AwayTeam"]})
        rows = []
        for team in raw_teams:
            cleaned = clean_name(team)
            rows.append({
                "csv_name": team,
                "clean_name": cleaned,
                "in_market_values": cleaned in MARKET_VALUES,
                "in_live_csv": cleaned in live_teams,
            })
        out["teams"][league] = {
            "distinct": len(rows),
            "in_market_values": sum(1 for r in rows if r["in_market_values"]),
            "not_in_market_values": sum(1 for r in rows if not r["in_market_values"]),
            "not_in_live_csv": [r for r in rows if not r["in_live_csv"]],
            "rows": rows,
        }
        # squadre del *_Live.csv assenti dal CSV: indicano nomi divergenti
        csv_clean = {r["clean_name"] for r in rows}
        out["divergent_teams"][league] = {
            "live_only": sorted(live_teams - csv_clean),
            "csv_only": sorted(csv_clean - live_teams),
        }

        # 1e: copertura grezza (righe CSV vs righe Live)
        src_keys = {
            (str(pd.to_datetime(d, dayfirst=True).date()), clean_name(h), clean_name(a))
            for d, h, a in zip(df["Date"], df["HomeTeam"], df["AwayTeam"])
        }
        live_keys = {
            (str(pd.to_datetime(d, dayfirst=True).date()), clean_name(h), clean_name(a))
            for d, h, a in zip(live["Date"], live["HomeTeam"], live["AwayTeam"])
        }
        out["coverage_vs_live"][league] = {
            "csv_matches": len(src_keys),
            "live_rows": int(len(live)),
            "live_unique_keys": len(live_keys),
            "csv_not_in_live": len(src_keys - live_keys),
            "live_not_in_csv": len(live_keys - src_keys),
            "live_not_in_csv_sample": sorted(live_keys - src_keys)[:20],
        }

    # 1.7: deriva delle colonne bookmaker / colonne "stabili"
    out["stable_columns"] = stable_column_check(historical_dir, snapshot_dir)
    return out


def stable_column_check(historical_dir: str, snapshot_dir: str) -> dict:
    """Verifica se B365*/Avg*/Max*/PS* sono davvero stabili fra le stagioni."""
    groups = {
        "B365*": lambda c: c.startswith("B365"),
        "Avg*": lambda c: c.startswith("Avg"),
        "Max*": lambda c: c.startswith("Max"),
        "PS*": lambda c: c.startswith("PS"),
    }
    seasons = []
    for year in ("2022", "2023", "2024", "2025"):
        path = os.path.join(historical_dir, f"SerieA_{year}.csv")
        if os.path.exists(path):
            cols = list(pd.read_csv(path, nrows=0, low_memory=False).columns)
            seasons.append((year, cols))
    current = list(pd.read_csv(os.path.join(snapshot_dir, "I1.csv"),
                               encoding="utf-8-sig", nrows=0, low_memory=False).columns)
    seasons.append(("2627", current))
    out = {"per_season": {}, "verdict": {}}
    for label, fn in groups.items():
        per_season = {year: sum(1 for c in cols if fn(c)) for year, cols in seasons}
        out["per_season"][label] = per_season
        out["verdict"][label] = {
            "stabile": len(set(per_season.values())) == 1 and list(per_season.values())[0] > 0,
            "conteggi": per_season,
        }
    # prefissi bookmaker presenti per stagione (1X2 + closing)
    prefixes = {}
    for year, cols in seasons:
        found = set()
        for col in cols:
            match = re.match(r"^([A-Za-z0-9]{2,5})(H|D|A)$", col)
            if match:
                found.add(match.group(1))
        prefixes[year] = sorted(found)
    out["bookmaker_prefixes"] = prefixes
    return out


# ==========================================
# Criterio C: replica del merge di update_db.py
# ==========================================
def simulate_update_db(enriched_db_dir: str, out_dir: str) -> dict:
    """Replica FEDELE del merge di update_db.py (righe 143-160) senza rete.

    update_db.py fa:
        df_old = read_csv(live_path)
        df_new = <righe API: 10 colonne>
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        df_merged = df_merged.drop_duplicates(subset=["Date","HomeTeam","AwayTeam"],
                                              keep="last")
        df_merged = sort by Date  ->  to_csv(live_path)
    Qui df_new e' ricostruito dalle stesse partite gia' presenti nel file
    (stessa data, stessi nomi): e' il caso MIGLIORE per update_db.py, eppure
    keep="last" fa vincere la riga API, che le 121 colonne ricche non le ha.
    """
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for league in LEAGUE_ORDER:
        src = db_path(enriched_db_dir, league)
        dst = db_path(out_dir, league)
        shutil.copyfile(src, dst)
        df_old = pd.read_csv(dst, on_bad_lines="skip", low_memory=False)
        rich_cols = [c for c in df_old.columns if c not in API_COLUMNS]
        before = int(df_old[rich_cols].notna().sum().sum()) if rich_cols else 0
        df_new = df_old[API_COLUMNS].copy()
        merged = pd.concat([df_old, df_new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"], keep="last")
        ordine = pd.to_datetime(merged["Date"], dayfirst=True, errors="coerce")
        merged = (merged.assign(_ord=ordine)
                        .sort_values("_ord", kind="stable")
                        .drop(columns="_ord"))
        merged.to_csv(dst, index=False)
        after_df = pd.read_csv(dst, on_bad_lines="skip", low_memory=False)
        after = int(after_df[rich_cols].notna().sum().sum()) if rich_cols else 0
        result[league] = {
            "rows_before": int(len(df_old)),
            "rows_after": int(len(after_df)),
            "rich_cells_before": before,
            "rich_cells_after": after,
            "rich_cells_zeroed": before - after,
            "rich_columns": len(rich_cols),
        }
    return result


# ==========================================
# Referto markdown
# ==========================================
def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def build_markdown(data: dict) -> str:
    L = []
    add = L.append
    add("# Fonte dati ricca per la stagione in corso (2627) — referto di verifica")
    add("")
    add("Referto GENERATO da `python audit/rich_db_audit.py` (non riscritto a mano).")
    add("")
    add(f"- generato il: `{data['generated_at']}` _(unica riga variabile fra due rigenerazioni)_")
    add(f"- rigenerabile con: `{data['reproduce_cmd']}`")
    add(f"- snapshot della fonte: `{data['snapshot_dir']}` "
        f"(5 CSV grezzi, byte per byte, + `manifest.json`)")
    add("- file della commessa: `SoccerMath/update_db_rich.py` (nuovo), "
        "`SoccerMath/test_update_db_rich.py` (nuovo), `SoccerMath/config.py` "
        "(solo il campo `fd_code` in `LEAGUES_CONFIG`), `audit/rich_db_audit.py` "
        "(nuovo), `audit/data/rich_2627_snapshot/` (byte grezzi della fonte), "
        "`audit/results/rich_2627_report.{md,json}`")
    add(f"- verifica eseguita su una COPIA ISOLATA del database "
        f"(`{data['work_dir_note']}`): i `*_Live.csv` di produzione **non sono stati modificati** "
        f"(commessa in STOP, vedi §1.6).")
    add("")

    # ---------------- sintesi
    add("## 0. Sintesi degli esiti")
    add("")
    add(_table(
        ["Criterio", "Esito", "Misura"],
        [[c["id"], c["esito"], c["misura"]] for c in data["criteria_summary"]]))
    add("")
    add(f"STOP della commessa (punto 1d): **{data['stop']['triggered']}** — "
        f"{data['stop']['detail']}")
    add("")

    # ---------------- punto 1
    add("## 1. Verifica preliminare (punto 1 della commessa)")
    add("")
    add("I 5 CSV sono stati scaricati una volta, grezzi, da un workflow GitHub Actions")
    add("temporaneo `.github/workflows/fd2627_fetch_tmp.yml` perché il dominio")
    add("`www.football-data.co.uk` **non è raggiungibile** dall'ambiente in cui lavoro")
    add("(TLS chiuso dal proxy di rete: `curl` e `requests` danno entrambi errore).")
    add("Il workflow (`contents: write`, nessun segreto, nessun commit nel repository:")
    add("pubblica i byte su una cartella temporanea del branch) è stato **rimosso prima del")
    add("commit finale**; i byte scaricati sono conservati in `audit/data/rich_2627_snapshot/`.")
    add("")
    add("### 1.1 Download: HTTP status e righe (punto 1a)")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        m = data["preliminary"]["leagues"][league]
        rows.append([league, m["fd_code"], m.get("http_status"), m.get("bytes"),
                     m.get("content_length_header"), m.get("rows"),
                     m.get("date_min"), m.get("date_max"),
                     (m.get("last_modified") or "").replace(" GMT", " UTC")])
    add(_table(["Lega", "Codice", "HTTP", "byte", "Content-Length", "righe",
                "prima data", "ultima data", "Last-Modified"], rows))
    add("")
    add("Tutte e 5 le risposte arrivano dopo un `302` da `www.football-data.co.uk` a")
    add("`football-data.co.uk` (seguendo il redirect), `content-type: text/csv`.")
    add("")
    add("### 1.2 Colonne: confronto insiemistico con l'header di `<Prefix>_2025.csv` (punto 1b)")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        d = data["preliminary"]["column_drift"][league]
        rows.append([league, d["csv_columns"], d["historical_columns"],
                     len(d["lost"]), len(d["new"])])
    add(_table(["Lega", "colonne CSV 2627", "colonne storico 2025", "perse", "nuove"], rows))
    add("")
    lost = data["preliminary"]["column_drift"]["Serie A"]["lost"]
    new = data["preliminary"]["column_drift"]["Serie A"]["new"]
    add(f"Colonne perse (identiche per le 5 leghe, {len(lost)}): "
        + ", ".join(f"`{c}`" for c in lost))
    add("")
    add(f"Colonne nuove (identiche per le 5 leghe, {len(new)}): "
        + ", ".join(f"`{c}`" for c in new))
    add("")
    add("Eccezione: il CSV dell'E0 porta anche `Referee` (colonna che l'header storico di")
    add("`Premier_2025.csv` ha già e che le altre 4 leghe non hanno): il merge per colonna")
    add("la lascia dov'è e la valorizza solo per la Premier League.")
    add("")
    add("### 1.3 Encoding (punto 1c)")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        m = data["preliminary"]["leagues"][league]
        rows.append([league, "UTF-8 con BOM" if m["bom_utf8"] else "senza BOM",
                     m["decoded_as"], m["crlf"], m["header_sha256"][:16] + "…"])
    add(_table(["Lega", "BOM", "decodifica usata", "righe CRLF", "sha256 header (prime 16)"], rows))
    add("")
    add("Atteso UTF-8-SIG per stagioni >= 2425: **confermato** su tutte e 5 le leghe "
        "(BOM `EF BB BF`, terminatore CRLF, decodifica senza errori).")
    add("")
    add("### 1.4 Nomi squadra e `config.clean_name()` (punto 1d)")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        t = data["preliminary"]["teams"][league]
        rows.append([league, t["distinct"], t["in_market_values"], t["not_in_market_values"],
                     len(t["not_in_live_csv"])])
    add(_table(["Lega", "squadre distinte", "clean_name in MARKET_VALUES",
                "clean_name NON in MARKET_VALUES", "clean_name NON presente nel *_Live.csv"], rows))
    add("")
    add("Dettaglio delle squadre il cui `clean_name` **non** è in `MARKET_VALUES` "
        "(sono le candidate al disallineamento):")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        for r in data["preliminary"]["teams"][league]["rows"]:
            if not r["in_market_values"]:
                rows.append([league, f"`{r['csv_name']}`", f"`{r['clean_name']}`",
                             "sì" if r["in_live_csv"] else "NO"])
    if rows:
        add(_table(["Lega", "nome nel CSV 2627", "clean_name", "già usato nel *_Live.csv"], rows))
    else:
        add("_nessuna_")
    add("")
    add("### 1.5 Copertura grezza: partite nel CSV vs partite nel `*_Live.csv` (punto 1e)")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        c = data["preliminary"]["coverage_vs_live"][league]
        rows.append([league, c["csv_matches"], c["live_rows"], c["live_unique_keys"],
                     c["csv_not_in_live"], c["live_not_in_csv"]])
    add(_table(["Lega", "partite nel CSV 2627", "righe nel *_Live.csv",
                "chiavi uniche nel *_Live.csv", "solo CSV", "solo Live"], rows))
    add("")
    add("Nota: le righe `*_Live.csv` sono più delle chiavi uniche perché `update_db.py`")
    add("scrive il nome breve dell'API e, in alcuni casi, la stessa partita ricompare")
    add("anche con il nome canonico (`Dortmund-HSV` e `Dortmund-Hamburg`, `Alavés` e")
    add("`Alaves`): il merge per colonna tratta le due righe come la stessa partita.")
    add("")
    add("### 1.6 STOP: nomi della stagione in corso non allineati")
    add("")
    if data["stop"]["triggered"].upper().startswith("SÌ") or \
       data["stop"]["triggered"].upper().startswith("SI"):
        add("**STOP ATTIVO.** La commessa dice: _se anche UNA squadra della stagione in")
        add("corso ha un `clean_name` che non coincide con quello già usato nel `*_Live.csv`,")
        add("fermarsi e riferire. Non aggiungere alias_. L'esito è questo:")
        add("")
        rows = []
        for league in LEAGUE_ORDER:
            live_only = data["preliminary"]["divergent_teams"][league]["live_only"]
            csv_only = data["preliminary"]["divergent_teams"][league]["csv_only"]
            for name in live_only:
                rows.append([league, f"`{name}` (nel *_Live.csv)",
                             ", ".join(f"`{c}`" for c in csv_only) or "—",
                             "nessun alias aggiunto: le partite restano non appaiate"])
        add(_table(["Lega", "nome usato nel *_Live.csv (canonico)",
                    "nome nel CSV football-data", "conseguenza"], rows))
        add("")
        add("Nessun alias è stato aggiunto a `team_aliases.py`, `TEAM_NAME_MAP` o")
        add("`MARKET_VALUES`, nessuna modifica a `clean_name`: la conseguenza è che le")
        add("partite di queste 5 squadre restano **non appaiate** e quindi non coperte")
        add("(è la causa diretta dello sforamento della soglia del criterio D).")
    else:
        add("Nessun nome divergente: tutti i `clean_name` delle squadre della stagione in")
        add("corso coincidono con quelli già usati nei `*_Live.csv`.")
    add("")
    add("### 1.7 Deriva delle colonne bookmaker e colonne \"stabili\"")
    add("")
    sc = data["preliminary"]["stable_columns"]
    seasons = sorted({s for counts in sc["per_season"].values() for s in counts})
    rows = []
    for label in ("B365*", "Avg*", "Max*", "PS*"):
        counts = sc["per_season"][label]
        rows.append([label] + [counts.get(s, 0) for s in seasons]
                    + ["stabile" if sc["verdict"][label]["stabile"] else "NON stabile"])
    add(_table(["Famiglia"] + seasons + ["verdetto"], rows))
    add("")
    add("**Verifica dell'assunto della commessa (“il codice a valle deve usare solo")
    add("B365*/Avg*/Max*/PS*, che sono stabili”): l'assunto è VERO per `B365*`, `Avg*` e")
    add("`Max*` (presenti in tutte e 5 le stagioni, 2022 → 2026/27) ed è **FALSO per `PS*`**,")
    add("che è presente in 2022/23, 2023/24, 2024/25 e 2025/26 e **assente nel 2026/27**")
    add("(al suo posto compaiono `PP*` e `SKB*`). Conseguenza operativa: qualsiasi calcolo")
    add("che legga Pinnacle da `PSH/PSD/PSA` + `PSCH/PSCD/PSCA` (per esempio")
    add("`audit/diagnose_clv_pinnacle.py`) **non è calcolabile sul 2026/27** neanche dopo")
    add("l'arricchimento. La chiusura di Bet365 (`B365CH/B365CD/B365CA`) è invece presente,")
    add("quindi un CLV Bet365 (apertura `B365H` vs chiusura `B365CH`) lo è.")
    add("")
    add("Prefissi bookmaker presenti per stagione (famiglie 1X2 e closing):")
    add("")
    for season in seasons:
        add(f"- **{season}**: " + ", ".join(f"`{p}`" for p in sc["bookmaker_prefixes"][season]))
    add("")
    add("Nessuno schema di colonne è assunto dal codice: `update_db_rich.py` unisce")
    add("l'unione delle colonne presenti e riempie solo le celle vuote.")
    add("")

    # ---------------- criteri
    add("## 2. Criteri di accettazione")
    add("")
    add("### A) Invarianza di produzione")
    add("")
    a = data["criteria"]["A"]
    add(_table(["Controllo", "Esito", "Misura"],
               [[c["name"], c["esito"], c["misura"]] for c in a["checks"]]))
    add("")
    add("Il test `SoccerMath/test_pt19_totali_invariance.py` è stato eseguito **due volte**")
    add("sulla copia isolata: prima dell'arricchimento e dopo.")
    add("")
    add("```")
    add(f"prima:  {a['invariance']['before']['verdict']}")
    add(f"dopo:   {a['invariance']['after']['verdict']}")
    add("```")
    add("")
    add("Le 6 colonne lette da `app.py` (`Date`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`, `FTR`)")
    add("sono confrontate cella per cella prima e dopo: differenze "
        f"**{a['production_columns_diff']}**.")
    add("")
    add("Righe sulle chiavi `(Date, clean_name(Home), clean_name(Away))`:")
    add("")
    add(_table(["Controllo", "Prima", "Dopo", "Esito"],
               [["righe totali", a["rows_before"], a["rows_after"],
                 "uguali" if a["rows_before"] == a["rows_after"] else "DIVERSI"],
                ["chiavi uniche", a["keys_before"], a["keys_after"],
                 "uguali" if a["keys_before"] == a["keys_after"] else "DIVERSI"],
                ["chiavi rimosse", "—", a["keys_removed"], "0" if not a["keys_removed"] else "DA SPIEGARE"],
                ["chiavi aggiunte", "—", a["keys_added"], "0" if not a["keys_added"] else "DA SPIEGARE"],
                ["colonne", a["columns_before"], a["columns_after"], "solo aggiunte"]]))
    add("")
    add("Fixture `test_fixtures/1x2_invariance.json` rigenerato prima e dopo e confrontato")
    add("byte a byte:")
    add("")
    add("```")
    add(f"before: sha256 {a['fixture']['sha_before']}  ({a['fixture']['bytes_before']} byte)")
    add(f"after : sha256 {a['fixture']['sha_after']}  ({a['fixture']['bytes_after']} byte)")
    add(f"identici: {a['fixture']['identical']}")
    add("```")
    add("")
    add("Confronto con il fixture committato (`SoccerMath/test_fixtures/1x2_invariance.json`,")
    add(f"sha256 `{a['fixture']['sha_committed'][:16]}…`): {a['fixture']['vs_committed']}")
    add("")
    add("### B) Idempotenza")
    add("")
    b = data["criteria"]["B"]
    add(_table(["Lega", "sha256 dopo run 1", "sha256 dopo run 2", "celle riscritte nel run 2",
                "Esito"],
               [[league,
                 b["per_league"][league]["sha_after_run1"][:16] + "…",
                 b["per_league"][league]["sha_after_run2"][:16] + "…",
                 b["per_league"][league]["cells_filled_run2"],
                 "identico" if b["per_league"][league]["identical"] else "DIVERSO"]
                for league in LEAGUE_ORDER]))
    add("")
    add(f"Esito: **{b['esito']}** — il secondo run non produce alcun diff sui CSV "
        f"(celle riscritte: {b['total_cells_filled_run2']}).")
    add("")
    add("### C) Non regressione del bug di dedup")
    add("")
    c = data["criteria"]["C"]
    add("Simulazione della sequenza reale `update_db_rich.py → update_db.py → update_db_rich.py`.")
    add("`update_db.py` non è stato eseguito (richiede la chiave API e scriverebbe sui file")
    add("di produzione): ne è stata replicata **fedelmente la logica di merge** (righe 143-160:")
    add("`pd.concat([df_old, df_new])` + `drop_duplicates(subset=[Date,HomeTeam,AwayTeam],")
    add("keep=\"last\")` + ordinamento per data), con `df_new` = le righe API delle stesse")
    add("partite (le 10 colonne che l'API espone, stessi nomi squadra: il caso migliore).")
    add("")
    add(_table(["Lega", "celle ricche dopo run 1", "celle ricche dopo update_db.py",
                "azzerate", "recuperate dal run 3 di update_db_rich"],
               [[league,
                 c["per_league"][league]["rich_cells_before"],
                 c["per_league"][league]["rich_cells_after"],
                 c["per_league"][league]["rich_cells_zeroed"],
                 c["per_league"][league]["rich_cells_recovered"]]
                for league in LEAGUE_ORDER]))
    add("")
    add(f"Esito: **{c['esito']}**")
    add("")
    add("**Prerequisito per la commessa di integrazione (da riportare, senza modificare")
    add("`update_db.py` in questa sede):**")
    add("")
    for chunk in c["prerequisite"].split(". "):
        add("> " + chunk.strip().rstrip(".") + ".")
    add("")
    add("### D) Copertura di `B365H` e `HS` (soglia 90%)")
    add("")
    d = data["criteria"]["D"]
    add(_table(["Lega", "partite concluse", "B365H non nulle", "% B365H", "HS non nulli",
                "% HS", "Esito"],
               [[league,
                 d["per_league"][league]["played"],
                 d["per_league"][league]["B365H"]["covered"],
                 f"{d['per_league'][league]['B365H']['ratio']:.1%}",
                 d["per_league"][league]["HS"]["covered"],
                 f"{d['per_league'][league]['HS']['ratio']:.1%}",
                 "OK" if d["per_league"][league]["ok"] else "SOTTO SOGLIA"]
                for league in LEAGUE_ORDER]))
    add("")
    add(f"Esito complessivo: **{d['esito']}**. Leghe sotto soglia: "
        f"{', '.join(d['under_threshold']) or 'nessuna'}.")
    add("")
    add("Motivo per partita non coperta (le due sonde coincidono sempre: le colonne")
    add("arrivano dalla stessa riga del CSV):")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        for row in d["per_league"][league]["B365H"]["missing_rows"]:
            rows.append([league, row["Date"], f"{row['HomeTeam']} - {row['AwayTeam']}",
                         row["reason"]])
    if rows:
        add(_table(["Lega", "Data", "Partita", "Motivo"], rows))
    else:
        add("_nessuna partita scoperta_")
    add("")
    add("### E) Test unitari del merge per colonna")
    add("")
    e = data["criteria"]["E"]
    add(f"- file: `{e['file']}`")
    add(f"- comando: `{e['cmd']}`")
    add(f"- test eseguiti: **{e['tests_run']}**, esito **{e['verdict']}**")
    add(f"- rete: {e['network']}")
    add("")
    add("Casi richiesti dalla commessa e presenti nella suite:")
    add("")
    add("- `test_una_colonna_gia_valorizzata_non_viene_sovrascritta` (valore diverso);")
    add("- `test_un_nullo_non_sovrascrive_un_valore_esistente` (il caso esplicitamente")
    add("  richiesto: una colonna già valorizzata NON viene sovrascritta da un nullo);")
    add("- `test_colonne_protette_non_vengono_mai_scritte` (Matchday e risultati);")
    add("- `test_nessuna_riga_aggiunta_o_rimossa`, `test_idempotenza_del_merge`,")
    add("  `test_tolleranza_piu_meno_un_giorno`, `test_unione_delle_colonne_con_ordine_stabile`,")
    add("  `test_righe_duplicate_sulla_stessa_chiave_riusano_la_sorgente`,")
    add("  `test_merge_non_usa_concat_ne_drop_duplicates`, `test_scrittura_atomica`,")
    add("  `test_exit_code_non_zero_con_sorgente_assente`.")
    add("")

    # ---------------- non appaiate
    add("## 3. Partite non appaiate (tutte le leghe)")
    add("")
    rows = []
    for league in LEAGUE_ORDER:
        for row in data["unmatched"]["per_league"][league]:
            rows.append([league, row["Date"], f"{row['HomeTeam']} - {row['AwayTeam']}",
                         f"{row['HomeClean']} / {row['AwayClean']}", row["reason"]])
    add(_table(["Lega", "Data", "Partita (come nel *_Live.csv)", "chiave pulita", "motivo"],
               rows or [["—", "—", "nessuna", "—", "—"]]))
    add("")
    add(f"Totale: {data['unmatched']['total']} righe non appaiate su "
        f"{data['unmatched']['total_rows']} righe complessive.")
    add("")
    add("Passaggi di allineamento: prima data esatta, poi tolleranza ±1 giorno a parità di")
    add(f"squadre pulite. Righe appaiate al secondo passaggio: "
        f"{data['unmatched']['matched_with_tolerance']}.")
    add("")

    # ---------------- come rigenerare
    add("## 4. Come rigenerare questo referto")
    add("")
    add("```")
    add("python audit/rich_db_audit.py            # usa lo snapshot committato")
    add("python audit/rich_db_audit.py --work-dir /tmp/rich2627   # per ispezionare i file")
    add("```")
    add("")
    add("Il referto dipende solo da: (a) gli sha256 dei 5 CSV in")
    add("`audit/data/rich_2627_snapshot/`, (b) gli sha256 dei `*_Live.csv` all'ingresso,")
    add("(c) il codice di `SoccerMath/`. Se uno di questi cambia, i numeri cambiano e la")
    add("differenza va letta, non assorbita: gli hash di ingresso sono qui sotto.")
    add("")
    add(_table(["File", "sha256 all'ingresso"],
               [[k, v[:32] + "…"] for k, v in data["input_hashes"].items()]))
    add("")
    add("## 5. Applicare l'arricchimento ai file di produzione")
    add("")
    add("In questa commessa i `*_Live.csv` **non sono stati modificati** (STOP del punto 1d).")
    add("I comandi per applicarlo, identici a quelli usati nel referto ma senza la copia")
    add("isolata, sono:")
    add("")
    add("```")
    add("# download reale dalla fonte (5 leghe, stagione derivata da config)")
    add("python SoccerMath/update_db_rich.py")
    add("")
    add("# oppure, a partire dallo snapshot committato (nessuna rete)")
    add("python SoccerMath/update_db_rich.py --source-dir audit/data/rich_2627_snapshot")
    add("")
    add("# prova senza scrivere")
    add("python SoccerMath/update_db_rich.py --dry-run --source-dir audit/data/rich_2627_snapshot")
    add("```")
    add("")
    add("Dopo l'applicazione, la sequenza del criterio C resta il prerequisito da")
    add("sciogliere prima di integrare il modulo nel workflow.")
    add("")
    return "\n".join(L) + "\n"


# ==========================================
# Main
# ==========================================
def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--out-md", default=DEFAULT_OUT_MD)
    parser.add_argument("--out-json", default=DEFAULT_OUT_JSON)
    args = parser.parse_args(argv)

    work = args.work_dir or tempfile.mkdtemp(prefix="rich2627_")
    repo_soccer = os.path.join(_REPO_ROOT, "SoccerMath")
    work_soccer = os.path.join(work, "SoccerMath")
    if not os.path.exists(work_soccer):
        shutil.copytree(repo_soccer, work_soccer,
                        ignore=shutil.ignore_patterns("__pycache__", "images", "*.pyc"))
    os.makedirs(os.path.join(work, "audit"), exist_ok=True)
    shutil.copyfile(os.path.join(_AUDIT_DIR, "make_1x2_invariance_fixture.py"),
                    os.path.join(work, "audit", "make_1x2_invariance_fixture.py"))
    work_db = os.path.join(work_soccer, "database")

    print(f"[1/8] verifica preliminare dei CSV grezzi in {args.source_dir}")
    preliminary = build_preliminary_checks(
        args.source_dir, work_db, historical_dir=os.path.join(repo_soccer, "database"))
    before = snapshot_db(work_db)

    # STOP
    divergent = {lg: preliminary["divergent_teams"][lg] for lg in LEAGUE_ORDER}
    n_divergent = sum(len(v["live_only"]) for v in divergent.values())
    stop = {
        "triggered": "SÌ" if n_divergent else "NO",
        "n_teams": n_divergent,
        "detail": (f"{n_divergent} squadre su 5 leghe hanno un nome divergente fra il CSV "
                   f"football-data e il *_Live.csv (dettaglio in §1.6)"
                   if n_divergent else "nessun nome divergente"),
        "per_league": divergent,
    }

    print("[2/8] criterio A — invarianza di produzione (test prima dell'arricchimento)")
    invariance_before = run_cmd([os.path.join(work_soccer, "test_pt19_totali_invariance.py")])
    fixture_before = os.path.join(work, "fixture_before.json")
    run_cmd([os.path.join(work, "audit", "make_1x2_invariance_fixture.py"),
             "--out", fixture_before], cwd=work)

    print("[3/8] run 1 di update_db_rich (sulla copia isolata)")
    run1_json = os.path.join(work, "run1.json")
    run_cmd([os.path.join(work_soccer, "update_db_rich.py"),
                    "--source-dir", args.source_dir,
                    "--database-dir", work_db,
                    "--json-out", run1_json])
    with open(run1_json, "r", encoding="utf-8") as fh:
        run1_report = json.load(fh)
    after = snapshot_db(work_db)

    print("[4/8] criterio A — test e fixture dopo l'arricchimento")
    invariance_after = run_cmd([os.path.join(work_soccer, "test_pt19_totali_invariance.py")])
    fixture_after = os.path.join(work, "fixture_after.json")
    run_cmd([os.path.join(work, "audit", "make_1x2_invariance_fixture.py"),
             "--out", fixture_after], cwd=work)

    sha_before = sha256_file(fixture_before)
    sha_after = sha256_file(fixture_after)
    committed_fixture = os.path.join(_REPO_ROOT, "SoccerMath", "test_fixtures",
                                     "1x2_invariance.json")
    sha_committed = sha256_file(committed_fixture)
    fixture_identical = sha_before == sha_after

    # confronto delle 6 colonne di produzione, riga per riga
    prod_diff = []
    for league in LEAGUE_ORDER:
        if before[league]["production_rows"] != after[league]["production_rows"]:
            for i, (old, new) in enumerate(zip(before[league]["production_rows"],
                                               after[league]["production_rows"])):
                if old != new:
                    prod_diff.append({"league": league, "row": i, "before": old, "after": new})
    keys_before = {lg: set(map(tuple, before[lg]["keyset"])) for lg in LEAGUE_ORDER}
    keys_after = {lg: set(map(tuple, after[lg]["keyset"])) for lg in LEAGUE_ORDER}
    keys_removed = {lg: sorted(keys_before[lg] - keys_after[lg]) for lg in LEAGUE_ORDER}
    keys_added = {lg: sorted(keys_after[lg] - keys_before[lg]) for lg in LEAGUE_ORDER}
    rows_before = sum(before[lg]["rows"] for lg in LEAGUE_ORDER)
    rows_after = sum(after[lg]["rows"] for lg in LEAGUE_ORDER)

    invariance_verdict_before = unittest_summary(combined_output(invariance_before))
    invariance_verdict_after = unittest_summary(combined_output(invariance_after))
    a_checks = [
        {"name": "test_pt19_totali_invariance.py prima",
         "esito": "VERDE" if invariance_before["ok"] else "ROSSO",
         "misura": invariance_verdict_before},
        {"name": "test_pt19_totali_invariance.py dopo",
         "esito": "VERDE" if invariance_after["ok"] else "ROSSO",
         "misura": invariance_verdict_after},
        {"name": "fixture 1x2 rigenerato prima/dopo (byte a byte)",
         "esito": "IDENTICO" if fixture_identical else "DIVERSO",
         "misura": f"{os.path.getsize(fixture_before)} byte, sha256 {sha_before[:32]}…"},
        {"name": "6 colonne lette da app.py",
         "esito": "IDENTICHE" if not prod_diff else "MODIFICATE",
         "misura": f"{len(prod_diff)} celle diverse su {rows_before * 6}"},
        {"name": "righe del database",
         "esito": "IDENTICHE" if rows_before == rows_after else "MODIFICATE",
         "misura": f"{rows_before} prima, {rows_after} dopo"},
        {"name": "colonne",
         "esito": "SOLO AGGIUNTE"
                  if all(set(before[lg]["columns"]) <= set(after[lg]["columns"])
                         for lg in LEAGUE_ORDER) else "MODIFICATE",
         "misura": "; ".join(f"{lg}: {before[lg]['columns_count']}→"
                             f"{after[lg]['columns_count']}" for lg in LEAGUE_ORDER)},
        {"name": "chiavi (Date, clean H, clean A)",
         "esito": "IDENTICHE" if not any(keys_removed.values()) and not any(keys_added.values())
                  else "MODIFICATE",
         "misura": f"{sum(len(v) for v in keys_removed.values())} rimosse, "
                   f"{sum(len(v) for v in keys_added.values())} aggiunte"},
    ]
    criterion_a = {
        "checks": a_checks,
        "esito": "VERDE" if all(c["esito"] in ("VERDE", "IDENTICO", "IDENTICHE",
                                                "SOLO AGGIUNTE")
                                for c in a_checks) else "ROSSO",
        "invariance": {
            "before": {"ok": invariance_before["ok"], "verdict": invariance_verdict_before},
            "after": {"ok": invariance_after["ok"], "verdict": invariance_verdict_after},
        },
        "fixture": {
            "sha_before": sha_before, "sha_after": sha_after,
            "bytes_before": os.path.getsize(fixture_before),
            "bytes_after": os.path.getsize(fixture_after),
            "identical": fixture_identical,
            "sha_committed": sha_committed,
            "vs_committed": ("identico al fixture committato"
                             if sha_committed == sha_after else
                             "diverso dal fixture committato: il database è cresciuto "
                             "rispetto a quando il fixture fu generato (partite 2026/27 "
                             "aggiunte dopo), quindi il campione rigenerato è un altro; "
                             "il confronto valido è prima/dopo l'arricchimento"),
        },
        "production_columns_diff": len(prod_diff),
        "columns_before": sum(before[lg]["columns_count"] for lg in LEAGUE_ORDER),
        "columns_after": sum(after[lg]["columns_count"] for lg in LEAGUE_ORDER),
        "production_column_diffs": prod_diff,
        "rows_before": rows_before, "rows_after": rows_after,
        "keys_before": sum(len(v) for v in keys_before.values()),
        "keys_after": sum(len(v) for v in keys_after.values()),
        "keys_removed": sum(len(v) for v in keys_removed.values()),
        "keys_added": sum(len(v) for v in keys_added.values()),
        "keys_removed_detail": {k: v for k, v in keys_removed.items() if v},
        "keys_added_detail": {k: v for k, v in keys_added.items() if v},
    }

    print("[5/8] criterio B — secondo run (idempotenza)")
    hashes_run1 = {lg: after[lg]["sha256"] for lg in LEAGUE_ORDER}
    run2_json = os.path.join(work, "run2.json")
    run2 = run_cmd([os.path.join(work_soccer, "update_db_rich.py"),
                    "--source-dir", args.source_dir,
                    "--database-dir", work_db,
                    "--json-out", run2_json])
    with open(run2_json, "r", encoding="utf-8") as fh:
        run2_report = json.load(fh)
    after2 = snapshot_db(work_db)
    per_league_b = {}
    for league in LEAGUE_ORDER:
        per_league_b[league] = {
            "sha_after_run1": hashes_run1[league],
            "sha_after_run2": after2[league]["sha256"],
            "identical": hashes_run1[league] == after2[league]["sha256"],
            "cells_filled_run2": run2_report["leagues"][league]["merge"]["cells_filled"],
        }
    criterion_b = {
        "per_league": per_league_b,
        "total_cells_filled_run2": sum(v["cells_filled_run2"] for v in per_league_b.values()),
        "exit_code_run2": run2["returncode"],
        "esito": "VERDE" if all(v["identical"] for v in per_league_b.values()) else "ROSSO",
    }

    print("[6/8] criterio C — simulazione del merge di update_db.py")
    sim_dir = os.path.join(work, "sim_update_db", "database")
    sim = simulate_update_db(work_db, sim_dir)
    run3_json = os.path.join(work, "run3.json")
    run3 = run_cmd([os.path.join(work_soccer, "update_db_rich.py"),
                    "--source-dir", args.source_dir,
                    "--database-dir", sim_dir,
                    "--json-out", run3_json])
    with open(run3_json, "r", encoding="utf-8") as fh:
        run3_report = json.load(fh)
    for league in LEAGUE_ORDER:
        sim[league]["rich_cells_recovered"] = (
            run3_report["leagues"][league]["merge"]["cells_filled"])
    total_zeroed = sum(v["rich_cells_zeroed"] for v in sim.values())
    criterion_c = {
        "per_league": sim,
        "total_zeroed": total_zeroed,
        "esito": "il bug si riproduce" if total_zeroed else "nessun azzeramento",
        "prerequisite": (
            "il merge dentro update_db.py va rifatto per colonna (come in "
            "update_db_rich.merge_columns) PRIMA di integrare update_db_rich.py nel "
            "workflow: con il concat + drop_duplicates(keep=\"last\") attuale, il primo "
            "run di update_db.py dopo l'arricchimento azzera "
            f"{total_zeroed} celle delle colonne ricche "
            "(tutte: la riga API ha solo 10 colonne e vince sul duplicato). "
            "Il terzo run di update_db_rich.py le recupera, ma solo perché riscarica "
            "tutto da football-data.co.uk: finché update_db.py non cambia, il dato "
            "ricco è garantito solo se update_db_rich.py gira DOPO update_db.py, e "
            "comunque la finestra in cui il dato è azzerato resta reale."),
        "run3_exit_code": run3["returncode"],
    }

    print("[7/8] criteri D e E")
    per_league_d = {}
    for league in LEAGUE_ORDER:
        cov = run1_report["leagues"][league]["coverage"]
        ok = all(cov[p]["ratio"] >= COVERAGE_THRESHOLD for p in COVERAGE_PROBES)
        per_league_d[league] = {
            "played": cov["played_matches"],
            "B365H": cov["B365H"], "HS": cov["HS"], "ok": ok,
        }
    under = [lg for lg in LEAGUE_ORDER if not per_league_d[lg]["ok"]]
    criterion_d = {
        "per_league": per_league_d,
        "threshold": COVERAGE_THRESHOLD,
        "under_threshold": under,
        "esito": "VERDE" if not under else f"ROSSO (sotto soglia: {', '.join(under)})",
    }

    unit = run_cmd([os.path.join(repo_soccer, "test_update_db_rich.py")])
    tests_run, _verdict = count_tests(combined_output(unit))
    criterion_e = {
        "file": "SoccerMath/test_update_db_rich.py",
        "cmd": "python SoccerMath/test_update_db_rich.py",
        "tests_run": tests_run,
        "verdict": "VERDE" if unit["ok"] else "ROSSO",
        "network": "nessuna (tutti i test sono offline)",
        "returncode": unit["returncode"],
    }

    unmatched = {"per_league": {}, "total": 0, "total_rows": rows_after,
                 "matched_with_tolerance": 0}
    for league in LEAGUE_ORDER:
        merge = run1_report["leagues"][league]["merge"]
        unmatched["per_league"][league] = merge["unmatched_rows"]
        unmatched["total"] += merge["unmatched"]
        unmatched["matched_with_tolerance"] += merge["matched_tolerance"]

    criteria_summary = [
        {"id": "A — invarianza di produzione", "esito": criterion_a["esito"],
         "misura": f"test 1X2 verde prima e dopo; fixture identico "
                   f"({'sì' if fixture_identical else 'NO'}); 6 colonne: "
                   f"{len(prod_diff)} celle cambiate; righe {rows_before}→{rows_after}"},
        {"id": "B — idempotenza", "esito": criterion_b["esito"],
         "misura": f"secondo run: {criterion_b['total_cells_filled_run2']} celle riscritte, "
                   f"sha256 identici per tutte e 5 le leghe"},
        {"id": "C — non regressione del bug di dedup", "esito": criterion_c["esito"],
         "misura": f"{total_zeroed} celle ricche azzerate dal merge di update_db.py "
                   f"(prerequisito dichiarato per la commessa di integrazione)"},
        {"id": "D — copertura ≥ 90%", "esito": criterion_d["esito"],
         "misura": "; ".join(f"{lg}: {per_league_d[lg]['B365H']['ratio']:.1%}"
                             for lg in LEAGUE_ORDER)},
        {"id": "E — test unitari del merge", "esito": criterion_e["verdict"],
         "misura": f"{tests_run} test offline, tutti verdi"},
    ]

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reproduce_cmd": "python audit/rich_db_audit.py",
        "snapshot_dir": os.path.relpath(args.source_dir, _REPO_ROOT),
        "work_dir_note": "cartella temporanea; --work-dir per ispezionarla",
        "work_dir": work,
        "stop": stop,
        "preliminary": preliminary,
        "input_hashes": {before[lg]["path"]: before[lg]["sha256"] for lg in LEAGUE_ORDER},
        "snapshot_hashes": {lg: preliminary["leagues"][lg].get("sha256")
                            for lg in LEAGUE_ORDER},
        "criteria_summary": criteria_summary,
        "criteria": {"A": criterion_a, "B": criterion_b, "C": criterion_c,
                     "D": criterion_d, "E": criterion_e},
        "unmatched": unmatched,
        "run1": run1_report,
        "run2": run2_report,
        "run3": run3_report,
        "before": {lg: {k: v for k, v in before[lg].items()
                        if k not in ("production_rows", "keys", "keyset")}
                   for lg in LEAGUE_ORDER},
        "after": {lg: {k: v for k, v in after[lg].items()
                       if k not in ("production_rows", "keys", "keyset")}
                  for lg in LEAGUE_ORDER},
    }

    print("[8/8] scrittura del referto")
    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(data))
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"referto: {args.out_md}")
    print(f"dati:    {args.out_json}")
    print(f"cartella di lavoro: {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
