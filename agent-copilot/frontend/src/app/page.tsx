import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Kreatwit",
  description: "Aletheia, the Kreatwit copilot: ask your company's data, and get only answers it can prove.",
};

const STEPS = [
  { n: "01", t: "Upload", d: "CSV, Excel, JSON, Markdown, PDF and site photos. Tables become queryable, documents become searchable, photos are described." },
  { n: "02", t: "Ask", d: "Plain questions: which assets are down, what a spill cost, which inspections are overdue. Aletheia picks the query and the chart." },
  { n: "03", t: "Check", d: "Every number is re-run against the result it came from. A mismatch is sent back to be fixed; if it still fails, you get no answer rather than a wrong one." },
];

const TRUST = [
  { t: "Claims, not prose", d: "Each figure in an answer is bound to a column and row in a query result, and re-executed before you see it." },
  { t: "Sources on every figure", d: "Open the records behind a number: the inspection, the report, the manual section it was checked against." },
  { t: "Disagreements surfaced", d: "When two records conflict, the answer says so instead of quietly picking one." },
  { t: "Corrections you can undo", d: "Fix a record in chat. The original is kept, your correction is attributed, and one click reverts it." },
];

export default function Landing() {
  const btn = "inline-flex items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold transition";
  return (
    <div className="paper min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-4">
        <Link href="/" className="flex items-center gap-2">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-accent-fg">K</span>
          <span className="display text-lg font-bold">Kreatwit</span>
        </Link>
        <nav className="flex items-center gap-1 text-sm sm:gap-3">
          <a href="#how" className="hidden rounded-md px-2 py-1 text-muted hover:text-fg sm:inline">How it works</a>
          <a href="#privacy" className="hidden rounded-md px-2 py-1 text-muted hover:text-fg sm:inline">Privacy</a>
          <Link href="/login/" className="rounded-md px-2 py-1 font-medium hover:underline">Sign in</Link>
          <Link href="/login/?mode=signup" className={`${btn} bg-accent px-3 py-1.5 text-accent-fg hover:opacity-90`}>Create account</Link>
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4">
        <section className="grid items-center gap-10 py-12 sm:py-20 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <p className="label">Aletheia · the Kreatwit copilot</p>
            <h1 className="display mt-4 text-5xl font-bold leading-[1.02] sm:text-6xl">
              Ask your company&apos;s data.<br />Get only answers it can <span className="hl">prove</span>.
            </h1>
            <p className="mt-6 max-w-xl text-lg text-muted">
              Upload your records and documents. Aletheia answers in numbers computed from them, cites the rows behind every
              figure, and tells you when your sources disagree. If it cannot prove an answer, it does not give one.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/login/?mode=signup" className={`${btn} bg-accent text-accent-fg hover:opacity-90`}>Create a free account</Link>
              <Link href="/login/" className={`${btn} border border-line bg-panel hover:border-accent`}>Sign in</Link>
            </div>
            <p className="mt-4 text-sm text-muted">Free during early access: 40 questions and 20 uploads a day per account.</p>
          </div>

          <figure aria-label="Example answer" className="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div className="label flex justify-between border-b border-line pb-2"><span>Answer</span><span>verified · 0 retries</span></div>
            <p className="mt-4 text-[15px] leading-relaxed">
              <span className="font-semibold">15 wells</span> are not producing as of 17 Oct. Five have open repair records;
              each figure below is checked against the query that produced it.
            </p>
            <div className="mt-4 space-y-2 font-mono text-[12px]">
              <div className="flex justify-between gap-2 rounded-md border border-line bg-raised px-3 py-2"><span>claim: 15</span><span className="text-ok">matches r1.count</span></div>
              <div className="flex justify-between gap-2 rounded-md border border-line bg-raised px-3 py-2"><span>source: MNT-0115-037</span><span className="text-muted">repair record</span></div>
              <div className="flex justify-between gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2"><span>conflict: status vs inspection</span><span className="text-warn">disclosed</span></div>
            </div>
            <figcaption className="mt-3 text-xs text-muted">Illustration based on the sample dataset every account starts with.</figcaption>
          </figure>
        </section>

        <section className="border-t border-line py-14">
          <p className="label">The name</p>
          <div className="mt-3 grid gap-6 lg:grid-cols-[1fr_2fr]">
            <h2 className="display text-3xl font-bold">Aletheia <span className="font-normal text-muted">ἀλήθεια</span></h2>
            <p className="text-lg text-muted">
              Greek for truth, and literally <em>un-concealment</em>: bringing what is hidden into view. That is the job here.
              The answer to most operational questions is already in your records; it is just buried across tables, reports
              and manuals that nobody has time to cross-check.
            </p>
          </div>
        </section>

        <section id="how" className="border-t border-line py-14">
          <p className="label">How it works</p>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.n} className="rounded-xl border border-line bg-panel p-5">
                <div className="font-mono text-sm text-muted">{s.n}</div>
                <h3 className="display mt-2 text-xl font-bold">{s.t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.d}</p>
              </div>
            ))}
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {TRUST.map((x) => (
              <div key={x.t} className="rounded-xl border border-line p-5">
                <h3 className="font-semibold">{x.t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">{x.d}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="privacy" className="border-t border-line py-14">
          <p className="label">Your data</p>
          <div className="mt-3 grid gap-6 lg:grid-cols-[1fr_2fr]">
            <h2 className="display text-3xl font-bold">Your workspace is yours alone.</h2>
            <div className="space-y-3 text-muted">
              <p>Every account gets its own database. What you upload, ask and correct is stored there and nowhere else, and the
                copilot working for you cannot open another account&apos;s files.</p>
              <p>Each workspace starts with a sample oil-field dataset (200 wells, about 40,000 inspections, repair reports and
                operating manuals) so you can try questions before uploading anything.</p>
              <p>Kreatwit is in early access. Do not upload regulated or highly sensitive data yet.</p>
            </div>
          </div>
        </section>

        <section className="border-t border-line py-16 text-center">
          <h2 className="display text-4xl font-bold">See what your data can prove.</h2>
          <Link href="/login/?mode=signup" className={`${btn} mt-6 bg-accent text-accent-fg hover:opacity-90`}>Create a free account</Link>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-6 text-sm text-muted">
          <span>Kreatwit · Aletheia copilot</span>
          <a href="https://github.com/abhinavships/kreatwit" className="hover:text-fg">Source on GitHub</a>
        </div>
      </footer>
    </div>
  );
}
