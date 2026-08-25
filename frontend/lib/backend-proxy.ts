const backendBase = process.env.BUILDWISE_BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function proxyToBackend(path: string, init?: RequestInit): Promise<Response> {
  try {
    const upstream = await fetch(`${backendBase}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
    const body = await upstream.text();
    return new Response(body, {
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