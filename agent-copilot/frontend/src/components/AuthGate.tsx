"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE, MOCK } from "@/lib/api";
import { authConfig, signOut, startServerSession } from "@/lib/auth";
import { Shell } from "@/components/Shell";

interface Me { auth: boolean; email?: string }

/** The app behind sign-in. Sign-in off (local dev, mock): the app as before. Otherwise no session: go to /login/. */
export function AuthGate() {
  const [me, setMe] = useState<Me | null>(MOCK ? { auth: false } : null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (MOCK) return;
    (async () => {
      const r = await fetch(`${API_BASE}/api/auth/me`);
      if (r.ok) return setMe((await r.json()) as Me);
      if (!(await authConfig()).auth) return setMe({ auth: false });
      // our cookie is gone or expired but Supabase may still hold a session: exchange it again
      const e = await startServerSession();
      if (e === "not signed in") return window.location.replace("/login/");
      if (e) return setErr(e);
      setMe((await (await fetch(`${API_BASE}/api/auth/me`)).json()) as Me);
    })().catch(() => setMe({ auth: false })); // backend offline: Shell shows its own load error
  }, []);

  if (err) return (
    <main className="grid min-h-screen place-items-center p-4 text-center">
      <div><p className="text-bad">{err}</p><Link className="mt-3 inline-block underline" href="/login/">Back to sign in</Link></div>
    </main>
  );
  if (me === null) return null;
  const leave = async () => { await signOut(); window.location.replace("/"); };
  return <Shell account={me.auth ? { email: me.email ?? "", onSignOut: leave } : undefined} />;
}
