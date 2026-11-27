import { useEffect, useState } from "react";
import { safeNext, signInUrl } from "./auth";
import Logo from "./Logo";
import { useTheme, type Theme } from "./theme";

function storedTheme(): Theme {
  try {
    return JSON.parse(localStorage.getItem("theme") || '"light"') === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Google's "G" mark, as Google's sign-in branding guidelines ask for on a "Sign in with Google" button. */
function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

/** Shown instead of any page while nobody is signed in; after Google, back to the page that was asked for. */
export default function SignInPage(props: { next: string; error?: string | null }) {
  const [theme] = useState<Theme>(storedTheme);
  useTheme(theme);
  useEffect(() => { document.title = "Sign in · Charting Lab"; }, []);
  const next = safeNext(props.next);
  return (
    <div className="signin-page">
      <div className="signin-card">
        <div className="signin-brand"><Logo size={40} /> <span>Charting Lab</span></div>
        <p className="muted">Charts, pattern screens and setup scans for NSE and US markets.</p>
        {props.error && <div className="signin-error" role="alert">Sign-in did not work: {props.error}</div>}
        <a className="google-btn" href={signInUrl(next)}><GoogleG /> Sign in with Google</a>
        <p className="signin-note small muted">
          Signing in shares your name, email address and profile picture from Google. To keep your account safe and
          to improve the service we record when you sign in and use Charting Lab, your IP address and approximate
          location, and the pages and stocks you open. Records older than a year are deleted.
        </p>
      </div>
    </div>
  );
}
