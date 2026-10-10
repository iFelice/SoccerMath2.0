"""Verifica il Top Mix mercato contro il mercato e il modello contro il modello.

Per ogni riga ``topmix_mercato_v3`` nel periodo:

* ricostruisce la probabilita' de-vig e la quota dalla versione storica di
  ``SoccerMath/database/live_odds.json`` il cui ``generato_il`` e' quello scritto
  nel Registro; la prima registrazione usa ``*_prima`` e l'ultima i campi attuali;
* confronta ``prob_modello_prima``/``prob_modello`` con il modello riprodotto da
  ``replay_legacy_topmix.simulate_click`` allo stesso istante di registrazione e
  sullo stesso ``match_id`` ed esito;
* non considera una riga senza snapshot o senza stato modello ricostruibile come
  una corrispondenza. Tutti i confronti eseguiti sono esatti (nessuna tolleranza).

La prima registrazione delle righe prive dei campi ``*_prima`` e' ricostruita:
in quel caso si verifica solo l'ultima registrazione e lo si dichiara. Sola
lettura: il Registro e la storia git non vengono modificati.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOCCER = os.path.join(ROOT, "SoccerMath")
if SOCCER not in sys.path:
    sys.path.insert(0, SOCCER)

import market_odds  # noqa: E402
import replay_legacy_topmix as replay  # noqa: E402
import registry_coverage_check as check  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    PROB_MERCATO_FIELD,
    PROB_MERCATO_PRIMA_FIELD,
    PROB_MODELLO_FIELD,
    PROB_MODELLO_PRIMA_FIELD,
    QUOTA_MERCATO_FIELD,
    QUOTA_MERCATO_PRIMA_FIELD,
    QUOTE_LIVE_ISTANTE_FIELD,
    QUOTE_LIVE_ISTANTE_PRIMA_FIELD,
    SELECTOR_VERSION_CURRENT,
    ha_prima_registrazione,
    model_variant_read,
    selector_version_of,
)
from registry_coverage import top_mix_rows  # noqa: E402

UTC = timezone.utc
LIVE_ODDS_GIT_PATH = "SoccerMath/database/live_odds.json"
ESITO_RIMANDATA = "verifica rimandata: 0 righe topmix_mercato_v3"
ESITO_OK = "ok"
ESITO_FALLITA = "fallita"
ITALY = None  # riempito in main() da app.ITALY_TZ; valorizzabile direttamente nei test.


def _parse_istante(valore: Any) -> Optional[datetime]:
    """Interpreta un timestamp del Registro come UTC senza inventare un'ora."""
    if isinstance(valore, datetime):
        dt = valore
    else:
        testo = str(valore or "").strip()
        if not testo:
            return None
        dt = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                dt = datetime.strptime(testo, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(testo.replace("Z", "+00:00"))
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ITALY or UTC)
    return dt.astimezone(UTC)


def istante_del_salvataggio(riga: Dict[str, Any]) -> Optional[datetime]:
    """Istante UTC dell'ultima registrazione (``salvato_il``, ora italiana)."""
    return _parse_istante(riga.get("salvato_il"))


def istante_registrazione(riga: Dict[str, Any], registrazione: str) -> Optional[datetime]:
    """Istante del click associato ai campi ``prima`` o ``ultima``.

    ``salvato_il_originario`` e' scritto al primo aggiornamento; se manca, la
    riga non risulta aggiornata e la prima registrazione coincide con ``salvato_il``.
    """
    if registrazione == "prima":
        return _parse_istante(riga.get("salvato_il_originario") or riga.get("salvato_il"))
    return istante_del_salvataggio(riga)


def variante_da_confrontare(riga: Dict[str, Any]) -> str:
    """Variante storica del modello, mantenuta utile ai referti diagnostici."""
    return model_variant_read(riga)


def _numero_finito(valore: Any) -> bool:
    return (not isinstance(valore, bool) and isinstance(valore, (int, float))
            and math.isfinite(float(valore)))


def _numero_probabilita(valore: Any) -> bool:
    return _numero_finito(valore) and 0.0 <= float(valore) <= 1.0


def _timestamp_snapshot(riga: Dict[str, Any], registrazione: str) -> Optional[str]:
    campo = (QUOTE_LIVE_ISTANTE_PRIMA_FIELD if registrazione == "prima"
             else QUOTE_LIVE_ISTANTE_FIELD)
    valore = riga.get(campo)
    if not isinstance(valore, str) or not valore.strip():
        return None
    return valore.strip()


