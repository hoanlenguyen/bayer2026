// Free-plan Worker: serves the React build and forwards /api/* to a backend running elsewhere,
// on Azure Container Apps (docs/DEPLOY_FREE.md).
// BACKEND_URL is set in wrangler.free.jsonc.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);

    if (!env.BACKEND_URL) {
      return Response.json({ error: "BACKEND_URL is not set on the Worker" }, { status: 503 });
    }
    const target = new URL(url.pathname + url.search, env.BACKEND_URL);
    try {
      // Streams both ways, so the Server-Sent Events of /api/chat arrive as they are sent.
      return await fetch(new Request(target, request));
    } catch (err) {
      return Response.json({ error: `Backend not reachable at ${env.BACKEND_URL}`, detail: String(err) }, { status: 502 });
    }
  },
};
