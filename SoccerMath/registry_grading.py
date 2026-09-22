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
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

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
from registry_pulizia import campi_grezzi  # noqa: E402
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


def canon(riga: Dict[str, Any]) -> str:
    """Testo canonico di una riga (lo STESSO che scrive ``registry_store``)."""
    return json.dumps(riga, ensure_ascii=False, sort_keys=True, default=str)


def nomi_stantii(campi_grezzi: Dict[str, Tuple[str, Dict[str, Any]]],
                 prima_per_chiave: Dict[str, Dict[str, Any]],
                 dopo_per_chiave: Dict[str, Dict[str, Any]],
                 chiavi_aggiornate: Optional[Iterable[str]] = None) -> List[str]:
    """Nomi di campo che portano la copia VECCHIA di una riga aggiornata.

    Il salvataggio scrive la riga sotto il nome canonico di OGGI (``field_of``,
    cioe' la chiave di dedup ricalcolata). Se la stessa riga viveva anche sotto un
    nome di campo di una convenzione precedente, quel campo resta li' e porta il
    contenuto di prima: due campi con la stessa chiave e contenuto DIVERSO fermano
    la lettura del Registro (e' la guardia dello store, e serve: la chiave non
    distingue piu' due righe). Quei nomi si tolgono — e SOLO quelli: un campo il
    cui contenuto e' gia' quello atteso non si tocca, un campo di un'altra riga
    nemmeno.
    """
    da_togliere: List[str] = []
    # Si guardano SOLO le righe che questa scrittura ha aggiornato: una coppia di
    # nomi identici su una riga NON toccata e' preesistente, la lettura la tollera
    # (stesso contenuto) e toccarla sarebbe una modifica fuori dalla richiesta.
    aggiornate = set(chiavi_aggiornate) if chiavi_aggiornate is not None else None
    for nome, (testo, riga) in sorted(campi_grezzi.items()):
        chiave = rs.field_of(riga)
        atteso = dopo_per_chiave.get(chiave)
        prima = prima_per_chiave.get(chiave)
        if atteso is None or prima is None:
            continue
        if aggiornate is not None and chiave not in aggiornate:
            continue
        if nome == rs.field_of(atteso):
            continue                                  # e' il campo canonico di oggi
        if canon(riga) == canon(prima):
            da_togliere.append(nome)                  # copia vecchia sotto nome vecchio
    return da_togliere


