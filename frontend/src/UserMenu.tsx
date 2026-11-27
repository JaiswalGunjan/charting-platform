import { useEffect, useRef, useState } from "react";
import { me, signOut } from "./auth";

/** The signed-in user in the top bar: picture (or initial), and a menu with their email, Users (admins), Sign out. */
export default function UserMenu() {
  const user = me();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  if (!user) return null;
  const initial = (user.given_name || user.name || user.email || "?").slice(0, 1).toUpperCase();
  return (
    <div className="user-menu" ref={box}>
      <button className="user-btn" aria-label="Account" title={`${user.name} (${user.email})`} onClick={() => setOpen((o) => !o)}>
        {user.picture ? <img src={user.picture} alt="" referrerPolicy="no-referrer" /> : <span className="user-initial">{initial}</span>}
      </button>
      {open && (
        <div className="menu user-dropdown" role="menu">
          <div className="user-who">
            <b>{user.name}</b>
            <span className="muted small">{user.email}</span>
            {user.provider === "local" && <span className="muted small">local mode (no Google sign-in)</span>}
          </div>
          {user.is_admin && <a className="menu-item" role="menuitem" href="/?page=admin">Admin</a>}
          {user.is_admin && <a className="menu-item" role="menuitem" href="/?page=users">Users</a>}
          {user.provider !== "local" && (
            <button className="menu-item" role="menuitem" onClick={() => void signOut()}>Sign out</button>
          )}
        </div>
      )}
    </div>
  );
}
