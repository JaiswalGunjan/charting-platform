"""Backend for the end-to-end tests: a fresh SQLite database seeded with deterministic synthetic data,
served on E2E_API_PORT (default 8010). Never touches the real database, the owner's .env settings or the real
SwingScanner: a fake scanner folder with one saved scan is used, and SCANNER_URL points at a closed port."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

backend = Path(__file__).resolve().parents[3] / "backend"
tmp = Path(tempfile.gettempdir()) / "charting-e2e"
shutil.rmtree(tmp, ignore_errors=True)
tmp.mkdir(parents=True)

scanner = tmp / "SwingScanner"
day = scanner / "scans" / "NSE_daily_2026-11-23"
day.mkdir(parents=True)
(scanner / "swingbt_config.ini").write_text("[app]\nscans = scans\n")
COLS = "date,symbol,setup,valid,close,stop,stop_pct,stop_note,score,stage,phase,base_len,reject,weak,notes,rank,status,shares,value,chart\n"
(day / "signals.csv").write_text(
    COLS + "2026-11-23,TCS,BBR,True,2400,2328,3.0,below the low,9.8,2,base,6,,,"
           "Bad break recovery: reclaimed the SMA50,1,would buy,10,24000,charts/TCS_BBR.html\n")
(day / "near_misses.csv").write_text(
    COLS + "2026-11-23,INFY,VCP,False,1500,1450,3.3,below the low,9.1,2,base,20,"
           "S8-R003: no ATR contraction,,VCP almost,,,0,0,\n")
(day / "market.json").write_text('{"valid_today": 1, "near_today": 1, "market_row": {"regime": "weak_bear", "risk_mult": 0.5}}')

os.environ.update(
    DATABASE_URL=f"sqlite:///{(tmp / 'e2e.db').as_posix()}",
    DATA_SOURCE="synthetic",            # overrides DATA_SOURCE=eod from the owner's .env
    REDIS_URL="",
    LIVE_ENABLED="true",
    ANTHROPIC_API_KEY="",
    SCANNER_DIR=str(scanner),
    SCREENS_DIR=str(tmp / "screens"),   # never overwrite the owner's saved "patterns today" screens
    SCANNER_URL="http://127.0.0.1:9",   # nothing listens there: the scanner reads as offline
)
sys.path.insert(0, str(backend))
os.chdir(backend)

from app import cli  # noqa: E402  (settings must see the environment above)

cli.main(["seed", "--minute-days", "4", "--daily-days", "900"])

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("E2E_API_PORT", "8010")), log_level="warning")
