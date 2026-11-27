// Who is signed in. main.tsx asks GET /api/auth/me before any page renders: no user, no page (the sign-in page
// instead), whatever link was opened. A request answered 401 later (the session ended) also goes to sign-in, and
// comes back to the same page afterwards.

export interface Me {
  id: number;
  email: string;
  name: string;
  given_name: string;
  picture: string;
  phone: string;
  is_admin: boolean;
  provider: "google" | "local";
  auth_mode: "google" | "local";
}

let current: Me | null = null;

export const me = (): Me | null => current;
export const isAdmin = (): boolean => !!current?.is_admin;
export function setMe(m: Me | null): void {
  current = m;
}

/** The page to come back to after signing in: a path on this site only (never another host). */
export function safeNext(next: string | null | undefined): string {
  const t = (next ?? "/").trim();
  if (!t.startsWith("/") || t.startsWith("//") || t.includes("\\")) return "/";
  return t;
}

/** Where this page is, to come back to it: the current path and query, minus the sign-in's own parameters. */
export function hereForNext(loc: { pathname: string; search: string } = window.location): string {
  const q = new URLSearchParams(loc.search);
  q.delete("next");
  q.delete("signin_error");
  const s = q.toString();
  return safeNext(loc.pathname + (s ? `?${s}` : ""));
}

export const signInUrl = (next: string): string => `/api/auth/google/login?next=${encodeURIComponent(safeNext(next))}`;

let leaving = false;
/** The session ended (a 401, or the live connection refused): to the sign-in page, then back here. */
export function signedOut(): void {
  if (leaving) return;
  leaving = true;
  window.location.assign(`/?next=${encodeURIComponent(hereForNext())}`);
}

export async function fetchMe(): Promise<Me | null> {
  const r = await fetch("/api/auth/me");
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(`sign-in check failed: ${r.status}`);
  return (await r.json()) as Me;
}

export async function signOut(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.assign("/");
}
