"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { API_BASE, MOCK } from "@/lib/api";
import { authConfig, signOut, startServerSession, type Account, type Me } from "@/lib/auth";
import { Shell } from "@/components/Shell";

async function loadMe(): Promise<Me | "login" | string> {
  const r = await fetch(`${API_BASE}/api/auth/me`);
  if (r.ok) return (await r.json()) as Me;
  if (!(await authConfig()).auth) return { auth: false };
  // our cookie is gone or expired but Supabase may still hold a session: exchange it again
  const e = await startServerSession();
  if (e === "not signed in") return "login";
  if (e) return e;
  return (await (await fetch(`${API_BASE}/api/auth/me`)).json()) as Me;
}

/** Signed-in state for app pages. Sign-in off (local dev, mock): { auth: false }. No session: goes to /login/. */
export function useMe(): { me: Me | null; err: string | null; reload: () => void } {
  const [me, setMe] = useState<Me | null>(MOCK ? { auth: false } : null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (MOCK) return;
    loadMe().then((m) => {
      if (m === "login") window.location.replace("/login/");
      else if (typeof m === "string") setErr(m);
      else setMe(m);
    }).catch(() => setMe({ auth: false })); // backend offline: Shell shows its own load error
  }, [n]);
  return { me, err, reload: () => setN((x) => x + 1) };
}

export const leave = async () => { await signOut(); window.location.replace("/"); };

export function Centered({ children }: { children: ReactNode }) {
  return <main className="paper grid min-h-screen place-items-center p-4">{children}</main>;
}

/** The app behind sign-in: no org yet → create one; otherwise the app as this member. */
export function AuthGate() {
  const { me, err, reload } = useMe();
  if (err) return (
    <Centered>
      <div className="text-center"><p className="text-bad">{err}</p><Link className="mt-3 inline-block underline" href="/login/">Back to sign in</Link></div>
    </Centered>
  );
  if (me === null) return null;
  if (!me.auth) return <Shell />;
  if (!me.member) return <CreateOrg email={me.email ?? ""} onDone={reload} />;
  const account: Account = { email: me.email ?? "", member: me.member, onSignOut: leave };
  return <Shell account={account} />;
}

function CreateOrg({ email, onDone }: { email: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true); setErr(null);
    const r = await fetch(`${API_BASE}/api/org`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: f.get("org"), your_name: f.get("name"), title: f.get("title") }),
    }).catch(() => null);
    setBusy(false);
    if (r?.ok) return onDone();
    const j = (await r?.json().catch(() => ({}))) as { detail?: unknown } | undefined;
    setErr(typeof j?.detail === "string" ? j.detail : "Could not create the organization.");
  };
  const field = "mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm";
  return (
    <Centered>
      <div className="w-full max-w-md">
        <form onSubmit={submit} className="space-y-3 rounded-xl border border-line bg-panel p-6">
          <h1 className="text-lg font-semibold">Set up your organization</h1>
          <p className="text-sm text-muted">
            Your organization holds your company&apos;s data. Everyone you invite works on the same data, each under their own name and role.
          </p>
          <label className="block text-sm">Organization name
            <input name="org" required minLength={2} maxLength={80} autoFocus className={field} placeholder="Acme Energy" />
          </label>
          <label className="block text-sm">Your name
            <input name="name" required maxLength={80} autoComplete="name" className={field} />
          </label>
          <label className="block text-sm">Your job title <span className="text-muted">(optional)</span>
            <input name="title" maxLength={80} className={field} placeholder="Production supervisor" />
          </label>
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
          <button type="submit" disabled={busy}
            className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-fg hover:opacity-90 disabled:opacity-50">
            {busy ? "Creating…" : "Create organization"}
          </button>
          <p className="text-xs text-muted">
            Joining a colleague&apos;s organization instead? Ask an admin there to invite <strong>{email}</strong>, then sign in again.
          </p>
          <p className="text-xs text-muted">New organizations start with a sample oil-field dataset to try questions on; your uploads are added beside it.</p>
          <button type="button" onClick={leave} className="text-xs text-muted underline">Sign out</button>
        </form>
      </div>
    </Centered>
  );
}
