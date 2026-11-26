"""Stand-ins for parts that are switched off (e.g. SETUP_SCANNER=none): the product runs, the part's pages are empty."""
from app.ports import ScannerOffline


class NoSetupScanner:
    name = "none"
    title = "No setup scanner"

    def status(self) -> dict:
        return dict(name=self.name, title=self.title, configured=False, online=False, markets=[],
                    msg="No setup scanner is set up (SETUP_SCANNER=none).")

    def scans(self) -> list[dict]:
        return []

    def scan(self, scan_id: str, near: bool = True) -> dict | None:
        return None

    def setups(self) -> dict[str, dict]:
        return {}

    def explain(self, scan_id, ticker, setup, near=False, equity=None, risk_pct=None) -> dict | None:
        return None

    def portfolio(self) -> dict:
        return dict(source="none", watchlist=[], trades=[])

    def run(self, market: str, day: str | None = None) -> dict:
        raise ScannerOffline("No setup scanner is set up.")

    def job(self, since: int = 0) -> dict:
        raise ScannerOffline("No setup scanner is set up.")

    def slim(self) -> tuple[int, int]:
        return 0, 0

    def routers(self) -> list:
        return []
