"use client";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { API_BASE } from "@/lib/api";
import type { Role } from "@/lib/auth";
import { Centered, leave, useMe } from "@/components/AuthGate";

interface OrgMember { user_id: string; email: string; name: string; title: string; role: Role; joined_at: string }
interface Invite { email: string; role: Role; invited_by: string; created_at: string }
interface JoinRequest { email: string; name: string; created_at: string }
interface Org { org: { org_id: string; name: string }; me: { user_id: string; role: Role }; members: OrgMember[]; invites: Invite[]; requests: JoinRequest[] }

const ROLES: Role[] = ["viewer", "member", "admin", "owner"];
const RANK = (r: Role) => ROLES.indexOf(r);
const ROLE_HELP: Record<Role, string> = {
  viewer: "Ask questions and see the organization's data.",
  member: "Also upload data and correct records.",
  admin: "Also invite, remove and change members.",
  owner: "Also make other owners.",
};

async function call(method: string, path: string, body?: unknown): Promise<string | null> {
  const r = await fetch(`${API_BASE}/api/org${path}`, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  }).catch(() => null);
  if (r?.ok) return null;
  const j = (await r?.json().catch(() => ({}))) as { detail?: unknown } | undefined;
  return typeof j?.detail === "string" ? j.detail : "Request failed.";
}

