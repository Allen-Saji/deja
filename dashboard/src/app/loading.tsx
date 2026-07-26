export default function Loading() {
  return (
    <main className="loading-shell" aria-busy="true" aria-label="Loading incident memory">
      <div className="loading-mark">DEJA / MEMORY OPERATIONS</div>
      <div className="loading-line" />
      <p>Reading the durable incident ledger...</p>
    </main>
  );
}