def _esito_massimo(probabilita: Dict[str, Any]) -> Optional[str]:
    """Argmax 1/X/2 con lo spareggio del selettore Top Mix mercato."""
    esiti = ("1", "X", "2")
    if any(not _numero_finito(probabilita.get(esito)) for esito in esiti):
        return None
    migliore = esiti[0]
    for esito in esiti[1:]:
        if float(probabilita[esito]) > float(probabilita[migliore]):
            migliore = esito
    return migliore


def _uguale_numero_esatto(registrato: Any, atteso: Any) -> bool:
    """Confronto numerico esatto, senza coercizioni da stringa o bool."""
    return _numero_finito(registrato) and _numero_finito(atteso) \
        and float(registrato) == float(atteso)


def _payload_sola_lega(payload: Dict[str, Any], lega: str) -> Optional[Dict[str, Any]]:
    leghe = payload.get("leghe") if isinstance(payload, dict) else None
    if not isinstance(leghe, dict) or not isinstance(leghe.get(lega), dict):
        return None
    return {"generato_il": payload.get("generato_il"), "leghe": {lega: leghe[lega]}}


def confronta_mercato_registrazione(
    riga: Dict[str, Any],
    registrazione: str,
    payload_snapshot: Optional[Dict[str, Any]],
    *,
    timestamp_richiesto: Optional[str] = None,
    commit_snapshot: Optional[str] = None,
) -> Dict[str, Any]:
    """Confronta probabilita' e quota salvate con uno snapshot storico.

    La probabilita' persistita dal percorso di produzione non e' il float grezzo
    della formula de-vig: e' ``round(round(p * 100, 1) / 100, 6)``. Si applica
    proprio quel passaggio (non una tolleranza) per confrontare campo contro
    campo esattamente. La quota e' invece confrontata col numero prodotto da
    ``market_odds.probabilita_mercato`` senza ulteriori arrotondamenti.

    Nella prima registrazione l'esito viene ricostruito come argmax dello
    snapshot (non serve ``mercato_standard_prima``); nell'ultima si usa l'esito
    registrato, cosi' un refresh continua a verificare la probabilita' del
    pronostico originario anche se nel frattempo e' cambiato il favorito.
    """
    out: Dict[str, Any] = {
        "registrazione": registrazione,
        "timestamp": timestamp_richiesto,
        "commit_snapshot": commit_snapshot,
        "esito": "non verificabile",
        "campi": [],
    }
    if not payload_snapshot:
        out["motivo"] = "snapshot live_odds.json non trovato nella storia git"
        return out
    generato_il = payload_snapshot.get("generato_il")
    if timestamp_richiesto and generato_il != timestamp_richiesto:
        out["motivo"] = (f"generato_il dello snapshot ({generato_il!r}) diverso dal timestamp "
                          f"richiesto ({timestamp_richiesto!r})")
        return out

    kickoff = riga.get("kickoff_utc")
    if not isinstance(kickoff, str) or not kickoff.strip():
        out["motivo"] = "kickoff_utc assente: abbinamento storico non verificabile"
        return out
    try:
        kickoff_dt = datetime.fromisoformat(kickoff.strip().replace("Z", "+00:00"))
    except ValueError:
        out["motivo"] = "kickoff_utc non valido: abbinamento storico non verificabile"
        return out
    if kickoff_dt.tzinfo is None:
        out["motivo"] = "kickoff_utc senza fuso orario: abbinamento storico non verificabile"
        return out

    lega = str(riga.get("campionato") or "").strip()
    sotto_payload = _payload_sola_lega(payload_snapshot, lega)
    if sotto_payload is None:
        out["motivo"] = f"lega {lega or '(assente)'} non presente nello snapshot"
        return out
    indice_info = market_odds.indice_partite(sotto_payload)
    indice = indice_info.get("indice") or {}
    evento, motivo = market_odds.cerca_quote_con_motivo(
        indice, str(riga.get("home") or ""), str(riga.get("away") or ""),
        riga.get("kickoff_utc"))
    if evento is None:
        out["motivo"] = motivo or "partita non abbinata nello snapshot"
        return out
    mercato = market_odds.probabilita_mercato(evento.get("libri") or [])
    probabilita = mercato.get("probs")
    quote = mercato.get("odds")
    if not isinstance(probabilita, dict) or not isinstance(quote, dict):
        out["motivo"] = "snapshot senza una terna 1X2 valida"
        return out

    if registrazione == "prima":
        esito = _esito_massimo(probabilita)
        campo_prob = PROB_MERCATO_PRIMA_FIELD
        campo_quota = QUOTA_MERCATO_PRIMA_FIELD
    else:
        esito = str(riga.get("mercato_standard") or "").strip().upper()
        campo_prob = PROB_MERCATO_FIELD
        campo_quota = QUOTA_MERCATO_FIELD
        if esito not in ("1", "X", "2"):
            esito = None
    if esito is None or not _numero_probabilita(probabilita.get(esito)):
        out["motivo"] = ("esito iniziale non ricostruibile" if registrazione == "prima"
                          else "mercato_standard assente o non 1/X/2")
        return out

    prob_grezza = float(probabilita[esito])
    prob_val = round(prob_grezza * 100.0, 1)
    atteso_prob = round(prob_val / 100.0, 6)
    attesa_quota = quote.get(esito)
    if not _numero_finito(attesa_quota):
        out["motivo"] = f"quota {esito} non ricostruibile dallo snapshot"
        return out

    confronti = []
    for campo, atteso in ((campo_prob, atteso_prob), (campo_quota, float(attesa_quota))):
        registrato = riga.get(campo)
        ok = _uguale_numero_esatto(registrato, atteso)
        confronti.append({
            "campo": campo,
            "registrato": registrato,
            "atteso": atteso,
            "esito": "corrisponde" if ok else "differisce",
        })
    out.update({
        "esito": ("corrisponde" if all(c["esito"] == "corrisponde" for c in confronti)
                  else "differisce"),
        "mercato": esito,
        "probabilita_devig_grezza": prob_grezza,
        "quota_snapshot": float(attesa_quota),
        "fonte": mercato.get("fonte"),
        "campi": confronti,
    })
    return out


