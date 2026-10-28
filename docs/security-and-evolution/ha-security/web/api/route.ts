import { NextResponse } from "next/server";

import { backendFetchJson } from "@/lib/backend";
import { withDashboardSession } from "@/lib/routeAuth";

export const dynamic = "force-dynamic";

/**
 * Proxy for the shop-activity record.
 *
 * The record lives in /root/authority.db on the API host; the browser must never hold an
 * API key, so this handler carries the session check and the backend does the reading —
 * the same shape as /api/activity.
 */
export async function GET(request: Request) {
  return withDashboardSession(async () => {
    const { searchParams } = new URL(request.url);
    const day = searchParams.get("day");
    const qs = day ? `?day=${encodeURIComponent(day)}` : "";
    try {
      const data = await backendFetchJson<Record<string, unknown>>(
        `/ceo/db/shop-activity${qs}`,
        { timeoutMs: 15000 },
      );
      return NextResponse.json(data);
    } catch {
      return NextResponse.json(
        { error: "the shop record is unreachable right now" },
        { status: 200 },
      );
    }
  });
}