export default function OrgPage() {
  const { me } = useMe();
  const [org, setOrg] = useState<Org | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch(`${API_BASE}/api/org`).then(async (r) => {
      if (r.ok) setOrg((await r.json()) as Org);
      else window.location.replace("/app/"); // no org yet (or sign-in off): the app handles it
    }).catch(() => setErr("Could not reach the server."));
  }, []);
  useEffect(() => { if (me?.member) load(); else if (me) window.location.replace("/app/"); }, [me, load]);

  const run = async (p: Promise<string | null>, ok?: string) => {
    setErr(null); setNote(null);
    const e = await p;
    if (e) setErr(e); else { if (ok) setNote(ok); load(); }
  };

  if (!org || !me?.member) return <Centered><p className="text-sm text-muted">Loading…</p></Centered>;
  const mine = org.me.role;
  const admin = RANK(mine) >= RANK("admin");
  const canChange = (m: OrgMember) => admin && m.user_id !== org.me.user_id && (m.role !== "owner" || mine === "owner");
  const grantable = ROLES.filter((r) => r !== "owner" || mine === "owner");
  const link = typeof window !== "undefined" ? `${window.location.origin}/login/?mode=signup` : "/login/?mode=signup";

  const invite = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const email = String(f.get("email"));
    run(call("POST", "/invites", { email, role: f.get("role") }),
      `Invited ${email}. Send them ${link}: when they sign up with that email they join ${org.org.name}.`).then(() => form.reset());
  };
  const profile = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    run(call("PATCH", "/me", { name: f.get("name"), title: f.get("title") }), "Profile saved.");
  };
  const rename = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    run(call("PATCH", "", { name: new FormData(e.currentTarget).get("org") }), "Organization renamed.");
  };
  const meRow = org.members.find((m) => m.user_id === org.me.user_id);
  const field = "rounded-lg border border-line bg-panel px-3 py-2 text-sm";
  const card = "rounded-xl border border-line bg-panel p-5";

  return (
    <div className="paper min-h-screen">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <Link href="/app/" className="text-sm text-muted underline hover:text-fg">← Back to Aletheia</Link>
            <h1 className="display mt-2 text-3xl font-bold">{org.org.name}</h1>
            <p className="text-sm text-muted">You are {mine}. {ROLE_HELP[mine]}</p>
          </div>
          <button type="button" onClick={leave} className="text-sm text-muted underline hover:text-fg">Sign out</button>
        </div>

        {err && <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{err}</p>}
        {note && <p role="status" className="rounded-lg border border-ok/40 bg-ok/10 px-3 py-2 text-sm text-ok">{note}</p>}

        <section className={card} aria-labelledby="members-h">
          <h2 id="members-h" className="font-semibold">Members ({org.members.length})</h2>
          <ul className="mt-3 divide-y divide-line">
            {org.members.map((m) => (
              <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{m.name}{m.user_id === org.me.user_id && <span className="text-muted"> (you)</span>}</div>
                  <div className="truncate text-xs text-muted">{m.title ? `${m.title} · ` : ""}{m.email}</div>
                </div>
                <div className="flex items-center gap-2">
                  {canChange(m) ? (
                    <select aria-label={`Role for ${m.name}`} value={m.role} className={`${field} py-1`}
                      onChange={(e) => run(call("PATCH", `/members/${m.user_id}`, { role: e.target.value }))}>
                      {grantable.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  ) : <span className="rounded-full border border-line px-2 py-0.5 text-xs">{m.role}</span>}
                  {canChange(m) && (
                    <button type="button" className="text-xs text-bad underline"
                      onClick={() => run(call("DELETE", `/members/${m.user_id}`), `${m.name} no longer has access. What they uploaded stays.`)}>
                      Remove
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>

        {admin && (
          <section className={card} aria-labelledby="id-h">
            <h2 id="id-h" className="font-semibold">Organization ID</h2>
            <p className="mt-1 text-sm text-muted">People who sign up can ask to join with this ID. You approve each request and pick their role.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <code className="min-w-0 flex-1 truncate rounded-lg border border-line bg-raised px-3 py-2 text-sm">{org.org.org_id}</code>
              <button type="button" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:border-accent"
                onClick={() => navigator.clipboard?.writeText(org.org.org_id).then(() => setNote("Organization ID copied."))}>Copy</button>
            </div>
            {org.requests.length > 0 && (
              <>
                <h3 className="mt-4 text-sm font-semibold">Requests to join ({org.requests.length})</h3>
                <ul className="mt-1 divide-y divide-line">
                  {org.requests.map((q) => (
                    <li key={q.email} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                      <span className="min-w-0 truncate">{q.name} <span className="text-muted">· {q.email}</span></span>
                      <span className="flex items-center gap-2">
                        <select aria-label={`Role for ${q.name}`} defaultValue="viewer" id={`role-${q.email}`} className={`${field} py-1`}>
                          {grantable.map((r) => <option key={r} value={r}>{r}</option>)}
                        </select>
                        <button type="button" className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg"
                          onClick={() => run(call("POST", `/requests/${encodeURIComponent(q.email)}`,
                            { role: (document.getElementById(`role-${q.email}`) as HTMLSelectElement).value }), `${q.name} joined.`)}>Approve</button>
                        <button type="button" className="text-xs underline"
                          onClick={() => run(call("DELETE", `/requests/${encodeURIComponent(q.email)}`))}>Decline</button>
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}

        {admin && (
          <section className={card} aria-labelledby="invite-h">
            <h2 id="invite-h" className="font-semibold">Invite people</h2>
            <p className="mt-1 text-sm text-muted">They join when they sign up or sign in with the invited email.</p>
            <form onSubmit={invite} className="mt-3 flex flex-wrap gap-2">
              <input name="email" type="email" required placeholder="name@company.com" aria-label="Email" className={`${field} min-w-0 flex-1`} />
              <select name="role" defaultValue="member" aria-label="Role" className={field}>
                {grantable.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
              <button type="submit" className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:opacity-90">Invite</button>
            </form>
            <ul className="mt-3 space-y-1 text-xs text-muted">
              {ROLES.map((r) => <li key={r}><strong className="text-fg">{r}</strong>: {ROLE_HELP[r]}</li>)}
            </ul>
            {org.invites.length > 0 && (
              <>
                <h3 className="mt-4 text-sm font-semibold">Pending</h3>
                <ul className="mt-1 divide-y divide-line">
                  {org.invites.map((i) => (
                    <li key={i.email} className="flex items-center justify-between gap-2 py-2 text-sm">
                      <span className="truncate">{i.email} <span className="text-muted">· {i.role}</span></span>
                      <button type="button" className="text-xs underline"
                        onClick={() => run(call("DELETE", `/invites/${encodeURIComponent(i.email)}`))}>Revoke</button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}

        <section className={card} aria-labelledby="profile-h">
          <h2 id="profile-h" className="font-semibold">Your profile</h2>
          <p className="mt-1 text-sm text-muted">Corrections and uploads are attributed to this name.</p>
          <form onSubmit={profile} className="mt-3 flex flex-wrap gap-2">
            <input name="name" required maxLength={80} defaultValue={meRow?.name} aria-label="Name" className={`${field} min-w-0 flex-1`} />
            <input name="title" maxLength={80} defaultValue={meRow?.title} placeholder="Job title" aria-label="Job title" className={`${field} min-w-0 flex-1`} />
            <button type="submit" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:border-accent">Save</button>
          </form>
        </section>

        {admin && (
          <section className={card} aria-labelledby="org-h">
            <h2 id="org-h" className="font-semibold">Organization</h2>
            <form onSubmit={rename} className="mt-3 flex flex-wrap gap-2">
              <input name="org" required minLength={2} maxLength={80} defaultValue={org.org.name} aria-label="Organization name" className={`${field} min-w-0 flex-1`} />
              <button type="submit" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:border-accent">Rename</button>
            </form>
          </section>
        )}

        {mine !== "owner" && (
          <button type="button" className="text-sm text-bad underline"
            onClick={() => run(call("DELETE", `/members/${org.me.user_id}`)).then(leave)}>Leave {org.org.name}</button>
        )}
      </div>
    </div>
  );
}
