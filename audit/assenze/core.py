"""Funzioni condivise della sonda assenze: rete esplicita, diagnostica e parsing PDF/HTML.

Le funzioni di parsing dei singoli campionati vivono in moduli separati e sono pure.
Questo modulo contiene soltanto i confini d'I/O e la normalizzazione tecnica.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_URL = "https://github.com/iFelice/SoccerMath2.0"
USER_AGENT = f"SoccerMath2.0-assenze-audit/1.0 (+{REPOSITORY_URL})"
REQUEST_DELAY_SECONDS = 3.0
REQUEST_TIMEOUT_SECONDS = 25
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

SOURCE_HOSTS: dict[str, frozenset[str]] = {
    "serie_a": frozenset({"legaseriea.it", "www.legaseriea.it", "images.legaseriea.it"}),
    "laliga": frozenset({"rfef.es", "www.rfef.es"}),
    "ligue1": frozenset({"ligue1.com", "www.ligue1.com"}),
}


@dataclass(frozen=True)
class HTTPResponse:
    requested_url: str
    final_url: str
    status_code: int | None
    body: bytes
    content_type: str | None = None
    error: str | None = None

    @property
    def response_bytes(self) -> int:
        return len(self.body)

    def diagnostic(self) -> dict[str, Any]:
        return {
            "url": self.requested_url,
            "final_url": self.final_url,
            "http_status": self.status_code,
            "response_bytes": self.response_bytes,
            "content_type": self.content_type,
            "error": self.error,
        }


class _NoRedirect(HTTPRedirectHandler):
    """Non segue redirect: ogni URL inserito corrisponde a una sola richiesta."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _VisibleText(HTMLParser):
    _BLOCKS = {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p",
        "section", "table", "td", "th", "tr", "ul",
    }
    _HIDDEN = {"script", "style", "noscript", "svg", "iframe", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._HIDDEN:
            self._hidden_depth += 1
        elif self._hidden_depth == 0 and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._HIDDEN and self._hidden_depth:
            self._hidden_depth -= 1
        elif self._hidden_depth == 0 and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0:
            self.parts.append(data)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(text: str) -> str:
    """Uniforma spazi e newline senza eliminare l'informazione strutturale."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    text = text.replace("\ufeff", "")
    return "\n".join(re.sub(r"[\t ]+", " ", line).strip() for line in text.split("\n"))


def strip_markup_line(line: str) -> str:
    """Toglie il Markdown usato dalle trascrizioni, mantenendo le parole."""
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    line = re.sub(r"^\s*#{1,6}\s*", "", line)
    return line.strip().strip("*").strip()


def html_to_text(source: str) -> str:
    parser = _VisibleText()
    parser.feed(source)
    parser.close()
    return normalize_text("\n".join(parser.parts))


def validate_source_url(source: str, url: str) -> str | None:
    """Restituisce un motivo se l'URL non è HTTPS o non appartiene alla fonte."""
    if not url or not url.strip():
        return "URL ufficiale non fornito"
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() != "https":
        return "URL rifiutato: è richiesto HTTPS"
    if not parsed.hostname or parsed.hostname.lower() not in SOURCE_HOSTS.get(source, frozenset()):
        return "URL rifiutato: host non appartenente alla fonte ufficiale prevista"
    if parsed.username or parsed.password:
        return "URL rifiutato: credenziali incorporate non ammesse"
    return None


def _read_limited(response: Any) -> tuple[bytes, str | None]:
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        return body[:MAX_RESPONSE_BYTES], f"risposta oltre il limite di {MAX_RESPONSE_BYTES} byte"
    return body, None


def fetch_url(
    source: str,
    url: str,
    *,
    delay_seconds: float = REQUEST_DELAY_SECONDS,
) -> HTTPResponse:
    """Esegue una richiesta identificabile, senza redirect né retry.

    Il ritardo viene applicato prima di ogni pagina. Gli errori HTTP/di rete sono
    dati diagnostici: non vengono convertiti in liste vuote di squalificati.
    """
    invalid = validate_source_url(source, url)
    if invalid:
        return HTTPResponse(url, url, None, b"", error=invalid)

    if delay_seconds > 0:
        time.sleep(delay_seconds)

    request = Request(
        url.strip(),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "it-IT,it;q=0.9,fr-FR;q=0.8,es-ES;q=0.7,en;q=0.5",
        },
        method="GET",
    )
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body, body_error = _read_limited(response)
            final_url = response.geturl()
            final_problem = validate_source_url(source, final_url)
            error = body_error or final_problem
            return HTTPResponse(
                requested_url=url,
                final_url=final_url,
                status_code=int(response.getcode()),
                body=body,
                content_type=response.headers.get("Content-Type"),
                error=error,
            )
    except HTTPError as exc:
        try:
            body, body_error = _read_limited(exc)
        except Exception:  # pragma: no cover - difesa da errori del body HTTPError
            body, body_error = b"", None
        return HTTPResponse(
            requested_url=url,
            final_url=getattr(exc, "url", url),
            status_code=int(exc.code),
            body=body,
            content_type=exc.headers.get("Content-Type") if exc.headers else None,
            error=body_error or f"risposta HTTP {exc.code}",
        )
    except URLError as exc:
        return HTTPResponse(
            requested_url=url,
            final_url=url,
            status_code=None,
            body=b"",
            error=f"errore di rete: {exc.reason}",
        )
    except TimeoutError:
        return HTTPResponse(
            requested_url=url,
            final_url=url,
            status_code=None,
            body=b"",
            error=f"timeout dopo {REQUEST_TIMEOUT_SECONDS} secondi",
        )
    except Exception as exc:  # gli errori inattesi restano diagnosi, non risultati vuoti
        return HTTPResponse(
            requested_url=url,
            final_url=url,
            status_code=None,
            body=b"",
            error=f"errore di richiesta: {type(exc).__name__}: {exc}",
        )


