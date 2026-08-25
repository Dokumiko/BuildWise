import { proxyToBackend } from "../../../../../lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return proxyToBackend("/api/v1/builds/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
}
