export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return forwardToBackend("/api/v1/catalog-datasets");
}

async function forwardToBackend(path: string): Promise<Response> {
  try {
    const upstream = await fetch(`${process.env.BUILDWISE_BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000"}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await upstream.text();

    return new Response(body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return Response.json(
      {
        detail: {
          code: "BACKEND_UNAVAILABLE",
          message: "The deterministic backend is unavailable. Start the backend and try again.",
        },
      },
      { status: 503 },
    );
  }
}