def extract_pdf_text(content: bytes) -> tuple[str | None, str | None]:
    """Converte un PDF via poppler, senza scrivere una copia del PDF su disco."""
    if not content.startswith(b"%PDF-"):
        return None, "la risposta HTTP 200 non è un PDF riconoscibile"
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
            input=content,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError:
        return None, "pdftotext non installato: impossibile leggere il PDF"
    except subprocess.TimeoutExpired:
        return None, "pdftotext ha superato il timeout di 30 secondi"
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        return None, f"pdftotext non ha letto il documento (exit {result.returncode}): {detail[:300]}"
    text = normalize_text(result.stdout.decode("utf-8", errors="replace"))
    if not text.strip():
        return None, "il PDF non contiene testo estraibile"
    return text, None


def decode_html(content: bytes) -> tuple[str | None, str | None]:
    """Decodifica una pagina HTML (charset dichiarato o UTF-8 come fallback)."""
    if not content:
        return None, "risposta senza byte"
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("windows-1252", errors="replace")
    visible = html_to_text(text)
    if not visible.strip():
        return None, "pagina HTML senza testo visibile"
    return visible, None


def empty_snapshot(source: str, label: str, report_window: str = "") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": source,
        "source_label": label,
        "status": "not_read",
        "captured_at_utc": utc_now_iso(),
        "report_window": report_window,
        "source_url": None,
        "requests": [],
        "http_status": None,
        "response_bytes": 0,
        "document_found": False,
        "rows_extracted": 0,
        "reason": None,
        "unmatched_teams": [],
    }


def attach_response(snapshot: dict[str, Any], response: HTTPResponse) -> None:
    snapshot["requests"].append(response.diagnostic())
    snapshot["response_bytes"] = sum(r.get("response_bytes", 0) for r in snapshot["requests"])
    statuses = [r.get("http_status") for r in snapshot["requests"]]
    snapshot["http_status"] = statuses[0] if len(statuses) == 1 else statuses


def set_rows_extracted(snapshot: dict[str, Any], rows: Iterable[Any]) -> None:
    snapshot["rows_extracted"] = len(list(rows))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
