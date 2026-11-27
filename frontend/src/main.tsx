import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import AdminPage from "./AdminPage";
import App from "./App";
import { fetchMe, safeNext, setMe } from "./auth";
import { loadMarkets } from "./markets";
import ScreenerPage from "./ScreenerPage";
import SetupPage from "./SetupPage";
import SignInPage from "./SignInPage";
import UsersPage from "./UsersPage";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);
const q = new URLSearchParams(window.location.search);

// Nobody sees any page (chart, screener, scanner, a stock opened by its link ...) before signing in: the sign-in
// check comes first, and a signed-out visitor gets the sign-in page, which brings them back to this very link.
async function start() {
  const user = await fetchMe().catch(() => null);
  if (!user) {
    // ?next= comes from a page that needed sign-in (the scanner report); else come back to this link itself
    const next = q.get("next") ?? window.location.pathname + window.location.search;
    root.render(<StrictMode><SignInPage next={next} error={q.get("signin_error")} /></StrictMode>);
    return;
  }
  setMe(user);
  const next = q.get("next");
  if (next) {                                        // signed in now: on to the page that sent us here
    window.location.replace(safeNext(next));
    return;
  }
  const page = q.get("page");
  // admin pages: not for other users, whatever link they use (nothing of them loads; the API refuses them too)
  if ((page === "admin" || page === "users") && !user.is_admin) {
    root.render(<StrictMode><NotAllowed /></StrictMode>);
    return;
  }
  await loadMarkets();                               // the market registry (time zones, currencies): every page uses it
  root.render(
    <StrictMode>
      {page === "screener" ? <ScreenerPage /> : page === "setups" ? <SetupPage /> : page === "users" ? <UsersPage />
        : page === "admin" ? <AdminPage /> : <App />}
    </StrictMode>,
  );
}

function NotAllowed() {
  return (
    <div className="signin-page">
      <div className="signin-card" role="alert">
        <h2>Not available</h2>
        <p className="muted">This page is for admins.</p>
        <a href="/">Back to the chart</a>
      </div>
    </div>
  );
}

void start();
