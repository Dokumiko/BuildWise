import { proxyToBackend } from "../../../../../../../lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ datasetVersion: string }> },
): Promise<Response> {
  const { datasetVersion } = await context.params;
  const query = new URL(request.url).search;
  return proxyToBackend(
    `/api/v1/catalog-datasets/${encodeURIComponent(datasetVersion)}/components/selection${query}`,
  );
}
