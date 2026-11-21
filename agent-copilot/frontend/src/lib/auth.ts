/** Sign-in through Supabase. The server's config decides whether sign-in is on (it is off in local dev). */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { API_BASE, MOCK } from "@/lib/api";

interface AuthConfig { auth: boolean; supabase_url: string; supabase_anon_key: string }

let configP: Promise<AuthConfig> | null = null;
let client: SupabaseClient | null = null;

export function authConfig(): Promise<AuthConfig> {
  if (MOCK) return Promise.resolve({ auth: false, supabase_url: "", supabase_anon_key: "" });
  configP ??= fetch(`${API_BASE}/api/auth/config`).then((r) => r.json() as Promise<AuthConfig>);
  return configP;
}

export async function supabase(): Promise<SupabaseClient> {
  if (client) return client;
  const c = await authConfig();
  // implicit flow: email links work even when opened in another browser than the one that signed up
  client = createClient(c.supabase_url, c.supabase_anon_key, { auth: { flowType: "implicit", persistSession: true } });
  return client;
}

/** Hand the Supabase session to our server, which sets its own HttpOnly cookie. Returns an error message or null. */
export async function startServerSession(): Promise<string | null> {
  const { data } = await (await supabase()).auth.getSession();
  if (!data.session) return "not signed in";
  const r = await fetch(`${API_BASE}/api/auth/session`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_token: data.session.access_token }),
  });
  if (r.ok) return null;
  const j = (await r.json().catch(() => ({}))) as { detail?: string };
  return j.detail ?? `sign-in failed (HTTP ${r.status})`;
}

export async function signOut(): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, { method: "POST" }).catch(() => {});
  if ((await authConfig()).auth) await (await supabase()).auth.signOut().catch(() => {});
}
