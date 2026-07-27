export default function Loading() {
  return (
    <main className="console-state-shell" aria-busy="true" aria-label="Loading incident memory">
      <div className="state-wordmark">
        <span className="wordmark-glyph" aria-hidden="true">
          d
        </span>
        <span>deja</span>
      </div>
      <section className="state-card">
        <p className="state-kicker">
          <span className="live-pulse" />
          Syncing durable memory
        </p>
        <h1>Loading incident memory</h1>
        <p>Reading verified runs, checkpoints, and outcome evidence.</p>
        <div className="state-progress" aria-hidden="true">
          <i />
        </div>
      </section>
    </main>
  );
}
