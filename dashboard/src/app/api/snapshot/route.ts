import { NextResponse } from "next/server";

import { getDashboardSnapshot } from "@/lib/data";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const startedAt = Date.now();
  try {
    const snapshot = await getDashboardSnapshot();
    console.info(
      JSON.stringify({
        event: "dashboard.snapshot.served",
        generated_at: snapshot.generatedAt,
        run_count: snapshot.metrics.totalRuns,
        duration_ms: Date.now() - startedAt,
      }),
    );
    return NextResponse.json(snapshot, {
      headers: {
        "Cache-Control": "private, no-store, max-age=0",
      },
    });
  } catch (error) {
    console.error(
      JSON.stringify({
        event: "dashboard.snapshot.failed",
        error_type: error instanceof Error ? error.name : "UnknownError",
        duration_ms: Date.now() - startedAt,
      }),
    );
    return NextResponse.json(
      { detail: "Live incident data is temporarily unavailable." },
      {
        status: 503,
        headers: {
          "Cache-Control": "private, no-store, max-age=0",
        },
      },
    );
  }
}
