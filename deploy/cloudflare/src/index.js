// One Worker for the whole app.
// - Static files (the React build) are served by Workers Static Assets before this code runs.
// - /api/* is forwarded to the FastAPI backend running in a Cloudflare Container.
import { Container, getContainer } from "@cloudflare/containers";

// Settings the backend reads from its environment. Secrets (OPENAI_API_KEY, MONGODB_URI) come from
// `wrangler secret put`; the rest from "vars" in wrangler.jsonc. Only names listed here reach the container.
const BACKEND_ENV = [
  "LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_REASONING", "MODEL_FAST",
  "EMBEDDINGS", "EMBED_MODEL", "EMBED_DIMS", "MONGODB_URI", "MONGODB_DB", "STAGE_DELAY",
];

export class Backend extends Container {
  defaultPort = 8000;   // uvicorn port in backend/Dockerfile
  sleepAfter = "30m";   // stop after 30 minutes without requests; the next request starts it again

  constructor(ctx, env) {
    super(ctx, env);
    this.envVars = Object.fromEntries(
      BACKEND_ENV.filter((k) => env[k] !== undefined && env[k] !== "").map((k) => [k, String(env[k])]),
    );
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      // One named instance, so every user shares the same in-memory state (vector store, live requests).
      return getContainer(env.BACKEND, "main").fetch(request);
    }
    return env.ASSETS.fetch(request);
  },
};
