"use client";

import { RotateCcw } from "lucide-react";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="console-state-shell">
      <div className="state-wordmark">
        <span className="wordmark-glyph" aria-hidden="true">
          d
        </span>
        <span>deja</span>
      </div>
      <section className="state-card error-state">
        <p className="state-kicker">Connection unavailable / 503</p>
        <h1>The incident ledger did not answer.</h1>
        <p>
          The console remains read-only. No backend action was attempted and no incident state
          changed.
        </p>
        <button type="button" onClick={reset} className="state-action">
          <RotateCcw size={15} aria-hidden="true" />
          Retry connection
        </button>
      </section>
    </main>
  );
}
