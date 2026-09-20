"""registry_coverage_check.py - Sola lettura: chi copre cosa nel Registro.

Risponde alla domanda della commessa: "per ogni partita del periodo, il
Registro ha sia la scelta del modello attuale sia quella del legacy? stesso
campione, stessa lunghezza per entrambi?".

Legge il Registro (JSONBin se configurato, altrimenti il file locale), calcola
la copertura con ``registry_coverage.coverage_by_variant`` e stampa:

* partite e righe per ciascun modello nel periodo;
* quante partite hanno ENTRAMBI i modelli;
* le partite coperte da un solo modello, con mercato/probabilita'/esito.

NON scrive mai: nessun PUT, nessun file di registro toccato. Esce con codice
1 se i due campioni non coincidono (utile come gate in CI, dove la
discrepanza va spiegata e non nascosta).

Uso:
    python SoccerMath/registry_coverage_check.py --from 2026-08-30 --to 2026-09-20
    python SoccerMath/registry_coverage_check.py --json out/coverage.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from registry_coverage import coverage_by_variant, render_coverage, top_mix_rows  # noqa: E402


def load_registry_file(path: str) -> Tuple[List[Dict[str, Any]], str]:
    """Registro da FILE (es. la copia fusa scritta da ``--dump-merged``).

    Serve a misurare la copertura sui dati RICOSTRUITI quando il Registro live
    non e' raggiungibile: il numero che ne esce e' un numero su file, e la
    fonte lo dichiara, quindi non puo' essere scambiato per quello del Registro.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    righe = data.get("data") if isinstance(data, dict) else data
    if not isinstance(righe, list):
        raise SystemExit(f"{path}: attesa una lista o {{\"data\": [...]}}, trovato {type(righe).__name__}")
    return righe, f"file {os.path.basename(path)}"


def load_registry_readonly() -> Tuple[List[Dict[str, Any]], str]:
    """Registro per la SOLA lettura. Ritorna ``(righe, fonte)``.

    A differenza di ``replay_legacy_topmix.strict_load_registry`` (che precede
    un PUT e quindi deve rifiutare i fallback) qui la lettura e' innocua: se il
    remoto non risponde si usa il file locale e lo si DICHIARA nella fonte,
    cosi' il numero non viene scambiato per quello del Registro live.
    """
    import requests
    from config import JSONBIN_API_KEY, JSONBIN_BIN_ID, PREDICTIONS_FILE
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            r = requests.get(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
                             headers={"X-Master-Key": JSONBIN_API_KEY}, timeout=20)
            if r.status_code == 200:
                rec = r.json().get("record", {})
                if isinstance(rec, dict) and isinstance(rec.get("data"), list):
                    return rec["data"], "jsonbin"
                if isinstance(rec, list):
                    return rec, "jsonbin"
            fonte = f"jsonbin HTTP {r.status_code}"
        except Exception as e:                       # pragma: no cover - rete
            fonte = f"jsonbin errore {e}"
    else:
        fonte = None
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        righe = data.get("data") if isinstance(data, dict) else data
        if isinstance(righe, list):
            return righe, fonte or "file locale"
    return [], fonte or "nessun registro"


def _parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="day_from", type=_parse_day, default=None,
                    help="primo giorno (UTC) del periodo, YYYY-MM-DD (default: tutti)")
    ap.add_argument("--to", dest="day_to", type=_parse_day, default=None,
                    help="ultimo giorno (UTC) del periodo, YYYY-MM-DD (default: tutti)")
    ap.add_argument("--registry", dest="registry_file", default=None, metavar="FILE",
                    help="misura su un FILE (copia fusa) invece che sul Registro live; la fonte lo dichiara")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="esce 0 anche se i due campioni non coincidono (default: esce 1)")
    args = ap.parse_args(argv)

    righe, fonte = (load_registry_file(args.registry_file) if args.registry_file
                    else load_registry_readonly())
    cov = coverage_by_variant(righe, args.day_from, args.day_to)
    cov["fonte"] = fonte
    cov["generato_il"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    testo = render_coverage(cov)
    kb = len(json.dumps({"data": righe}, ensure_ascii=False).encode("utf-8")) / 1024
    print(f"Registro ({fonte}): {len(righe)} righe totali · {kb:.1f} kB (limite piano free JSONBin: 100 kB) · "
          f"righe Top Mix nel periodo: "
          f"{sum(1 for _ in top_mix_rows(righe, args.day_from, args.day_to))}")
    print(testo)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(cov, f, ensure_ascii=False, indent=2)
        print(f"[coverage] json: {args.json_out}")
    if not cov["pareggio"] and not args.allow_mismatch:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
