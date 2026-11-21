"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { authConfig, startServerSession, supabase } from "@/lib/auth";

type Mode = "signin" | "signup" | "forgot" | "recovery";
const TITLES: Record<Mode, string> = {
  signin: "Sign in", signup: "Create your account", forgot: "Reset your password", recovery: "Choose a new password",
};

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("signin");
  const [ready, setReady] = useState(false);
  const [off, setOff] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const enter = async () => {
    const e = await startServerSession();
    if (e) { setErr(e); return; }
    window.location.replace("/app/");
  };

  useEffect(() => {
    // read before the client starts: supabase-js consumes the email link's #fragment on init
    const recovering = window.location.hash.includes("type=recovery");
    const wanted = new URLSearchParams(window.location.search).get("mode");
    if (wanted === "signup") setMode("signup");
    (async () => {
      if (!(await authConfig()).auth) { setOff(true); setReady(true); return; }
      const sb = await supabase();
      const { data } = await sb.auth.getSession();
      if (recovering && data.session) { setMode("recovery"); setReady(true); return; }
      if (data.session) { await enter(); return; } // signed in already, or just confirmed by email link
      setReady(true);
    })().catch(() => { setErr("Could not reach the server."); setReady(true); });
  }, []);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email") ?? "").trim();
    const password = String(f.get("password") ?? "");
    setBusy(true); setErr(null); setNote(null);
    try {
      const sb = await supabase();
      const back = `${window.location.origin}/login/`;
      if (mode === "signin") {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) setErr(error.message === "Email not confirmed" ? "Confirm your email first: check your inbox for the link." : error.message);
        else await enter();
      } else if (mode === "signup") {
        const { data, error } = await sb.auth.signUp({ email, password, options: { emailRedirectTo: back } });
        if (error) setErr(error.message);
        else if (data.session) await enter(); // email confirmation turned off in Supabase
        else setNote(`We sent a confirmation link to ${email}. Open it to finish creating your account.`);
      } else if (mode === "forgot") {
        const { error } = await sb.auth.resetPasswordForEmail(email, { redirectTo: back });
        if (error) setErr(error.message);
        else setNote(`If ${email} has an account, a reset link is on its way.`);
      } else {
        const { error } = await sb.auth.updateUser({ password });
        if (error) setErr(error.message);
        else await enter();
      }
    } catch { setErr("Could not reach the server."); } finally { setBusy(false); }
  };

  const field = "mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm";
  const link = "underline hover:text-fg";
  return (
    <div className="paper grid min-h-screen place-items-center p-4">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-6 flex items-center justify-center gap-2">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-accent-fg">K</span>
          <span className="display text-lg font-bold">Kreatwit</span>
        </Link>
        {!ready ? <p className="text-center text-sm text-muted">Loading…</p> : off ? (
          <div className="rounded-xl border border-line bg-panel p-6 text-sm">
            <p>Sign-in is off on this server (local development).</p>
            <Link href="/app/" className={`mt-3 inline-block font-semibold ${link}`}>Open the app</Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3 rounded-xl border border-line bg-panel p-6">
            <h1 className="text-lg font-semibold">{TITLES[mode]}</h1>
            {mode !== "recovery" && (
              <label className="block text-sm">Email
                <input name="email" type="email" required autoComplete="email" autoFocus className={field} />
              </label>
            )}
            {mode !== "forgot" && (
              <label className="block text-sm">{mode === "recovery" ? "New password" : "Password"}
                <input name="password" type="password" required minLength={mode === "signin" ? 1 : 8}
                  autoComplete={mode === "signin" ? "current-password" : "new-password"} className={field} />
                {mode !== "signin" && <span className="mt-1 block text-xs text-muted">At least 8 characters.</span>}
              </label>
            )}
            {err && <p role="alert" className="text-sm text-bad">{err}</p>}
            {note && <p role="status" className="text-sm text-ok">{note}</p>}
            <button type="submit" disabled={busy}
              className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-fg hover:opacity-90 disabled:opacity-50">
              {busy ? "Please wait…" : TITLES[mode]}
            </button>
            <div className="space-y-1 pt-1 text-center text-sm text-muted">
              {mode === "signin" && <>
                <p>New here? <button type="button" className={link} onClick={() => { setMode("signup"); setErr(null); setNote(null); }}>Create an account</button></p>
                <p><button type="button" className={link} onClick={() => { setMode("forgot"); setErr(null); setNote(null); }}>Forgot password?</button></p>
              </>}
              {(mode === "signup" || mode === "forgot") &&
                <p>Have an account? <button type="button" className={link} onClick={() => { setMode("signin"); setErr(null); setNote(null); }}>Sign in</button></p>}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
