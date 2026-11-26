"""The scanner's HTML report, restyled in Charting Lab's look.

The report pages (scans/<id>/index.html, their chart pages, portfolio.html and the scanner's home page) are read from
the scanner's folder, or fetched from its server for pages it builds on the fly, and served here with our theme
stylesheet and a small script added. Nothing is written into the scanner's folder. The report's own buttons
(Watch, Enter trade, Refresh) call the scanner's /api; those calls are passed through to its server.
"""
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse, Response

from app.api.scanner import SCAN_ID, _rows, scanner_dir, scans_dir
from app.config import get_settings
from app.wording import neutral_html

router = APIRouter(prefix="/scanner/report", tags=["scanner"])
ASSETS = Path(__file__).resolve().parent.parent / "static"


def restyle_html(html: str) -> str:
    """Add the theme script (before the page's first script, so it can wrap lightweight-charts) and the theme
    stylesheet (last in <head>, so it wins over the report's own styles)."""
    css = (ASSETS / "scanner_report.css").read_text(encoding="utf-8")
    js = (ASSETS / "scanner_report.js").read_text(encoding="utf-8")
    head = f"<script>{js}</script>"
    tail = f'<style id="charting-lab-theme">{css}</style>'
    low = html.lower()
    j = low.find("</head>")
    if j < 0:
        return head + tail + html
    i = low.find("<script")
    k = i if 0 <= i < j else j
    html = html[:k] + head + html[k:]
    lw = re.search(r'<script[^>]*lightweight-charts[^>]*>\s*</script>', html, re.I)
    if lw:
        html = html[:lw.end()] + "<script>window.__clWrap && window.__clWrap();</script>" + html[lw.end():]
    j = html.lower().find("</head>")
    return html[:j] + tail + html[j:]


def restyle_js(js: str) -> str:
    """The report's scripts use site-root paths (/api/..., /<scan>/index.html); point them at this route."""
    return (js.replace('"/api/', 'window.__SCAN_BASE + "api/')
              .replace('location.href = "/" + ', 'location.href = window.__SCAN_BASE + ')
              .replace('a.href = "/";', 'a.href = window.__SCAN_BASE;')
              .replace("rgba(60,60,60,0.55)", "rgba(128,134,150,0.55)"))


def _scanner_get(path: str) -> tuple[bytes, str]:
    url = get_settings().scanner_url.rstrip("/") + "/" + path
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.read(), r.headers.get("content-type", "text/html; charset=utf-8")
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(404, f"not in the scans folder and the scanner is offline: {e}") from e


@router.api_route("/api/{path:path}", methods=["GET", "POST"])
async def scanner_api(path: str, request: Request) -> Response:
    """Pass the report's own actions (watch, trade, refresh, portfolio) to the scanner's server."""
    url = get_settings().scanner_url.rstrip("/") + "/api/" + path
    body = await request.body() if request.method == "POST" else None
    req = urllib.request.Request(url, data=body, method=request.method,
                                 headers={"Content-Type": request.headers.get("content-type", "application/json")})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return Response(r.read(), status_code=r.status, media_type=r.headers.get("content-type"))
    except urllib.error.HTTPError as e:
        return Response(e.read(), status_code=e.code, media_type=e.headers.get("content-type"))
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(502, f"the scanner is not running ({get_settings().scanner_url}): {e}") from e


def chart_signal(scans: Path, path: str) -> dict | None:
    """The signal behind a report chart page (<scan>/charts/<file>.html), from the scan's CSVs."""
    parts = path.replace("\\", "/").split("/")
    m = SCAN_ID.match(parts[0]) if len(parts) == 3 and parts[1] == "charts" else None
    if not m:
        return None
    chart = f"charts/{parts[2]}"
    for name, near in (("signals.csv", False), ("near_misses.csv", True)):
        f = scans / parts[0] / name
        if f.is_file():
            for r in _rows(f, m.group(1)):
                if r["chart"] == chart:
                    return dict(scan=parts[0], symbol=r["ticker"], setup=r["setup"], near=near)
    return None


@router.get("/{path:path}")
def report_file(path: str, raw: bool = False) -> Response:
    """A report file. Chart pages open as Charting Lab's own chart and trade summary (raw=1: the scanner's page)."""
    root = scanner_dir()
    if root is None:
        raise HTTPException(404, "SCANNER_DIR is not set")
    scans = scans_dir(root).resolve()
    if not raw and (sig := chart_signal(scans, path)):
        q = dict(scan=sig["scan"], symbol=sig["symbol"], setup=sig["setup"]) | ({"near": "1"} if sig["near"] else {})
        return RedirectResponse("/?" + urlencode(q), status_code=302)
    rel = path or "index.html"
    f = (scans / rel).resolve()
    if scans not in f.parents and f != scans:
        raise HTTPException(404, "outside the scans folder")
    if f.is_file():
        data, ctype = f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    elif not path or path.endswith("/") or path == "index.html":
        data, ctype = _scanner_get(path)      # the scanner's home page is built by its server
    else:
        raise HTTPException(404, "no such report file")
    name = rel.lower()
    if name.endswith(".html") or "text/html" in ctype:
        text = neutral_html(restyle_js(data.decode("utf-8", "replace")))   # page text without buy/sell words
        return Response(restyle_html(text), media_type="text/html; charset=utf-8", headers={"cache-control": "no-cache"})
    if name.endswith(".js") and "/_lib/" in "/" + rel.replace("\\", "/"):
        return Response(restyle_js(data.decode("utf-8", "replace")), media_type="text/javascript",
                        headers={"cache-control": "no-cache"})
    return Response(data, media_type=ctype)
