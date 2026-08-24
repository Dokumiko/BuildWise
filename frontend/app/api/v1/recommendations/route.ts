export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();

  try {
    const upstream = await fetch(`${process.env.BUILDWISE_BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000"}/api/v1/recommendations`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body,
      cache: "no-store",
    });
    const responseBody = await upstream.text();

    return new Response(responseBody, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
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