def carica_snapshot_live_odds_da_git(
    timestamp_richiesti: Iterable[str],
    *,
    repo_root: str = ROOT,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Carica da git gli snapshot il cui ``generato_il`` coincide esattamente.

    ``git log`` visita solo i commit che hanno scritto il file. Con il checkout
    CI a ``fetch-depth: 0`` sono disponibili le versioni storiche committate dal
    workflow delle quote; la ricerca termina appena sono trovati tutti i
    timestamp richiesti.
    """
    richiesti = {str(t).strip() for t in timestamp_richiesti if str(t).strip()}
    report: Dict[str, Any] = {
        "snapshot_necessari": len(richiesti),
        "snapshot_trovati": 0,
        "commit_scansionati": 0,
        "errore_git": None,
    }
    if not richiesti:
        return {}, report
    try:
        log = subprocess.run(
            ["git", "-C", repo_root, "log", "--all", "--full-history", "--format=%H", "--",
             LIVE_ODDS_GIT_PATH],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
    except OSError as exc:
        report["errore_git"] = f"{type(exc).__name__}: {exc}"
        return {}, report
    if log.returncode != 0:
        report["errore_git"] = (log.stderr or f"git log uscito con {log.returncode}").strip()
        return {}, report

    trovati: Dict[str, Dict[str, Any]] = {}
    for commit in (line.strip() for line in log.stdout.splitlines() if line.strip()):
        if richiesti.issubset(trovati):
            break
        report["commit_scansionati"] += 1
        try:
            show = subprocess.run(
                ["git", "-C", repo_root, "show", f"{commit}:{LIVE_ODDS_GIT_PATH}"],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
        except OSError as exc:
            report["errore_git"] = f"{type(exc).__name__}: {exc}"
            break
        if show.returncode != 0:
            continue
        try:
            payload = json.loads(show.stdout)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        generato = payload.get("generato_il")
        if isinstance(generato, str) and generato in richiesti and generato not in trovati:
            trovati[generato] = {"payload": payload, "commit": commit}
    report["snapshot_trovati"] = len(trovati)
    return trovati, report


def _descrittore_modello(
    indice_riga: int,
    riga: Dict[str, Any],
    registrazione: str,
    esito: Optional[str],
    motivo_esito: Optional[str] = None,
) -> Dict[str, Any]:
    campo = PROB_MODELLO_PRIMA_FIELD if registrazione == "prima" else PROB_MODELLO_FIELD
    valore = riga.get(campo)
    istante = istante_registrazione(riga, registrazione)
    d = {
        "indice_riga": indice_riga,
        "riga": riga,
        "registrazione": registrazione,
        "campo": campo,
        "registrato": valore,
        "esito": "non verificabile",
        "mercato": esito,
        "istante": istante,
    }
    if not _numero_finito(valore):
        d["motivo"] = f"{campo} assente o non numerico"
    elif esito not in ("1", "X", "2"):
        d["motivo"] = motivo_esito or "esito della registrazione non ricostruibile"
    elif istante is None:
        d["motivo"] = "istante del click della registrazione non ricostruibile"
    else:
        d["motivo"] = "in attesa della simulazione point-in-time"
    return d


def _aggiungi_non_verificabile(riga: Dict[str, Any], registrazione: str, motivo: str,
                               *, categoria: str, istante: Optional[datetime] = None,
                               timestamp_snapshot: Optional[str] = None) -> Dict[str, Any]:
    return {
        "categoria": categoria,
        "match_id": riga.get("match_id"),
        "partita": f"{riga.get('home')} - {riga.get('away')}",
        "registrazione": registrazione,
        "istante": istante,
        "timestamp_snapshot": timestamp_snapshot,
        "esito": "non verificabile",
        "motivo": motivo,
    }


def _cerca_fixture(fixtures: Dict[str, List[Any]], riga: Dict[str, Any]) -> Optional[Any]:
    lega = riga.get("campionato")
    return next((f for f in fixtures.get(lega, [])
                 if str(getattr(f, "match_id", None)) == str(riga.get("match_id"))), None)


def _click_model_rows(click: Any, esito: str, match_id: Any) -> Optional[float]:
    """Prob_val del current prodotto da simulate_click per ID ed esito richiesti."""
    tutti = getattr(click, "model_prob_val_by_variant", None) or {}
    current = tutti.get(MODEL_VARIANT_CURRENT, {}) if isinstance(tutti, dict) else {}
    per_esito = current.get(str(match_id), {}) if isinstance(current, dict) else {}
    if isinstance(per_esito, dict) and _numero_finito(per_esito.get(esito)):
        return float(per_esito[esito])

    # Compatibilita' con ClickResult piu' vecchi/finti: prob_val e' confrontabile
    # solo quando la riga del replay ha lo stesso mercato_standard.
    rows = getattr(click, "rows", {}) or {}
    for replay_row in rows.get(MODEL_VARIANT_CURRENT, []) or []:
        if (str(replay_row.get("match_id")) == str(match_id)
                and str(replay_row.get("mercato_standard") or "").upper() == esito
                and _numero_finito(replay_row.get("prob_val"))):
            return float(replay_row["prob_val"])
    return None


def _simula_modello(descrittori: List[Dict[str, Any]], fixtures: Dict[str, List[Any]], *,
                    snapshot_cache: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Una simulazione per istante, includendo tutti i match dello stesso click."""
    risultati: List[Dict[str, Any]] = []
    non_verificabili: List[Dict[str, Any]] = []
    per_istante: Dict[datetime, Dict[str, Any]] = {}
    for d in descrittori:
        riga = d["riga"]
        instant = d.get("istante")
        if instant is None or d.get("motivo") != "in attesa della simulazione point-in-time":
            non_verificabili.append(_aggiungi_non_verificabile(
                riga, d["registrazione"], d.get("motivo", "stato modello non ricostruibile"),
                categoria="b) modello", istante=instant))
            continue
        target = _cerca_fixture(fixtures, riga)
        if target is None:
            non_verificabili.append(_aggiungi_non_verificabile(
                riga, d["registrazione"],
                f"match_id {riga.get('match_id')} non trovato nelle fixture",
                categoria="b) modello", istante=instant))
            continue
        gruppo = per_istante.setdefault(instant, {"targets": [], "leagues": set(), "checks": []})
        gruppo["targets"].append(target)
        gruppo["leagues"].add(riga.get("campionato"))
        gruppo["checks"].append(d)

    for instant, gruppo in sorted(per_istante.items(), key=lambda item: item[0]):
        # Una sola richiesta di calcolo per tutte le righe originate dal medesimo click.
        targets = list({str(t.match_id): t for t in gruppo["targets"]}.values())
        leghe = sorted({str(l) for l in gruppo["leagues"] if l})
        click = replay.simulate_click(
            instant, fixtures, targets=targets, leagues=leghe,
            snapshot_cache=snapshot_cache,
        )
        leak = getattr(click, "leak", None)
        if leak is not None and not getattr(click, "scrivibile", False):
            dettagli = getattr(leak, "dettagli", []) or []
            motivo = "stato point-in-time non valido" + (": " + "; ".join(dettagli) if dettagli else "")
            for d in gruppo["checks"]:
                non_verificabili.append(_aggiungi_non_verificabile(
                    d["riga"], d["registrazione"], motivo, categoria="b) modello",
                    istante=d.get("istante")))
            continue

        for d in gruppo["checks"]:
            riga = d["riga"]
            valore_replay = _click_model_rows(click, d["mercato"], riga.get("match_id"))
            if valore_replay is None:
                motivo = ("simulate_click non ha ricostruito il match nello stato selezionato "
                          "all'istante richiesto, oppure non ha prodotto la probabilita' "
                          f"dell'esito {d['mercato']}")
                d["motivo"] = motivo
                non_verificabili.append(_aggiungi_non_verificabile(
                    riga, d["registrazione"], motivo, categoria="b) modello",
                    istante=d.get("istante")))
                continue
            ok = _uguale_numero_esatto(d["registrato"], valore_replay)
            risultato = {
                "indice_riga": d["indice_riga"],
                "riga": riga,
                "registrazione": d["registrazione"],
                "campo": d["campo"],
                "istante": instant,
                "mercato": d["mercato"],
                "registrato": d["registrato"],
                "atteso": valore_replay,
                "snapshot_modello": getattr(click, "snapshot_sha", None),
                "esito": "corrisponde" if ok else "differisce",
            }
            risultati.append(risultato)
    return risultati, non_verificabili


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v).replace("|", "\\|").replace("\n", " ")