def ripara_nomi(*, istantanea: str, scrivi: bool = False, api_key: str = "",
                db_dir: Optional[str] = None, fonte: str = "archivio") -> Dict[str, Any]:
    """Toglie i nomi di campo vecchi lasciati da un aggiornamento del Registro.

    L'istantanea scattata PRIMA della scrittura e' il termine di confronto: le
    righe attese sono quelle dell'istantanea con il grading applicato (stesso
    piano, stessa fonte). Si cancellano SOLO i campi che portano il contenuto
    precedente di una riga aggiornata: nient'altro.
    """
    righe_snap = rs.upstash_snapshot_read(istantanea)
    if righe_snap is None:
        return {"ok": False, "motivo": f"istantanea `{istantanea}` non leggibile: riparazione non possibile"}
    p = piano(righe_snap, api_key=api_key, db_dir=db_dir, fonte=fonte)
    prima_per_chiave = {rs.field_of(r): r for r in righe_snap}
    dopo_per_chiave = {rs.field_of(r): r for r in righe_snap}
    for v in p["da_gradare"]:
        chiave = next((k for k, r in prima_per_chiave.items()
                       if str(r.get("match_id")) == str(v["match_id"])), None)
        if chiave is None:
            continue
        dopo_per_chiave[chiave] = applica(prima_per_chiave[chiave], v["campi"])
    aggiornate = {k for k, r in dopo_per_chiave.items()
                  if canon(r) != canon(prima_per_chiave.get(k) or {})}
    stantii = nomi_stantii(campi_grezzi(), prima_per_chiave, dopo_per_chiave, aggiornate)
    fuori: Dict[str, Any] = {
        "istantanea": istantanea, "righe_istantanea": len(righe_snap),
        "da_gradare": len(p["da_gradare"]), "nomi_stantii": stantii, "scritto": False,
    }
    if not stantii:
        fuori["nota"] = "nessun nome di campo vecchio da togliere"
        return fuori
    if not scrivi:
        fuori["nota"] = "PROVA: nessuna scrittura"
        return fuori
    risposta = rs.upstash_raw(["HDEL", rs.hash_key()] + stantii)
    fuori["hdel"] = risposta.get("result")
    fuori["scritto"] = True
    dopo = rs.upstash_rows()                      # qui la lettura DEVE tornare a funzionare
    attesi = {k: canon(v) for k, v in dopo_per_chiave.items()}
    per_chiave_dopo = {rs.field_of(r): r for r in dopo}
    for k, r in per_chiave_dopo.items():
        if k not in attesi:
            fuori.setdefault("errori", []).append(f"riga {k}: nell'hash ma non nell'istantanea")
        elif canon(r) != attesi[k]:
            fuori.setdefault("errori", []).append(f"riga {k}: contenuto diverso dall'atteso")
    for k in attesi:
        if k not in per_chiave_dopo:
            fuori.setdefault("errori", []).append(f"riga {k}: sparita dall'hash")
    fuori["righe_dopo"] = len(dopo)
    fuori["righe_attese"] = len(dopo_per_chiave)
    fuori["ok"] = (len(dopo) == len(dopo_per_chiave)
                   and not fuori.get("errori") and fuori["hdel"] == len(stantii))
    return fuori


def diagnosi_nomi(*, istantanea: Optional[str] = None, api_key: str = "",
                  db_dir: Optional[str] = None, fonte: str = "archivio") -> Dict[str, Any]:
    """Com'e' fatto l'hash, nome per nome: quante righe, quanti campi, quali doppi.

    Sola lettura. Risponde con i numeri a due domande diverse:

    * **coerenza**: la lettura del Registro funziona e le righe sono quelle attese
      (confronto con l'istantanea scattata prima della scrittura, se c'e')?
    * **struttura**: quali chiavi sono presenti sotto PIU' nomi di campo, e quei nomi
      portano lo stesso contenuto (la lettura li tollera) o contenuto diverso (la
      fermano)?
    """
    campi = campi_grezzi()
    per_chiave: Dict[str, List[Tuple[str, str]]] = {}
    for nome, (testo, riga) in campi.items():
        per_chiave.setdefault(rs.field_of(riga), []).append((nome, testo))
    doppi = {k: v for k, v in per_chiave.items() if len(v) > 1}
    doppi_diversi = {k: v for k, v in doppi.items() if len({t for _n, t in v}) > 1}
    fuori: Dict[str, Any] = {
        "campi_grezzi": len(campi),
        "righe_logiche": len(per_chiave),
        "chiavi_con_piu_nomi": len(doppi),
        "chiavi_con_contenuti_diversi": len(doppi_diversi),
        "esempi_doppi": [{"chiave": k, "nomi": [n for n, _t in v]}
                         for k, v in sorted(doppi.items())[:8]],
        "esempi_doppi_diversi": [{"chiave": k, "nomi": [n for n, _t in v]}
                                 for k, v in sorted(doppi_diversi.items())[:8]],
    }
    lettura_ok, errore, righe = True, "", []
    try:
        righe = rs.upstash_rows()
    except Exception as e:                                            # pragma: no cover - rete
        lettura_ok, errore = False, str(e)
    fuori["lettura_ok"] = lettura_ok
    fuori["righe_lette"] = len(righe) if lettura_ok else None
    if errore:
        fuori["lettura_errore"] = errore
    if istantanea:
        fuori["istantanea"] = istantanea
        righe_snap = rs.upstash_snapshot_read(istantanea)
        fuori["istantanea_leggibile"] = righe_snap is not None
        if righe_snap is not None:
            p = piano(righe_snap, api_key=api_key, db_dir=db_dir, fonte=fonte)
            attese = {rs.field_of(r): r for r in righe_snap}
            for voce in p["da_gradare"]:
                chiave = next((k for k, r in attese.items()
                               if str(r.get("match_id")) == str(voce["match_id"])), None)
                if chiave is not None:
                    attese[chiave] = applica(attese[chiave], voce["campi"])
            lette = {rs.field_of(r): r for r in righe}
            fuori["righe_attese"] = len(attese)
            fuori["da_gradare_nell_istantanea"] = len(p["da_gradare"])
            fuori["mancanti"] = len([k for k in attese if k not in lette])
            fuori["in_piu"] = len([k for k in lette if k not in attese])
            fuori["diverse"] = len([k for k in attese if k in lette
                                    and canon(lette[k]) != canon(attese[k])])
            fuori["coerente"] = (fuori["mancanti"] == 0 and fuori["in_piu"] == 0
                                 and fuori["diverse"] == 0 and lettura_ok
                                 and fuori["righe_attese"] == fuori["righe_lette"])
    return fuori


