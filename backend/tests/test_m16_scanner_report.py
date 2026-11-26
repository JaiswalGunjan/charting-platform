"""The scanner's report served in Charting Lab's theme: files read (never written) from the scans folder, theme and
script added, the report's root paths pointed at this route, its /api calls passed to the scanner's server."""
from app.adapters.swingscanner.report import restyle_html, restyle_js
from tests.test_m14_scanner import scan_root  # noqa: F401  (fixture)

REPORT = "/scanner/report/NSE_daily_2026-11-23"
PAGE = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>x</title>'
        '<link rel="stylesheet" href="../../_lib/style.css">'
        '<script src="../../_lib/lightweight-charts.standalone.production.js"></script></head>'
        '<body><a href="/">home</a><script src="../../_lib/render.js"></script></body></html>')


def write_report(root):
    scans = root / "my_scans"
    (scans / "_lib").mkdir(exist_ok=True)
    (scans / "_lib" / "scan_ui.js").write_text(
        'fetch("/api/portfolio"); const j = api("/api/trade", {}); a.href = "/";\n'
        'location.href = "/" + s.job.scan_folder + "/index.html";', encoding="utf-8")
    (scans / "_lib" / "style.css").write_text("body { color: red }", encoding="utf-8")
    day = scans / "NSE_daily_2026-11-23"
    (day / "charts").mkdir(exist_ok=True)
    (day / "index.html").write_text(PAGE.replace("../../", "../"), encoding="utf-8")
    (day / "charts" / "MARICO_BBR_2026-11-23.html").write_text(PAGE, encoding="utf-8")
    return scans


def test_report_page_is_themed_and_untouched_on_disk(client, scan_root):  # noqa: F811
    root, _ = scan_root
    scans = write_report(root)
    before = (scans / "NSE_daily_2026-11-23" / "index.html").read_text(encoding="utf-8")
    r = client.get(f"{REPORT}/index.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert '<style id="charting-lab-theme">' in html and "html[data-theme=\"dark\"]" in html
    assert html.index("charting-lab-theme") > html.index("_lib/style.css")       # ours comes last, so it wins
    assert "window.__SCAN_BASE" in html and html.index("__clWrap = wrap") < html.index("lightweight-charts.standalone")
    assert (scans / "NSE_daily_2026-11-23" / "index.html").read_text(encoding="utf-8") == before   # never written


def test_chart_page_wraps_the_chart_library_before_the_page_script(client, scan_root):  # noqa: F811
    root, _ = scan_root
    write_report(root)
    html = client.get(f"{REPORT}/charts/MARICO_BBR_2026-11-23.html", params={"raw": 1}).text
    lib = html.index("lightweight-charts.standalone.production.js")
    call = html.index("window.__clWrap && window.__clWrap();")
    assert lib < call < html.index("render.js")


def test_report_scripts_point_at_this_route(client, scan_root):  # noqa: F811
    root, _ = scan_root
    write_report(root)
    js = client.get("/scanner/report/_lib/scan_ui.js").text
    assert 'fetch(window.__SCAN_BASE + "api/portfolio")' in js and 'api(window.__SCAN_BASE + "api/trade"' in js
    assert "a.href = window.__SCAN_BASE;" in js and "location.href = window.__SCAN_BASE + s.job.scan_folder" in js
    assert '"/api/' not in js
    assert client.get("/scanner/report/_lib/style.css").text == "body { color: red }"   # other files as they are


def test_paths_outside_the_scans_folder_are_refused(client, scan_root):  # noqa: F811
    root, _ = scan_root
    write_report(root)
    (root / "secret.txt").write_text("no")
    assert client.get("/scanner/report/..%2Fsecret.txt").status_code == 404
    assert client.get("/scanner/report/NSE_daily_2026-11-23/..%2F..%2Fsecret.txt").status_code == 404
    assert client.get(f"{REPORT}/missing.html").status_code == 404


def test_actions_and_home_need_the_scanner_running(client, scan_root):  # noqa: F811
    root, _ = scan_root
    write_report(root)
    r = client.post("/scanner/report/api/watch", json={"action": "add", "symbol": "MARICO"})
    assert r.status_code == 502 and "not running" in r.json()["detail"]
    assert client.get("/scanner/report/").status_code == 404                  # home page is built by its server


def test_scan_links_use_the_themed_route(client, scan_root):  # noqa: F811
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    assert d["report_href"] == f"{REPORT}/index.html"
    assert d["signals"][0]["chart_href"] == f"{REPORT}/charts/MARICO_BBR_2026-11-23.html"


def test_restyle_helpers():
    assert restyle_html("<p>no head</p>").endswith("<p>no head</p>") and "charting-lab-theme" in restyle_html("x")
    plain = restyle_html("<html><head><title>t</title></head><body></body></html>")
    assert plain.index("__SCAN_BASE") < plain.index("charting-lab-theme") < plain.index("</head>")
    assert restyle_js("color: rgba(60,60,60,0.55)") == "color: rgba(128,134,150,0.55)"


def test_chart_pages_open_in_charting_lab(client, scan_root):  # noqa: F811
    root, _ = scan_root
    write_report(root)
    r = client.get(f"{REPORT}/charts/MARICO_BBR_2026-11-23.html", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/?scan=NSE_daily_2026-11-23&symbol=MARICO&setup=BBR&scanner=swingscanner"
    # a chart page that is not a signal of the scan is served as it is
    assert client.get(f"{REPORT}/charts/OTHER_PP_2026-11-23.html", follow_redirects=False).status_code == 404