def _righe_confrontate(risultati: Sequence[Dict[str, Any]]) -> Set[int]:
    return {int(x["indice_riga"]) for x in risultati
            if x.get("esito") in ("corrisponde", "differisce")}


def _righe_con_corrispondenza_esatta(mercato: Sequence[Dict[str, Any]],
                                     modello: Sequence[Dict[str, Any]]) -> Set[int]:
    """Righe con almeno una registrazione completa esatta, non solo campi isolati."""
    righe = {int(x["indice_riga"]) for x in mercato if x.get("esito") == "corrisponde"}
    righe.update(int(x["indice_riga"]) for x in modello if x.get("esito") == "corrisponde")
    return righe


def _riepilogo_testo(*, n_v3: int, n_comparabili: int,
                     mercato: List[Dict[str, Any]], modello: List[Dict[str, Any]],
                     snapshot_report: Dict[str, Any], n_esatti: int, n_differenze: int) -> str:
    confronti_mercato_validi = [x for x in mercato
                                if x.get("esito") in ("corrisponde", "differisce")]
    confronti_modello_validi = [x for x in modello
                                if x.get("esito") in ("corrisponde", "differisce")]
    righe_mercato = len(_righe_confrontate(mercato))
    righe_modello = len(_righe_confrontate(modello))
    righe_esatte = len(_righe_con_corrispondenza_esatta(mercato, modello))
    return (
        f"[verifica] riepilogo: righe_v3={n_v3}; righe_v3_confrontabili={n_comparabili}; "
        f"righe_con_corrispondenza_esatta={righe_esatte}; "
        f"refresh_mercato_standard=immutabile (per_esito registrato); "
        f"a_mercato_righe={righe_mercato}, registrazioni={len(confronti_mercato_validi)}, "
        f"campi_esatti={sum(c['esito'] == 'corrisponde' for x in mercato for c in x.get('campi', []))}; "
        f"b_modello_righe={righe_modello}, registrazioni={len(confronti_modello_validi)}; "
        f"snapshot_necessari={snapshot_report.get('snapshot_necessari', 0)}, "
        f"snapshot_trovati={snapshot_report.get('snapshot_trovati', 0)}, "
        f"commit_scansionati={snapshot_report.get('commit_scansionati', 0)}; "
        f"confronti_esatti={n_esatti}; differenze={n_differenze}"
    )


