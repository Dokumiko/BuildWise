import { proxyToBackend } from "../../../../../../lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ datasetVersion: string }> },
): Promise<Response> {
  const { datasetVersion } = await context.params;
  return proxyToBackend(`/api/v1/catalog-datasets/${encodeURIComponent(datasetVersion)}/components`);
}