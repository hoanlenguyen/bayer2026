# Deploy to Cloudflare (frontend + backend)

One Cloudflare Worker runs the whole app:

```
Browser ──► https://analytics-manager.<your-subdomain>.workers.dev
              │
              ├─ /, /cala-graph, /assets/*  → React build (Workers Static Assets, no Worker code runs)
              └─ /api/*                     → Worker → Container "Backend" (FastAPI, backend/Dockerfile, port 8000)
                                                         └─► MongoDB Atlas, OpenAI API
```

The frontend and the API share one address, so the browser needs no CORS setup and no `VITE_API_BASE`.

Files: `deploy/cloudflare/wrangler.jsonc` (configuration), `deploy/cloudflare/src/index.js` (Worker and container class),
`.github/workflows/deploy-cloudflare.yml` (deploy from GitHub), `.dockerignore` (keeps the image small).

## Cost

- Workers Paid plan: USD 5 per month minimum. Containers need it.
- Container usage on top of that is billed for the time it runs, and CPU only while it works. The container (`standard-1`: 1/2 vCPU, 4 GiB)
  stops after 30 minutes without requests (`sleepAfter` in `src/index.js`), so a demo app costs little.
- Check current rates at https://developers.cloudflare.com/containers/platform/pricing/.

## Step 1. Cloudflare account (once)

1. Sign in at https://dash.cloudflare.com, then **Workers & Pages → Plans**, and choose **Workers Paid**.
2. Note your **Account ID** (Workers & Pages overview, right-hand side).
3. Create an API token: **My Profile → API Tokens → Create Token → "Edit Cloudflare Workers"** template.
   Add the permission **Account → Containers → Edit** if the template does not include it.
   Copy the token once; it is shown only once. Do not paste it into chat or commit it.

## Step 2. MongoDB Atlas network access (once)

Containers have no fixed outgoing IP address, so Atlas must accept connections from anywhere:

1. Atlas → project **Bayer2026** → **Network Access → Add IP Address → Allow access from anywhere** (`0.0.0.0/0`).
2. Because of that, the database user needs a strong password. Rotate the password that was shared in chat earlier
   (**Database Access → Edit → Edit Password**) and update `MONGODB_URI` in your local `backend/.env` too.

## Step 3. Store the app keys on the Worker (once)

On your machine (Windows PowerShell works), from the repository:

```bash
cd deploy/cloudflare
```

```bash
npm install
```

```bash
npx wrangler login
```

```bash
npx wrangler secret put OPENAI_API_KEY
```

```bash
npx wrangler secret put MONGODB_URI
```

Each `secret put` asks for the value and stores it encrypted on the Worker. If the Worker does not exist yet, Wrangler offers to create it; answer yes.
Secrets stay in place across deploys. Other settings (models, embeddings, database name) are in `"vars"` in `wrangler.jsonc`.

Without these two secrets the app still runs, offline: mock model, local embeddings and in-memory storage that is lost when the container stops.

## Step 4. Deploy

Choose one.

### A. From GitHub (recommended, no Docker on your machine)

1. GitHub repository → **Settings → Secrets and variables → Actions → New repository secret**:
   `CLOUDFLARE_API_TOKEN` (from step 1.3) and `CLOUDFLARE_ACCOUNT_ID` (from step 1.2).
2. **Actions → Deploy to Cloudflare → Run workflow**, pick the branch (for example `version-2`), run.
3. The log ends with the address, `https://analytics-manager.<your-subdomain>.workers.dev`.

The workflow file must be on the default branch (`main`) for the **Run workflow** button to appear. Until it is merged there,
use option B.

### B. From your machine (needs Docker Desktop running)

```bash
cd deploy/cloudflare
```

```bash
npm run deploy
```

This builds the frontend, builds the backend image from `backend/Dockerfile`, pushes it to Cloudflare's registry and deploys the Worker.

## Step 5. Check it works

1. Open `https://analytics-manager.<your-subdomain>.workers.dev/api/health`. The first request after a deploy or a quiet period
   starts the container and can take 20 to 40 seconds. Expect `"provider": "openai"` and `"store": "mongodb"`.
2. Open the address without `/api/health` and run a starter question. With **Technical details** on, "Understand the request"
   should show MongoDB Atlas Vector Search.
3. Logs: `npx wrangler tail` in `deploy/cloudflare`, or the Worker's **Logs** tab in the dashboard (container output included).

## Updating

Run the GitHub workflow again, or `npm run deploy`. The new container image replaces the old one; the running container is stopped and
the next request starts the new version.

## Things to know

- **One shared backend instance.** The Worker sends every `/api/*` request to the container named `main`, so all users share the same
  in-memory state (vector store, requests created in the app). `max_instances: 2` leaves room for a rollout.
- **Cold start.** After 30 minutes without requests the container stops. The next request waits for it to start. To keep it warm
  during a demo, raise `sleepAfter` in `src/index.js` (for example `"3h"`) and deploy again.
- **Generated PBIP files** are written inside the container (`/app/backend/output`) and are lost when it stops. Download them in the
  same session.
- **Atlas vector index** is unchanged. If you change `EMBED_MODEL` or `EMBED_DIMS`, run `python -m app.build_vectors` locally again.
- **Local development** is unchanged: `uvicorn` on port 8000 and `npm run dev` in `frontend/`.