def elenca_istantanee(prefisso: str = "sm:registro:snapshot:") -> List[Dict[str, Any]]:
    """Tutte le istantanee del Registro, con che cosa contengono (SOLA LETTURA).

    Serve a sapere su quali fotografie si puo' contare: una chiave ``...-campi``
    contiene i CAMPI come sono scritti nell'hash (nome -> testo), quindi e' l'unica
    che puo' documentare i nomi di campo, compresi quelli vecchi; una chiave senza
    suffisso contiene le righe logiche, che non dicono niente sui nomi.
    """
    chiavi = rs.upstash_raw(["KEYS", f"{prefisso}*"]).get("result") or []
    fuori: List[Dict[str, Any]] = []
    for chiave in sorted(str(c) for c in chiavi):
        nome_chiave = chiave[len(prefisso):] if chiave.startswith(prefisso) else chiave
        corpo = rs.upstash_raw(["GET", chiave]).get("result")
        voce: Dict[str, Any] = {"chiave": nome_chiave,
                                "byte": len(corpo.encode("utf-8")) if isinstance(corpo, str) else None}
        try:
            dati = json.loads(corpo) if isinstance(corpo, str) else None
        except (TypeError, json.JSONDecodeError):
            dati = None
        if isinstance(dati, list):
            voci = [(None, r) for r in dati if isinstance(r, dict)]
            voce.update({"tipo": "righe", "campi": None, "righe": len(voci)})
        elif isinstance(dati, dict):
            voci = []
            for nome, testo in dati.items():
                try:
                    riga = json.loads(testo)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(riga, dict):
                    voci.append((nome, riga))
            voce.update({"tipo": "campi", "campi": len(voci), "righe": len(voci)})
        else:
            voce.update({"tipo": "illeggibile", "campi": None, "righe": None})
            fuori.append(voce)
            continue
        chiavi_logiche = {rs.field_of(r) for _n, r in voci}
        voce["righe_logiche"] = len(chiavi_logiche)
        voce["extra"] = (len(voci) - len(chiavi_logiche)) if voce["tipo"] == "campi" else None
        fuori.append(voce)
    return fuori


