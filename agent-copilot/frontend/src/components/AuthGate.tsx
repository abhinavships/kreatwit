"use client";
import { useEffect, useState, type FormEvent } from "react";
import { API_BASE, MOCK } from "@/lib/api";
import { Shell } from "@/components/Shell";

interface Me { auth: boolean; user_id?: string; email?: string }

/** Asks the server who is signed in. Sign-in off (local dev, mock) renders the app as before, with the user picker. */
export function AuthGate() {
  const [me, setMe] = useState<Me | null | "anon">(MOCK ? { auth: false } : null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const accept = (m: Me) => {
    // Shell and the board read the acting user from here on mount; the server ignores it and uses the session anyway
    if (m.auth && m.user_id) { try { localStorage.setItem("wellops.user", m.user_id); } catch { /* ignore */ } }
    setMe(m);
  };
  useEffect(() => {
    if (MOCK) return;
    fetch(`${API_BASE}/api/auth/me`).then((r) => (r.ok ? r.json().then(accept) : setMe("anon")))
      .catch(() => setMe({ auth: false })); // backend offline: Shell shows its own load error
  }, []);

  const signIn = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: f.get("email"), password: f.get("password") }),
      });
      if (r.ok) accept((await r.json()) as Me);
      else setErr(r.status === 429 ? "Too many attempts. Try again in 15 minutes." : "Wrong email or password.");
    } catch { setErr("Could not reach the server."); } finally { setBusy(false); }
  };
  const signOut = async () => {
    await fetch(`${API_BASE}/api/auth/logout`, { method: "POST" }).catch(() => {});
    setMe("anon");
  };

  if (me === null) return null;
  if (me !== "anon") return <Shell account={me.auth ? { email: me.email ?? "", onSignOut: signOut } : undefined} />;
  const field = "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm";
  return (
    <main className="grid min-h-screen place-items-center p-4">
      <form onSubmit={signIn} className="w-full max-w-sm space-y-3 rounded-xl border border-line bg-panel p-6">
        <h1 className="text-lg font-semibold">Sign in to WellOps Copilot</h1>
        <label className="block text-sm">Email
          <input name="email" type="email" required autoComplete="username" autoFocus className={`mt-1 ${field}`} />
        </label>
        <label className="block text-sm">Password
          <input name="password" type="password" required autoComplete="current-password" className={`mt-1 ${field}`} />
        </label>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <button type="submit" disabled={busy} className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-fg hover:opacity-90 disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
