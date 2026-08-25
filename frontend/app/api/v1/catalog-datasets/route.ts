import { proxyToBackend } from "../../../../lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return proxyToBackend("/api/v1/catalog-datasets");
}