def elenca_campi_extra(chiave_istantanea: str,
                       live: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """I nomi di campo NON allineati alla chiave, in un'istantanea dei campi.

    Per ognuno: la chiave logica che lo contiene, la partita, la variante letta e se
    quel nome esiste ANCORA nell'hash vivo (nomi come sono scritti adesso). Un nome
    che l'istantanea ha e il vivo non ha piu' e' un nome tolto dopo quella
    fotografia: e' l'elenco che serve per dire, con i fatti, che cosa e' stato
    rimosso e che cosa invece e' ancora la' (SOLA LETTURA).
    """
    # La chiave si puo' indicare intera o con il solo nome del giorno (come appare
    # nei referti): il prefisso e' uno solo e vive in ``registry_store``.
    completa = chiave_istantanea if chiave_istantanea.startswith("sm:registro:snapshot:") \
        else rs.snapshot_key(chiave_istantanea)
    corpo = rs.upstash_raw(["GET", completa]).get("result")
    if not isinstance(corpo, str):
        return {"chiave": chiave_istantanea, "esiste": False, "extra": []}
    try:
        dati = json.loads(corpo)
    except (TypeError, json.JSONDecodeError):
        return {"chiave": chiave_istantanea, "esiste": True, "illeggibile": True, "extra": []}
    if not isinstance(dati, dict):
        return {"chiave": chiave_istantanea, "esiste": True, "non_e_una_foto_di_campi": True, "extra": []}
    nomi_vivi = set(campi_grezzi().keys())
    per_chiave: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for nome, testo in dati.items():
        try:
            riga = json.loads(testo)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(riga, dict):
            per_chiave.setdefault(rs.field_of(riga), []).append((nome, riga))
    extra: List[Dict[str, Any]] = []
    for chiave in sorted(per_chiave):
        voci = per_chiave[chiave]
        for nome, riga in voci:
            if nome == chiave:
                continue
            extra.append({
                "nome": nome, "chiave": chiave, "match_id": riga.get("match_id"),
                "home": riga.get("home"), "away": riga.get("away"),
                "variante": model_variant_read(riga), "origine": origin_of(riga),
                "ancora_presente": nome in nomi_vivi,
            })
    return {"chiave": chiave_istantanea, "esiste": True, "righe_logiche": len(per_chiave),
            "campi": sum(len(v) for v in per_chiave.values()), "extra": extra,
            "extra_ancora_presenti": sum(1 for e in extra if e["ancora_presente"]),
            "extra_non_piu_presenti": sum(1 for e in extra if not e["ancora_presente"])}


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
    ap.add_argument("--elenca-istantanee", action="store_true",
                    help="sola lettura: quali istantanee esistono e che cosa contengono "
                         "(righe logiche oppure campi scritti, con i nomi extra)")
    ap.add_argument("--campi-di", default=None,
                    help="sola lettura: elenca i nomi di campo EXTRA di un'istantanea dei campi "
                         "(``<giorno>-pre-pulizia-campi`` …) e dice quali esistono ancora "
                         "nell'hash vivo")
    ap.add_argument("--diagnosi-nomi", action="store_true",
                    help="sola lettura: com'e' fatto l'hash (campi grezzi, chiavi con piu' nomi, "
                         "contenuti diversi, coerenza con l'istantanea)")
    ap.add_argument("--ripara-nomi", action="store_true",
                    help="toglie i nomi di campo VECCHI lasciati da un aggiornamento del Registro "
                         "(usa l'istantanea scattata prima della scrittura come termine di confronto)")
    ap.add_argument("--istantanea", default=None,
                    help="giorno dell'istantanea da usare per la riparazione (default: "
                         "``<oggi>-pre-grading``)")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il referto in JSON")
    args = ap.parse_args(argv)

    if args.elenca_istantanee or args.campi_di:
        intestazione = "sm:registro:snapshot:"
        if args.elenca_istantanee:
            for voce in elenca_istantanee(intestazione):
                print("ISTANTANEA| " + " | ".join(
                    f"{k} {v}" for k, v in voce.items() if v is not None))
        if args.campi_di:
            for chiave_chiesta in [c.strip() for c in args.campi_di.split(",") if c.strip()]:
                d = elenca_campi_extra(chiave_chiesta)
                print(f"CAMPI| chiave {chiave_chiesta} | esiste: {d.get('esiste')} | "
                      f"righe_logiche: {d.get('righe_logiche')} | campi: {d.get('campi')} | "
                      f"extra: {len(d.get('extra') or [])} | ancora presenti: "
                      f"{d.get('extra_ancora_presenti')} | non piu' presenti: "
                      f"{d.get('extra_non_piu_presenti')}")
                for e in d.get("extra") or []:
                    print(f"EXTRA| {e['nome']} | chiave {e['chiave']} | {e['home']} - {e['away']} "
                          f"| {e['variante']} | origine {e['origine']} | id {e['match_id']} | "
                          f"ancora presente: {'si' if e['ancora_presente'] else 'NO'}")
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump({"istantanee": elenca_istantanee(intestazione) if args.elenca_istantanee else None,
                           "campi": [elenca_campi_extra(c) for c in (args.campi_di or "").split(",")
                                     if c.strip()]},
                          f, ensure_ascii=False, indent=2, default=str)
        return 0

    if args.diagnosi_nomi:
        from config import FOOTBALL_DATA_API_KEY
        d = diagnosi_nomi(istantanea=args.istantanea or f"{args.giorno or _giorno_utc()}-pre-grading",
                          api_key=FOOTBALL_DATA_API_KEY, fonte=args.fonte)
        print("DIAGNOSI| " + " · ".join(f"{k}: {v}" for k, v in d.items()
                                        if not isinstance(v, list)))
        for esempio in d.get("esempi_doppi") or []:
            print(f"DOPPIO| {esempio['chiave']} -> {', '.join(esempio['nomi'])}")
        for esempio in d.get("esempi_doppi_diversi") or []:
            print(f"DOPPIO-DIVERSO| {esempio['chiave']} -> {', '.join(esempio['nomi'])}")
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        return 0 if d["lettura_ok"] and d.get("coerente", True) else 3

    if args.ripara_nomi:
        # La riparazione non passa da ``load_rows``: quando i nomi doppi ci sono,
        # la lettura del Registro e' proprio quella che si rompe.
        from config import FOOTBALL_DATA_API_KEY
        giorno = args.istantanea or f"{args.giorno or _giorno_utc()}-pre-grading"
        r = ripara_nomi(istantanea=giorno, scrivi=args.scrivi and args.conferma,
                        api_key=FOOTBALL_DATA_API_KEY, fonte=args.fonte)
        testo = " · ".join(f"{k}: {v}" for k, v in r.items() if k != "nomi_stantii")
        righe_out = [f"RIPARAZIONE| {testo}"]
        for nome in r.get("nomi_stantii") or []:
            righe_out.append(f"NOME-VECCHIO| {nome}")
        print("\n".join(righe_out))
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2, default=str)
        if not r.get("scritto") and args.scrivi and r.get("nomi_stantii"):
            print("::error title=grading::--scrivi senza --conferma: nessuna riparazione")
            return 3
        if not r.get("ok", True):
            print("::error title=grading::riparazione NON verificata: vedi il referto")
            return 4
        return 0

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

    # 2b) Nomi di campo VECCHI delle righe aggiornate: se una riga viveva sotto la
    # convenzione di prima, il salvataggio scrive il nome canonico di oggi e il
    # campo vecchio resta con il contenuto di prima. Due campi con la stessa
    # chiave e contenuto diverso FERMANO la lettura del Registro: si tolgono qui,
    # subito, con lo stesso piano (istantanea = termine di confronto).
    prima_per_chiave = {rs.field_of(r): r for r in righe}
    dopo_per_chiave = {rs.field_of(r): r for r in nuove}
    aggiornate = {k for k, r in dopo_per_chiave.items()
                  if canon(r) != canon(prima_per_chiave.get(k) or {})}
    stantii = nomi_stantii(campi_grezzi(), prima_per_chiave, dopo_per_chiave, aggiornate)
    if stantii:
        risposta_hdel = rs.upstash_raw(["HDEL", rs.hash_key()] + stantii)
        print(f"- nomi di campo vecchi tolti: **{len(stantii)}** · `HDEL` result = "
              f"**{risposta_hdel.get('result')}** ({', '.join('`' + s + '`' for s in stantii[:4])}"
              f"{' …' if len(stantii) > 4 else ''})")

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
