"""Completa il GRADING delle righe in attesa per partite GIA' giocate (sola lettura
finche' non si passa ``--scrivi`` insieme a ``--conferma``).

Perche' esiste. Nel Registro ci sono righe con esito ancora in attesa la cui partita
e' stata giocata da giorni o mesi (misurato il 21/09/2026: **10 righe**, tutte
l'ultima giornata della stagione 2025/2026). Il giro di grading di produzione
(``app.aggiorna_risultati_reali``) interroga la stagione IN CORSO: quelle partite
non le chiedera' mai piu', quindi le righe restano fuori dal denominatore delle
percentuali di successo (la tabella dice 129 righe, il conto ne usa 119). Non e'
un pareggio: e' campione che manca.

Cosa fa, in ordine:

1. seleziona le righe SENZA esito la cui partita e' passata da almeno
   ``--ore-minime`` (default 48);
2. per ognuna prende il risultato finale dalla FONTE AUTOREVOLE (football-data.org,
   per ``match_id``) e lo **verifica**: stato ``FINISHED``, gol presenti, squadre
   della partita identiche a quelle della riga, data della partita coerente;
3. **controprova locale**: quando la partita si ritrova anche nell'archivio della
   stagione in ``SoccerMath/database`` (``<lega>_<anno>.csv``), i due risultati
   devono COINCIDERE. Se non coincidono, quella riga NON si scrive: si dichiara;
4. calcola l'esito con lo STESSO grading della produzione
   (``prediction_registry.esito_mercato``) e scrive **due soli campi**:
   ``risultato_reale`` ed ``esito``.

Garanzie (le stesse delle altre scritture sul Registro vivo):

* nessuna riga che ha GIA' un esito viene toccata: non si riscrive mai un esito;
* nessun altro campo viene modificato: la scrittura usa ``registry_store.save_rows``,
  che manda una ``HSET`` solo per i campi cambiati, e la verifica dopo la scrittura
  confronta riga per riga (ogni riga non selezionata deve essere IDENTICA);
* nessuna scrittura senza ``--scrivi`` **e** ``--conferma``; il numero di righe da
  gradare deve combaciare con ``--attesi`` quando dato;
* istantanea PRIMA di scrivere (``sm:registro:snapshot:<giorno>-pre-grading``,
  con suffisso se la chiave e' gia' occupata: un punto di ripristino non si
  sovrascrive);
* backend Upstash soltanto;
* niente risultato inventato: se la partita non risponde, non e' finita, non ha
  gol, le squadre non combaciano o le due fonti litigano, la riga si SALTA e si
  dichiara il motivo.

Uso:

    python SoccerMath/registry_grading.py                      # prova (nessuna scrittura)
    python SoccerMath/registry_grading.py --compatto --json /tmp/grading.json
    python SoccerMath/registry_grading.py --scrivi --conferma --attesi 10
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_store as rs  # noqa: E402
from prediction_registry import (  # noqa: E402
    DATA_FIELD,
    ESITO_FIELD,
    ESITO_PERSO,
    ESITO_VINTO,
    KICKOFF_UTC_FIELD,
    esito_mercato,
    model_variant_read,
    origin_of,
    outcome_of_entry,
    parse_datetime,
    parse_kickoff,
)
from season_calendar import season_label, season_start_year_of  # noqa: E402

UTC = timezone.utc
RISULTATO_FIELD = "risultato_reale"
CAMPI_GRADING = (RISULTATO_FIELD, ESITO_FIELD)
ORE_MINIME_DEFAULT = 48
API_MATCH = "https://api.football-data.org/v4/matches/{id}"

# Nomi che l'archivio delle stagioni (football-data, ``<lega>_<anno>.csv``) usa in
# forma DIVERSA da quella mostrata nella riga del Registro (shortName dell'API).
# Non e' fuzzy matching: sono due nomi e la voce e' dichiarata qui, a mano, una
# per una. Sono squadre della stagione 2025/2026 che oggi non ci sono piu' (quelle
# attuali passano da ``clean_name``): per questo le tabelle di alias correnti non
# le coprono.
ALIAS_ARCHIVIO = {
    "Real Oviedo": "Oviedo",
    "Wolverhampton": "Wolves",
}


def _giorno_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def kickoff_riga(riga: Dict[str, Any]) -> Optional[datetime]:
    """Istante della partita: ``kickoff_utc`` (autorevole) o ``data`` italiana."""
    ko = parse_kickoff(riga.get(KICKOFF_UTC_FIELD))
    if ko is not None:
        return ko
    return parse_datetime(riga.get(DATA_FIELD))


def stagione_riga(riga: Dict[str, Any]) -> str:
    campo = str(riga.get("stagione") or "").strip()
    if campo:
        return campo
    ko = kickoff_riga(riga)
    return season_label(season_start_year_of(ko.date())) if ko else "Sconosciuta"


def seleziona_in_attesa(righe: Sequence[Dict[str, Any]], *, adesso: Optional[datetime] = None,
                        ore_minime: int = ORE_MINIME_DEFAULT,
                        stagione: Optional[str] = None) -> List[Dict[str, Any]]:
    """Righe SENZA esito la cui partita e' finita da almeno ``ore_minime``.

    Il margine serve a non chiamare "buco" una partita di ieri sera: il risultato
    arriva dopo il fischio, e il giro di produzione lo prende alla giornata
    successiva. Una riga senza data leggibile non si seleziona (non si sa se la
    partita si e' giocata).
    """
    adesso = adesso or datetime.now(UTC)
    soglia = adesso - timedelta(hours=max(0, ore_minime))
    fuori: List[Dict[str, Any]] = []
    for r in righe or []:
        if outcome_of_entry(r) is not None:
            continue
        ko = kickoff_riga(r)
        if ko is None or ko > soglia:
            continue
        if stagione is not None and stagione_riga(r) != stagione:
            continue
        fuori.append(r)
    return sorted(fuori, key=lambda r: (kickoff_riga(r) or datetime.min.replace(tzinfo=UTC),
                                        str(r.get("home") or "")))


# ---------------------------------------------------------------------------
# Fonte autorevole: football-data.org per match_id
# ---------------------------------------------------------------------------
def partita_da_api(match_id: Any, *, api_key: str, getter: Optional[Callable[..., Any]] = None,
                   timeout: int = 20, tentativi: int = 3,
                   pausa: float = 6.5) -> Tuple[Optional[Dict[str, Any]], str]:
    """La partita dal suo ``match_id`` (1 GET). Ritorna ``(payload, motivo)``.

    Il piano free di football-data.org risponde 429 quando le chiamate si
    susseguono: il ritentativo e' quello del replay (stessa garanzia, un posto
    solo per la regola), importato pigramente per non tirare dentro ``app``.
    """
    if not api_key:
        return None, "nessuna FOOTBALL_DATA_API_KEY: fonte API non interrogabile"
    if getter is None:
        import requests
        getter = requests.get
    url = API_MATCH.format(id=match_id)
    try:
        from replay_legacy_topmix import _get_con_ritentativi
        risposta = _get_con_ritentativi(getter, url, headers={"X-Auth-Token": api_key},
                                        timeout=timeout, tentativi=tentativi, pausa=pausa)
    except Exception as e:                                            # pragma: no cover - rete
        return None, f"richiesta fallita: {e}"
    codice = getattr(risposta, "status_code", None)
    if codice != 200:
        return None, f"HTTP {codice}"
    try:
        payload = risposta.json()
    except Exception as e:
        return None, f"risposta non JSON: {e}"
    if not isinstance(payload, dict) or payload.get("id") is None:
        return None, "risposta senza partita"
    return payload, ""


def _coppia_gol(payload: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    score = payload.get("score") or {}
    tempi = score.get("fullTime") or {}
    gh, ga = tempi.get("home"), tempi.get("away")
    if gh is None or ga is None:
        return None
    try:
        return int(gh), int(ga)
    except (TypeError, ValueError):
        return None


def _normalizza_nome(nome: Any) -> str:
    """Nome squadra ridotto alla forma con cui si confronta (canonica se si puo')."""
    testo = str(nome or "").strip()
    if not testo:
        return ""
    try:
        from team_aliases import clean_name
        return clean_name(ALIAS_ARCHIVIO.get(testo, testo)) or testo.lower()
    except Exception:                                                 # pragma: no cover - difensivo
        return testo.lower()


def valida_partita(payload: Dict[str, Any], riga: Dict[str, Any]) -> Tuple[bool, str]:
    """La partita risponde a QUESTA riga? (squadre, stato, gol, giorno).

    Il ``match_id`` identifica la partita, ma un risultato scritto sulla partita
    sbagliata e' peggio di un risultato mancante: si controlla tutto quello che si
    puo' controllare senza fidarsi del solo numero.
    """
    if str(payload.get("id")) != str(riga.get("match_id")):
        return False, "id diverso"
    if str(payload.get("status") or "").upper() != "FINISHED":
        return False, f"partita non finita (status {payload.get('status')})"
    gol = _coppia_gol(payload)
    if gol is None:
        return False, "risultato finale assente"
    casa = ((payload.get("homeTeam") or {}).get("shortName")
            or (payload.get("homeTeam") or {}).get("name"))
    ospiti = ((payload.get("awayTeam") or {}).get("shortName")
              or (payload.get("awayTeam") or {}).get("name"))
    if _normalizza_nome(casa) != _normalizza_nome(riga.get("home")):
        return False, f"squadra di casa diversa ({casa} ≠ {riga.get('home')})"
    if _normalizza_nome(ospiti) != _normalizza_nome(riga.get("away")):
        return False, f"squadra ospite diversa ({ospiti} ≠ {riga.get('away')})"
    ko = parse_kickoff(payload.get("utcDate"))
    giorno_riga = kickoff_riga(riga)
    if ko is None or giorno_riga is None:
        return False, "data della partita non leggibile"
    if abs((ko.date() - giorno_riga.date()).days) > 1:
        return False, f"giorno diverso ({ko.date()} ≠ {giorno_riga.date()})"
    return True, ""


# ---------------------------------------------------------------------------
# Controprova locale: archivio delle stagioni nei CSV
# ---------------------------------------------------------------------------
def percorso_archivio(riga: Dict[str, Any], *, db_dir: Optional[str] = None) -> Optional[str]:
    """Il CSV della stagione della riga (``<db_prefix>_<anno>.csv``), se esiste."""
    from config import DATABASE_DIR, LEAGUES_CONFIG
    camp = str(riga.get("campionato") or "").strip()
    info = LEAGUES_CONFIG.get(camp)
    if not info:
        for nome, voce in LEAGUES_CONFIG.items():
            if camp.lower() in (nome.lower(), str(voce.get("short_name") or "").lower()):
                info = voce
                break
    if not info:
        return None
    ko = kickoff_riga(riga)
    if ko is None:
        return None
    anno = season_start_year_of(ko.date())
    percorso = os.path.join(db_dir or DATABASE_DIR, f"{info['db_prefix']}_{anno}.csv")
    return percorso if os.path.exists(percorso) else None


def risultato_da_archivio(riga: Dict[str, Any], *, db_dir: Optional[str] = None,
                          righe_csv: Optional[Sequence[Dict[str, Any]]] = None
                          ) -> Tuple[Optional[Tuple[int, int]], str]:
    """Risultato della partita dall'archivio della stagione (``(gol, motivo)``).

    La partita deve ritrovarsi **una sola volta** per giorno e per squadre: zero
    o piu' di una candidata = non si scrive nulla (niente scelta a caso).
    """
    percorso = percorso_archivio(riga, db_dir=db_dir)
    if percorso is None and righe_csv is None:
        return None, "archivio della stagione non disponibile"
    if righe_csv is None:
        with open(percorso, newline="", encoding="utf-8", errors="replace") as f:
            righe_csv = list(csv.DictReader(f))
    ko = kickoff_riga(riga)
    casa, ospiti = _normalizza_nome(riga.get("home")), _normalizza_nome(riga.get("away"))
    trovate: List[Tuple[int, int]] = []
    for r in righe_csv:
        data = str(r.get("Date") or "").strip()
        if ko is not None and data:
            try:
                giorno = datetime.strptime(data, "%d/%m/%Y").date()
            except ValueError:
                continue
            if giorno != ko.date():
                continue
        if (_normalizza_nome(r.get("HomeTeam")) != casa
                or _normalizza_nome(r.get("AwayTeam")) != ospiti):
            continue
        try:
            trovate.append((int(r.get("FTHG")), int(r.get("FTAG"))))
        except (TypeError, ValueError):
            return None, "riga d'archivio senza gol"
    if not trovate:
        return None, "partita non trovata nell'archivio della stagione"
    if len(trovate) > 1:
        return None, f"partita ambigua nell'archivio ({len(trovate)} righe)"
    return trovate[0], ""


# ---------------------------------------------------------------------------
# Grading e aggiornamento della riga
# ---------------------------------------------------------------------------
def campi_grading(riga: Dict[str, Any], gh: int, ga: int) -> Tuple[Optional[Dict[str, Any]], str]:
    """I due campi da aggiornare (o il motivo per cui non si tocca la riga).

    Il risultato e' ``risultato_reale`` = ``"golcasa-golospiti"`` e ``esito``
    calcolato da ``esito_mercato`` (stesso grading della produzione). Se il
    mercato non e' graduabile quel campo resta dov'e': non si inventa un esito.
    """
    risultato = f"{gh}-{ga}"
    esito = esito_mercato(riga.get("mercato_standard", ""), gh, ga)
    if esito is None:
        return None, f"mercato `{riga.get('mercato_standard')}` non graduabile"
    gia = riga.get(RISULTATO_FIELD)
    if gia not in (None, "") and str(gia).strip() != risultato:
        return None, f"la riga dichiara gia' il risultato {gia} (≠ {risultato}): non si riscrive"
    return {RISULTATO_FIELD: risultato, ESITO_FIELD: esito}, ""


def applica(riga: Dict[str, Any], campi: Dict[str, Any]) -> Dict[str, Any]:
    """Copia della riga con SOLO i campi indicati aggiornati (il resto identico)."""
    nuova = dict(riga)
    prima = {k: v for k, v in nuova.items() if k not in campi}
    nuova.update(campi)
    diverse = {k for k in set(prima) | set(nuova) if prima.get(k, object()) != nuova.get(k, object())}
    if diverse - set(campi):                        # pragma: no cover - rete di sicurezza
        raise RuntimeError(f"campi cambiati fuori da quelli previsti: {sorted(diverse - set(campi))}")
    return nuova


def chiave_istantanea_libera(giorno: str, scrivi: bool, *, suffisso: str = "pre-grading") -> str:
    """``<giorno>-pre-grading``, con un suffisso se quella chiave esiste gia'.

    Un'istantanea che sovrascrive un'altra istantanea non e' un punto di
    ripristino: e' un punto di ripristino in meno. La lettura avviene solo quando
    si sta per scrivere (in prova nessun GET).
    """
    base = f"{giorno}-{suffisso}"
    if not scrivi:
        return base
    candidata, n = base, 1
    while rs.upstash_raw(["GET", rs.snapshot_key(candidata)]).get("result") is not None:
        n += 1
        candidata = f"{base}-{n}"
        if n > 50:                                                        # pragma: no cover
            raise SystemExit("::error title=grading::troppe istantanee con lo stesso nome")
    return candidata


# ---------------------------------------------------------------------------
# Piano e referto
# ---------------------------------------------------------------------------
def piano(righe: Sequence[Dict[str, Any]], *, api_key: str = "",
          getter: Optional[Callable[..., Any]] = None, db_dir: Optional[str] = None,
          fonte: str = "auto", risultati: Optional[Dict[str, str]] = None,
          adesso: Optional[datetime] = None, ore_minime: int = ORE_MINIME_DEFAULT,
          stagione: Optional[str] = None) -> Dict[str, Any]:
    """Per ogni riga in attesa: risultato, fonte, campi da scrivere (o il motivo).

    ``risultati`` (``{match_id: "g-h"}``) e' la scorciatoia per una prova senza
    rete: quello che c'e' li' dentro e' dichiarato come fonte ``file``.
    """
    selezionate = seleziona_in_attesa(righe, adesso=adesso, ore_minime=ore_minime, stagione=stagione)
    voci: List[Dict[str, Any]] = []
    for r in selezionate:
        voce: Dict[str, Any] = {
            "match_id": r.get("match_id"), "data": r.get("data"), "home": r.get("home"),
            "away": r.get("away"), "campionato": r.get("campionato"),
            "mercato": r.get("mercato_standard"), "salvato_il": r.get("salvato_il"),
            "variante": model_variant_read(r), "origine": origin_of(r),
            "stagione": stagione_riga(r), "giornata": r.get("giornata"),
            "esito_attuale": r.get(ESITO_FIELD), "risultato_attuale": r.get(RISULTATO_FIELD),
        }
        gol: Optional[Tuple[int, int]] = None
        fonti: List[str] = []
        motivi: List[str] = []
        if risultati and str(r.get("match_id")) in {str(k) for k in risultati}:
            valore = next(v for k, v in risultati.items() if str(k) == str(r.get("match_id")))
            try:
                gh, ga = (int(x) for x in str(valore).replace("-", " ").split())
                gol, fonti = (gh, ga), ["file"]
            except (TypeError, ValueError):
                motivi.append(f"risultato nel file non leggibile ({valore!r})")
        if fonte in ("auto", "api") and gol is None:
            payload, motivo = partita_da_api(r.get("match_id"), api_key=api_key, getter=getter)
            if payload is None:
                motivi.append(f"API: {motivo}")
                voce["api"] = motivo
            else:
                ok, perche = valida_partita(payload, r)
                if not ok:
                    motivi.append(f"API: {perche}")
                    voce["api"] = perche
                else:
                    gol, fonti = _coppia_gol(payload), ["api"]            # type: ignore[assignment]
                    voce["api"] = "partita verificata (FINISHED, squadre e giorno coerenti)"
        if fonte in ("auto", "archivio") and gol is not None:
            # Controprova locale: se la partita c'e' anche nell'archivio, i due
            # risultati devono coincidere.
            arch, perche = risultato_da_archivio(r, db_dir=db_dir)
            if arch is None:
                voce["archivio"] = perche
            elif arch != gol:
                motivi.append(f"archivio in disaccordo ({arch[0]}-{arch[1]} ≠ {gol[0]}-{gol[1]})")
                gol, fonti = None, []
            else:
                fonti.append("archivio")
                voce["archivio"] = "coincide"
        elif fonte in ("auto", "archivio") and gol is None:
            arch, perche = risultato_da_archivio(r, db_dir=db_dir)
            if arch is not None:
                gol, fonti = arch, ["archivio"]
            else:
                voce["archivio"] = perche
        if gol is None:
            voce["saltata"] = "; ".join(motivi) or "nessuna fonte disponibile"
            voce["campi"] = None
        else:
            campi, perche = campi_grading(r, gol[0], gol[1])
            voce["risultato"] = f"{gol[0]}-{gol[1]}"
            voce["fonti"] = fonti
            if campi is None:
                voce["saltata"] = perche
                voce["campi"] = None
            else:
                voce["campi"] = campi
                voce["esito"] = campi[ESITO_FIELD]
        voci.append(voce)
    return {
        "selezionate": len(selezionate),
        "da_gradare": [v for v in voci if v.get("campi")],
        "saltate": [v for v in voci if not v.get("campi")],
        "voci": voci,
    }


def _pct_no(x: Any) -> str:
    return "-" if x in (None, "") else str(x)


def righe_compatti(p: Dict[str, Any], esito_scrittura: Optional[Dict[str, Any]] = None,
                   verifica: Optional[Dict[str, Any]] = None) -> List[str]:
    """Righe brevi prefissate, per i referti con tetto di caratteri (CI)."""
    out: List[str] = []
    out.append(f"SELEZIONE| righe in attesa per partite gia' giocate: {p['selezionate']} · "
               f"da gradare {len(p['da_gradare'])} · saltate {len(p['saltate'])}")
    for v in p["voci"]:
        if v.get("campi"):
            api_txt = f" | API: {v['api']}" if v.get("api") else ""
            out.append(f"GRADING| {v['data']} | {v['home']} - {v['away']} | {v['campionato']} | "
                       f"{v['mercato']} | risultato {v['risultato']} | esito {v['esito']} | "
                       f"fonte {'+'.join(v.get('fonti') or [])}{api_txt} | scritta {v['salvato_il']} | "
                       f"{v['variante']} | {v['stagione']} | id {v['match_id']}")
        else:
            out.append(f"SALTATA| {v['data']} | {v['home']} - {v['away']} | {v['campionato']} | "
                       f"{v['mercato']} | motivo: {v['saltata']} | {v['stagione']} | id {v['match_id']}")
    if esito_scrittura is not None:
        out.append("SCRITTURA| " + json.dumps(esito_scrittura, ensure_ascii=False, default=str))
    if verifica is not None:
        out.append("VERIFICA| " + " · ".join(f"{k}: {v}" for k, v in verifica.items()))
    return out


def righe_testo(p: Dict[str, Any], esito_scrittura: Optional[Dict[str, Any]] = None,
                verifica: Optional[Dict[str, Any]] = None) -> List[str]:
    L: List[str] = ["## Grading delle righe in attesa per partite gia' giocate (sola lettura)", ""]
    L.append(f"- righe selezionate: **{p['selezionate']}** · da gradare: **{len(p['da_gradare'])}** · "
             f"saltate: **{len(p['saltate'])}**")
    L.append("")
    L.append("| data | partita | campionato | mercato | risultato | esito | fonte | scritta il |")
    L.append("|---|---|---|---|---|---|---|---|")
    for v in p["voci"]:
        L.append(f"| {v['data']} | {v['home']} - {v['away']} | {v['campionato']} | {v['mercato']} | "
                 f"{_pct_no(v.get('risultato'))} | {_pct_no(v.get('esito'))} | "
                 f"{'+'.join(v.get('fonti') or []) or '—'} | {v['salvato_il']} |")
        if v.get("api") and "archivio" in (v.get("fonti") or []):
            L.append(f"  - API non usata: {v['api']}")
    for v in p["saltate"]:
        L.append(f"- **saltata**: {v['home']} - {v['away']} ({v['stagione']}, id {v['match_id']}): "
                 f"{v['saltata']}")
    if esito_scrittura is not None:
        L.append("")
        L.append(f"- scrittura: `{json.dumps(esito_scrittura, ensure_ascii=False, default=str)}`")
    if verifica is not None:
        L.append("- verifica: " + " · ".join(f"{k}: {v}" for k, v in verifica.items()))
    return L


def verifica_scrittura(prima: Sequence[Dict[str, Any]], dopo: Sequence[Dict[str, Any]],
                       attese: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Verifica INDIPENDENTE dal percorso di scrittura, campo per campo.

    * ogni riga non selezionata deve essere identica (testo canonico);
    * ogni riga selezionata deve avere esattamente i due campi di grading diversi
      e l'esito nuovo;
    * nessuna riga selezionata deve restare in attesa.
    """
    canon = lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)  # noqa: E731
    per_campo_prima = {rs.field_of(r): r for r in prima}
    per_campo_dopo = {rs.field_of(r): r for r in dopo}
    attese_per_campo = {rs.field_of(r): attese[str(r.get("match_id"))] for r in prima
                        if str(r.get("match_id")) in attese}
    fuori_selezione_prima = {k: v for k, v in per_campo_prima.items() if k not in attese_per_campo}
    fuori_selezione_dopo = {k: v for k, v in per_campo_dopo.items() if k not in attese_per_campo}
    identiche = (len(fuori_selezione_prima) == len(fuori_selezione_dopo)
                 and all(canon(fuori_selezione_prima[k]) == canon(fuori_selezione_dopo[k])
                         for k in fuori_selezione_prima))
    attesa_rimasta: List[str] = []
    campi_sbagliati: List[str] = []
    for campo, attesi_campi in attese_per_campo.items():
        riga_dopo = per_campo_dopo.get(campo)
        if riga_dopo is None:
            campi_sbagliati.append(f"{campo}: riga sparita")
            continue
        prima_riga = per_campo_prima[campo]
        diff = {k for k in set(prima_riga) | set(riga_dopo)
                if prima_riga.get(k, object()) != riga_dopo.get(k, object())}
        if diff != set(attesi_campi):
            campi_sbagliati.append(f"{campo}: campi diversi da quelli previsti ({sorted(diff)})")
        if riga_dopo.get(ESITO_FIELD) not in (ESITO_VINTO, ESITO_PERSO):
            attesa_rimasta.append(f"{campo}: esito {riga_dopo.get(ESITO_FIELD)!r}")
    return {
        "righe_prima": len(prima), "righe_dopo": len(dopo),
        "fuori_selezione_identiche": identiche,
        "fuori_selezione": len(fuori_selezione_dopo),
        "righe_gradate": len(attese_per_campo) - len(campi_sbagliati),
        "campi_sbagliati": len(campi_sbagliati),
        "ancora_in_attesa": len(attesa_rimasta),
        "dettagli": campi_sbagliati + attesa_rimasta,
        "ok": identiche and not campi_sbagliati and not attesa_rimasta,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scrivi", action="store_true", help="aggiorna davvero il Registro")
    ap.add_argument("--conferma", action="store_true",
                    help="seconda chiave: senza questa, --scrivi non scrive")
    ap.add_argument("--attesi", type=int, default=None,
                    help="numero di righe atteso nella selezione: se non combacia lo strumento si ferma")
    ap.add_argument("--stagione", default=None, help="limita a una stagione (es. 2025/2026)")
    ap.add_argument("--ore-minime", type=int, default=ORE_MINIME_DEFAULT,
                    help=f"la partita deve essere finita da almeno queste ore (default {ORE_MINIME_DEFAULT})")
    ap.add_argument("--fonte", choices=("auto", "api", "archivio"), default="auto",
                    help="dove prendere il risultato: api (football-data), archivio (CSV della "
                         "stagione), auto = prima l'API e l'archivio come controprova/ripiego")
    ap.add_argument("--risultati", default=None,
                    help="JSON {match_id: \"golcasa-golospiti\"} per una prova senza rete")
    ap.add_argument("--giorno", default=None, help="giorno dell'istantanea (default: oggi UTC)")
    ap.add_argument("--compatto", action="store_true", help="righe brevi per le annotazioni")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il referto in JSON")
    args = ap.parse_args(argv)

    righe, fonte_registro = rs.load_rows(strict=True)
    if righe is None:
        print("::error title=grading::Registro non leggibile")
        return 2
    if fonte_registro != rs.BACKEND_UPSTASH and args.scrivi:
        print(f"::error title=grading::backend attivo `{fonte_registro}`: questo grading si scrive "
              "solo su Upstash")
        return 2
    risultati = None
    if args.risultati:
        with open(args.risultati, encoding="utf-8") as f:
            risultati = json.load(f)
    from config import FOOTBALL_DATA_API_KEY
    p = piano(righe, api_key=FOOTBALL_DATA_API_KEY, fonte=args.fonte, risultati=risultati,
              ore_minime=args.ore_minime, stagione=args.stagione)
    print("\n".join(righe_testo(p) if not args.compatto else righe_compatti(p)))

    if args.attesi is not None and p["selezionate"] != args.attesi:
        print(f"::error title=grading::attese {args.attesi} righe in attesa, trovate "
              f"{p['selezionate']}: nessuna scrittura")
        return 3
    if not args.scrivi:
        print("\n**PROVA**: nessuna scrittura. Per eseguire servono `--scrivi --conferma`.")
        return 0
    if not args.conferma:
        print("\n::error title=grading::`--scrivi` senza `--conferma`: nessuna scrittura.")
        return 3
    if not p["da_gradare"]:
        print("\nNiente da gradare: nessuna riga in attesa con il risultato disponibile "
              "(idempotente, nessuna scrittura).")
        return 0

    # 1) Istantanea PRIMA di toccare: e' il punto di ripristino.
    giorno = chiave_istantanea_libera(args.giorno or _giorno_utc(), args.scrivi)
    snap = rs.upstash_snapshot(giorno, righe)
    print(f"\n- istantanea creata: `{snap['chiave']}` · {snap['righe']} righe · {snap['byte']} byte")

    # 2) Scrittura: la riga si ricostruisce dai campi di grading, il resto identico.
    attese = {str(v["match_id"]): v["campi"] for v in p["da_gradare"]}
    nuove = list(righe)
    cambiate = 0
    for i, r in enumerate(nuove):
        campi = attese.get(str(r.get("match_id")))
        if campi is None:
            continue
        nuova = applica(r, campi)
        if rs.field_of(nuova) != rs.field_of(r):
            print(f"::error title=grading::la riga {r.get('match_id')} cambierebbe chiave: "
                  "nessuna scrittura")
            return 4
        nuove[i] = nuova
        cambiate += 1
    esito_scrittura = rs.save_rows(nuove)
    print(f"- scrittura: `{json.dumps(esito_scrittura, ensure_ascii=False, default=str)}` "
          f"(righe ricostruite: {cambiate})")

    # 3) Rilettura e verifica indipendente.
    dopo = rs.upstash_rows()
    verifica = verifica_scrittura(righe, dopo, attese)
    print("- verifica: " + " · ".join(f"{k}: {v}" for k, v in verifica.items() if k != "dettagli"))
    for d in verifica["dettagli"]:
        print(f"  - {d}")
    print("\n" + "\n".join(righe_compatti(p, esito_scrittura, verifica)))
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"piano": p, "scrittura": esito_scrittura, "verifica": verifica,
                       "istantanea": snap["chiave"], "fonte_registro": fonte_registro},
                      f, ensure_ascii=False, indent=2, default=str)
    if not verifica["ok"]:
        print("::error title=grading::verifica NON superata: guarda i dettagli sopra "
              "(l'istantanea e' comunque al sicuro)")
        return 4
    print("\n**Grading eseguito e verificato**: solo `risultato_reale` ed `esito` aggiunti, "
          "ogni altra riga identica, istantanea disponibile per il ripristino.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
