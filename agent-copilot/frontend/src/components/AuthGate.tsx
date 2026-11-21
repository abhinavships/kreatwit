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
  if (!me.member) return <Onboarding me={me} onDone={reload} />;
  const account: Account = { email: me.email ?? "", member: me.member, onSignOut: leave };
  return <Shell account={account} />;
}

type Path = "solo" | "team" | "join";

function Onboarding({ me, onDone }: { me: Me; onDone: () => void }) {
  const [path, setPath] = useState<Path>("solo");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const post = async (method: string, url: string, body?: unknown) => {
    setBusy(true); setErr(null);
    const r = await fetch(`${API_BASE}${url}`, {
      method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    setBusy(false);
    if (r?.ok) return onDone();
    const j = (await r?.json().catch(() => ({}))) as { detail?: unknown } | undefined;
    setErr(typeof j?.detail === "string" ? j.detail : "Something went wrong. Check the details and try again.");
  };
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const name = String(f.get("name") ?? "").trim();
    if (path === "join") return post("POST", "/api/org/join", { org_id: String(f.get("org_id") ?? "").trim(), your_name: name });
    return post("POST", "/api/org", {
      name: path === "solo" ? `${name}'s workspace` : f.get("org"), your_name: name, title: f.get("title") ?? "",
      sample: f.get("sample") === "on",
    });
  };
  const field = "mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm";
  const tab = (k: Path, label: string) => (
    <button type="button" role="tab" aria-selected={path === k} onClick={() => { setPath(k); setErr(null); }}
      className={`flex-1 rounded-md px-2 py-1.5 text-sm ${path === k ? "bg-panel font-semibold shadow-sm" : "text-muted hover:text-fg"}`}>{label}</button>
  );

  if (me.request) return (
    <Centered>
      <div className="w-full max-w-md space-y-3 rounded-xl border border-line bg-panel p-6">
        <h1 className="text-lg font-semibold">Waiting for approval</h1>
        <p className="text-sm text-muted">You asked to join <strong className="text-fg">{me.request.org_name}</strong>. An admin there will approve you
          with a role; refresh this page after that.</p>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onDone} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg">Check again</button>
          <button type="button" disabled={busy} onClick={() => post("DELETE", "/api/org/join")} className="rounded-lg border border-line px-4 py-2 text-sm">Cancel request</button>
        </div>
        <button type="button" onClick={leave} className="text-xs text-muted underline">Sign out</button>
      </div>
    </Centered>
  );

  return (
    <Centered>
      <div className="w-full max-w-md">
        <form onSubmit={submit} className="space-y-3 rounded-xl border border-line bg-panel p-6">
          <h1 className="text-lg font-semibold">How will you use Kreatwit?</h1>
          <div role="tablist" className="flex gap-1 rounded-lg bg-raised p-1">
            {tab("solo", "Just me")}{tab("team", "New organization")}{tab("join", "Join one")}
          </div>
          <p className="text-sm text-muted">{{
            solo: "A private workspace: upload your own files and ask questions about them. You can invite people later.",
            team: "A shared workspace for your company. Invite colleagues and give each a role: viewer, member, admin or owner.",
            join: "Paste the organization ID an admin gave you (Team & settings shows it). They approve you and choose your role.",
          }[path]}</p>
          {path === "team" && (
            <label className="block text-sm">Organization name
              <input name="org" required minLength={2} maxLength={80} className={field} placeholder="Acme Energy" />
            </label>
          )}
          {path === "join" && (
            <label className="block text-sm">Organization ID
              <input name="org_id" required pattern="[0-9a-fA-F-]{36}" title="36 characters, like 3f2a…-…" className={`${field} font-mono`}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
            </label>
          )}
          <label className="block text-sm">Your name
            <input name="name" required maxLength={80} autoComplete="name" className={field} />
          </label>
          {path === "team" && (
            <label className="block text-sm">Your job title <span className="text-muted">(optional)</span>
              <input name="title" maxLength={80} className={field} placeholder="Production supervisor" />
            </label>
          )}
          {path !== "join" && (
            <label className="flex items-start gap-2 text-sm">
              <input name="sample" type="checkbox" className="mt-1" />
              <span>Add the sample oil-field dataset (200 demo wells) to try questions before uploading. <span className="text-muted">Off: start empty with only your data.</span></span>
            </label>
          )}
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
          <button type="submit" disabled={busy}
            className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-fg hover:opacity-90 disabled:opacity-50">
            {busy ? "Please wait…" : path === "join" ? "Ask to join" : "Start"}
          </button>
          <p className="text-xs text-muted">Invited by email? Sign in with <strong>{me.email}</strong> and you join automatically.</p>
          <button type="button" onClick={leave} className="text-xs text-muted underline">Sign out</button>
        </form>
      </div>
    </Centered>
  );
}
