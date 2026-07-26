"use client";

import { RotateCcw } from "lucide-react";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="error-shell">
      <p className="eyebrow">DEJA / MEMORY OPERATIONS</p>
      <div className="error-code">503</div>
      <h1>The incident ledger did not answer.</h1>
      <p>
        The dashboard remains read-only. No backend action was attempted and no incident state
        was changed.
      </p>
      <button type="button" onClick={reset} className="primary-button">
        <RotateCcw size={16} aria-hidden="true" />
        Retry connection
      </button>
    </main>
  );
}