def costruisci_referto(
    *,
    fonte: str,
    top: List[Dict[str, Any]],
    in_prova: List[Dict[str, Any]],
    non_v3: Counter,
    risultati_mercato: List[Dict[str, Any]],
    risultati_modello: List[Dict[str, Any]],
    non_verificabili: List[Dict[str, Any]],
    snapshot_report: Dict[str, Any],
    esito: str,
    n_comparabili: int,
    n_esatti: int,
    n_differenze: int,
) -> str:
    n_a_rows = len(_righe_confrontate(risultati_mercato))
    n_b_rows = len(_righe_confrontate(risultati_modello))
    n_exact_rows = len(_righe_con_corrispondenza_esatta(risultati_mercato, risultati_modello))
    n_a_reg = sum(x.get("esito") in ("corrisponde", "differisce") for x in risultati_mercato)
    n_b_reg = sum(x.get("esito") in ("corrisponde", "differisce") for x in risultati_modello)
    L = [
        "# Replay Top Mix mercato: controlli mercato-mercato e modello-modello",
        "",
        f"**Esito verifica: {esito}**",
        "",
        f"Registro: {fonte} · righe Top Mix nel periodo: {len(top)} · "
        f"righe `{SELECTOR_VERSION_CURRENT}`: {len(in_prova)} · "
        f"righe v3 effettivamente confrontabili: {n_comparabili}",
        "",
        "## Riepilogo confronti",
        "",
        f"- a) mercato contro mercato: **{n_a_rows} righe** confrontate, "
        f"{n_a_reg} registrazioni (prima/ultima) con snapshot ed evento ricostruiti; "
        f"{sum(c['esito'] == 'corrisponde' for x in risultati_mercato for c in x.get('campi', []))} "
        "campi esatti.",
        f"- b) modello contro modello: **{n_b_rows} righe** confrontate, "
        f"{n_b_reg} registrazioni con stato point-in-time ricostruito.",
        f"- snapshot live_odds necessari: **{snapshot_report.get('snapshot_necessari', 0)}**; "
        f"trovati nella storia git: **{snapshot_report.get('snapshot_trovati', 0)}** "
        f"(commit scansionati: {snapshot_report.get('commit_scansionati', 0)}).",
        f"- righe con almeno una registrazione esatta: **{n_exact_rows}**; "
        f"confronti esatti: **{n_esatti}**; differenze: **{n_differenze}**; "
        f"righe non verificabili: **{len(non_verificabili)}**.",
        "",
        "Le probabilita' di mercato sono confrontate esattamente dopo la stessa "
        "quantizzazione usata dalla scrittura (`round(round(p * 100, 1) / 100, 6)`); "
        "le quote, `prob_modello` e `prob_val` sono confrontate senza tolleranza.",
        "Per la prima registrazione l'esito e' l'argmax 1/X/2 ricostruito dallo "
        "snapshot storico; per l'ultima e' `mercato_standard` della riga, cosi' "
        "il rinfresco resta legato all'esito registrato anche se il favorito cambia.",
        "",
    ]
    if snapshot_report.get("errore_git"):
        L.append(f"**Lettura storia git:** {snapshot_report['errore_git']}")
        L.append("")
    if non_v3:
        L.append("RIGHE NON VERIFICABILI per selettore diverso da quello in prova:")
        for versione, n in sorted(non_v3.items()):
            L.append(f"- `{versione}`: {n} righe")
        L.append("")

    if risultati_mercato:
        L.extend([
            "## a) Mercato contro mercato",
            "",
            "| match_id | partita | registrazione | snapshot `generato_il` | commit git | esito usato | "
            "prob_mercato (Registro / snapshot quantizzato) | quota (Registro / snapshot) | esito |",
            "|---:|---|---|---|---|---|---:|---:|---|",
        ])
        for x in risultati_mercato:
            r = x["riga"]
            cmap = {c["campo"]: c for c in x["campi"]}
            pc = cmap.get(PROB_MERCATO_PRIMA_FIELD if x["registrazione"] == "prima"
                          else PROB_MERCATO_FIELD, {})
            qc = cmap.get(QUOTA_MERCATO_PRIMA_FIELD if x["registrazione"] == "prima"
                          else QUOTA_MERCATO_FIELD, {})
            L.append(
                f"| {r.get('match_id')} | {r.get('home')} - {r.get('away')} ({r.get('campionato')}) | "
                f"{x['registrazione']} | {_fmt(x.get('timestamp'))} | "
                f"{str(x.get('commit_snapshot') or '')[:10] or '—'} | {x.get('mercato')} | "
                f"{_fmt(pc.get('registrato'))} / {_fmt(pc.get('atteso'))} | "
                f"{_fmt(qc.get('registrato'))} / {_fmt(qc.get('atteso'))} | {x['esito']} |"
            )
        L.append("")
        L.append("Dettaglio campi confrontati esattamente:")
        for x in risultati_mercato:
            r = x["riga"]
            for c in x["campi"]:
                L.append(f"- match_id {r.get('match_id')} · {x['registrazione']} · "
                         f"`{c['campo']}`: {_fmt(c['registrato'])} vs {_fmt(c['atteso'])} — {c['esito']}")
        L.append("")

    if risultati_modello:
        L.extend([
            "## b) Modello contro modello",
            "",
            "| match_id | partita | registrazione | campo Registro | istante del click simulato | esito | "
            "prob_modello (Registro) | prob_val (simulate_click) | snapshot modello | esito |",
            "|---:|---|---|---|---|---|---:|---:|---|---|",
        ])
        for x in risultati_modello:
            r = x["riga"]
            L.append(
                f"| {r.get('match_id')} | {r.get('home')} - {r.get('away')} ({r.get('campionato')}) | "
                f"{x['registrazione']} | `{x['campo']}` | {_fmt(x.get('istante'))} | "
                f"{x.get('mercato')} | {_fmt(x.get('registrato'))} | {_fmt(x.get('atteso'))} | "
                f"{_fmt(x.get('snapshot_modello'))} | {x['esito']} |"
            )
        L.append("")

    L.extend([
        "## c) Esito della riga durante il rinfresco",
        "",
        "Verificato nel codice: `aggiorna_righe_mercato_in_attesa` seleziona la lettura "
        "`per_esito` usando `mercato_standard` gia' registrato e copia solo i campi "
        "di ultima registrazione; `mercato_standard` non appartiene ai campi aggiornabili. "
        "Quindi il rinfresco non puo' cambiare 1/X/2: aggiorna la probabilita' dell'esito "
        "registrato anche quando il favorito corrente e' cambiato. Test di regressione: "
        "`test_rinfresco_non_cambia_esito_registrato_se_cambia_il_favorito`.",
        "",
    ])

    if non_verificabili:
        L.append("## Non verificabili (non conteggiate come corrispondenze)")
        L.append("")
        L.append("| categoria | match_id | partita | registrazione | istante click / snapshot richiesto | motivo |")
        L.append("|---|---:|---|---|---|---|")
        for x in non_verificabili:
            riferimento = x.get("istante") or x.get("timestamp_snapshot")
            L.append(f"| {x.get('categoria')} | {x.get('match_id')} | {x.get('partita')} | "
                     f"{x.get('registrazione')} | {_fmt(riferimento)} | {x.get('motivo')} |")
        L.append("")

    riepilogo = _riepilogo_testo(
        n_v3=len(in_prova), n_comparabili=n_comparabili,
        mercato=risultati_mercato, modello=risultati_modello,
        snapshot_report=snapshot_report, n_esatti=n_esatti, n_differenze=n_differenze,
    )
    L.append(riepilogo)
    L.append(f"[verifica] esito: {esito}")
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    global ITALY
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="day_from", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=None)
    ap.add_argument("--to", dest="day_to", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=None)
    ap.add_argument("--fixtures", choices=("api", "csv"), default="api",
                    help="fixture: api = football-data.org (id del Registro), csv = offline per i test")
    ap.add_argument("--snapshot-cache", default=None, metavar="DIR")
    ap.add_argument("--out", default=None, metavar="FILE")
    args = ap.parse_args(argv)

    import app  # noqa: F401; definisce ITALY_TZ per i timestamp del Registro
    ITALY = app.ITALY_TZ

    righe, fonte = check.load_registry_readonly()
    top = top_mix_rows(righe, args.day_from, args.day_to)
    in_prova = [r for r in top if selector_version_of(r) == SELECTOR_VERSION_CURRENT]
    non_v3 = Counter(selector_version_of(r) or "(senza versione)"
                     for r in top if selector_version_of(r) != SELECTOR_VERSION_CURRENT)

    non_verificabili: List[Dict[str, Any]] = []
    ricostruita: Dict[int, bool] = {}
    timestamp_per_registrazione: Dict[Tuple[int, str], Optional[str]] = {}
    richiesti: Set[str] = set()
    for i, riga in enumerate(in_prova):
        ricostruita[i] = not ha_prima_registrazione(riga)
        for registrazione in ("prima", "ultima"):
            if registrazione == "prima" and ricostruita[i]:
                timestamp_per_registrazione[(i, registrazione)] = None
                non_verificabili.append(_aggiungi_non_verificabile(
                    riga, "prima", "prima registrazione ricostruita dall'ultima: verificata solo l'ultima",
                    categoria="a) mercato"))
                continue
            ts = _timestamp_snapshot(riga, registrazione)
            timestamp_per_registrazione[(i, registrazione)] = ts
            if ts:
                richiesti.add(ts)
            else:
                campo = (QUOTE_LIVE_ISTANTE_PRIMA_FIELD if registrazione == "prima"
                         else QUOTE_LIVE_ISTANTE_FIELD)
                non_verificabili.append(_aggiungi_non_verificabile(
                    riga, registrazione, f"{campo} assente o non valido", categoria="a) mercato"))

    snapshots, snapshot_report = carica_snapshot_live_odds_da_git(richiesti, repo_root=ROOT)
    risultati_mercato: List[Dict[str, Any]] = []
    outcome_prima: Dict[int, Optional[str]] = {}
    for i, riga in enumerate(in_prova):
        outcome_prima[i] = None
        for registrazione in ("prima", "ultima"):
            if registrazione == "prima" and ricostruita[i]:
                continue
            ts = timestamp_per_registrazione.get((i, registrazione))
            if not ts:
                continue
            snapshot_rec = snapshots.get(ts)
            if snapshot_rec is None:
                non_verificabili.append(_aggiungi_non_verificabile(
                    riga, registrazione,
                    f"snapshot con generato_il={ts} non trovato nella storia git",
                    categoria="a) mercato", timestamp_snapshot=ts))
                continue
            confronto = confronta_mercato_registrazione(
                riga, registrazione, snapshot_rec["payload"], timestamp_richiesto=ts,
                commit_snapshot=snapshot_rec.get("commit"),
            )
            confronto["indice_riga"] = i
            confronto["riga"] = riga
            risultati_mercato.append(confronto)
            if registrazione == "prima" and confronto.get("mercato") in ("1", "X", "2"):
                outcome_prima[i] = confronto["mercato"]
            if confronto["esito"] == "non verificabile":
                non_verificabili.append(_aggiungi_non_verificabile(
                    riga, registrazione, confronto.get("motivo", "snapshot non utilizzabile"),
                    categoria="a) mercato", timestamp_snapshot=ts))

    descrittori: List[Dict[str, Any]] = []
    for i, riga in enumerate(in_prova):
        if ricostruita[i]:
            non_verificabili.append(_aggiungi_non_verificabile(
                riga, "prima", "prima registrazione ricostruita: il modello si verifica solo sull'ultima",
                categoria="b) modello", istante=istante_registrazione(riga, "ultima")))
        else:
            motivo_esito = None
            if outcome_prima[i] is None:
                motivo_esito = "esito della prima registrazione non ricostruibile dallo snapshot storico"
            descrittori.append(_descrittore_modello(i, riga, "prima", outcome_prima[i], motivo_esito))
        outcome_ultima = str(riga.get("mercato_standard") or "").strip().upper()
        descrittori.append(_descrittore_modello(
            i, riga, "ultima", outcome_ultima if outcome_ultima in ("1", "X", "2") else None,
            "mercato_standard assente o non 1/X/2",
        ))

    desc_pronti = [d for d in descrittori
                   if d.get("motivo") == "in attesa della simulazione point-in-time"]
    leghe_modello = sorted({str(d["riga"].get("campionato")) for d in desc_pronti
                            if d["riga"].get("campionato")})
    fixtures: Dict[str, List[Any]] = {}
    if desc_pronti:
        if args.fixtures == "api":
            from config import FOOTBALL_DATA_API_KEY
            fixtures = replay.fixtures_from_api(FOOTBALL_DATA_API_KEY, leghe_modello)
        else:
            fixtures = replay.fixtures_from_csv_and_archive(leghe_modello)
    risultati_modello, non_verificabili_modello = _simula_modello(
        descrittori, fixtures, snapshot_cache=args.snapshot_cache)
    non_verificabili.extend(non_verificabili_modello)

    indici_confrontati = _righe_confrontate(risultati_mercato) | _righe_confrontate(risultati_modello)
    n_comparabili = len(indici_confrontati)
    confronti_campi = [c for x in risultati_mercato for c in x.get("campi", [])]
    esiti_confronti = [c.get("esito") for c in confronti_campi] + [x.get("esito") for x in risultati_modello]
    n_esatti = sum(e == "corrisponde" for e in esiti_confronti)
    n_differenze = sum(e == "differisce" for e in esiti_confronti)
    n_righe_esatte = len(_righe_con_corrispondenza_esatta(risultati_mercato, risultati_modello))
    if not in_prova:
        esito, rc = ESITO_RIMANDATA, 0
        # Solo l'assenza reale di righe v3 resta verde e genera l'annotazione.
        print(f"::warning::{ESITO_RIMANDATA}", flush=True)
    elif n_righe_esatte == 0:
        # Righe v3 presenti senza alcuna registrazione completa esatta (anche se
        # tutte non verificabili) non superano il gate.
        esito = (f"{ESITO_FALLITA} (righe v3 presenti, zero corrispondenze esatte; "
                 f"{n_comparabili} righe confrontabili; {n_differenze} differenze)")
        rc = 1
    elif n_differenze:
        esito = f"{ESITO_FALLITA} ({n_differenze} confronti esatti discordanti)"
        rc = 1
    elif n_esatti == 0:
        # Difesa aggiuntiva contro un campione presente ma non confrontato.
        esito, rc = f"{ESITO_FALLITA} (righe v3 presenti, zero corrispondenze esatte)", 1
    else:
        esito = (f"{ESITO_OK} ({n_comparabili}/{len(in_prova)} righe v3 confrontabili; "
                 f"a={len(_righe_confrontate(risultati_mercato))} righe, "
                 f"b={len(_righe_confrontate(risultati_modello))} righe, "
                 f"{n_esatti} confronti esatti)")
        rc = 0

    testo = costruisci_referto(
        fonte=fonte, top=top, in_prova=in_prova, non_v3=non_v3,
        risultati_mercato=risultati_mercato, risultati_modello=risultati_modello,
        non_verificabili=non_verificabili, snapshot_report=snapshot_report,
        esito=esito, n_comparabili=n_comparabili, n_esatti=n_esatti,
        n_differenze=n_differenze,
    )
    print(testo, flush=True)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(testo)
        print(f"[verifica] referto: {args.out}", flush=True)
    if rc:
        print("[verifica] confronti esatti non riprodotti; vedi righe e campi sopra", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
