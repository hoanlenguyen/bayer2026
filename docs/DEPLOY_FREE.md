# Deploy for free: Cloudflare Workers Free (frontend) + Azure Container Apps (backend)

## Push changes live

Use `main` for production. This checkout is configured with a `git live` shortcut. In another checkout, install it once:

```bash
git config alias.live '!bash deploy/push-live.sh'
```

Before editing, get the latest code:

```bash
git switch main
git pull --ff-only origin main
```

After editing, review and commit the files you want to publish, then run:

```bash
git add path/to/changed-file
git commit -m "Describe the change"
git live
```

`git live` fetches the latest history, safely fast-forwards when possible, and pushes your committed changes to `main`.
It stops if there are uncommitted files or conflicting history. It never force-pushes or commits files for you.
`git live --check` validates the history without moving your branch or pushing.

Open [Actions → Deploy live](https://github.com/hoanlenguyen/bayer2026/actions/workflows/deploy-live.yml) to follow the release:
backend tests and image → Azure update → new revision ready and commercial API returns 200 → Cloudflare `deploy:free` →
live `/briefings` and its API return 200. The final job summary gives the verified `/briefings` URL.
A successful Git push only starts the release; a green **Deploy live** run confirms deployment.
If nothing new was pushed, use **Run workflow → main** there to retry a release.

**One-time requirement:** the repository needs `AZURE_CREDENTIALS`, `CLOUDFLARE_API_TOKEN`, and `CLOUDFLARE_ACCOUNT_ID`.
The account owner adds these in [Settings → Secrets and variables → Actions](https://github.com/hoanlenguyen/bayer2026/settings/secrets/actions).
See [Automatic deploys](#automatic-deploys-on-push-to-main) below for how to obtain each value. Keep the values out of chat and Git.
Once configured, collaborators with GitHub write access can publish without signing into Azure or Cloudflare on their own machines.

```
Browser ──► https://analytics-manager.<your-subdomain>.workers.dev      Cloudflare Worker, Free plan
              ├─ /, /cala-graph, /assets/*  → React build (static assets)
              └─ /api/*                     → Worker forwards to BACKEND_URL
                                                  │
                                                  ▼
              https://analytics-manager-api.<id>.francecentral.azurecontainerapps.io    Azure Container Apps
                                                  └─ backend/Dockerfile (FastAPI) ─► MongoDB Atlas, OpenAI API

Image: GitHub Actions builds backend/Dockerfile → ghcr.io/hoanlenguyen/bayer2026-backend (free) → pulled by Azure
```

The browser only sees the Cloudflare address, so no CORS setup and no `VITE_API_BASE` are needed.

Why this split: Cloudflare Containers need the paid plan, and the Python backend cannot run as a free Worker. Azure Container Apps
runs the existing Docker image on its free monthly grant.

Files: `.github/workflows/backend-image.yml`, `deploy/azure/containerapp.sh`, `deploy/cloudflare/wrangler.free.jsonc`,
`deploy/cloudflare/src/proxy.js`.

Tested: the free Worker (`wrangler dev`) in front of the real backend, with health, frontend routes and the streaming chat (17 events
arriving over 2.7 s as they are sent, not buffered). The Azure script was checked with a stand-in `az` command; the first real run is yours.

## Cost

| Part | Free allowance | Our use |
|---|---|---|
| Cloudflare Workers Free | 100,000 requests per day | Far below |
| Azure Container Apps (consumption) | Per month: 180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million requests | 0.5 vCPU, 1 GiB; scales to zero when idle. About 100 hours of activity per month stay free. |
| GitHub Container Registry | Free for this use | One image |
| Azure for Students credit | USD 100 | Covers anything above the grant |

## Step 1. Build the backend image (automatic)

Every push to `main`, `version-2` or `version-4` that changes `backend/` or `materials/` runs **Actions → Backend image** and pushes
`ghcr.io/hoanlenguyen/bayer2026-backend:latest`. To run it by hand: **Actions → Backend image → Run workflow**.

Check it worked: GitHub profile → **Packages** → `bayer2026-backend`.

## Step 2. A token so Azure can pull the image

The image follows the repository's visibility, and is private for a private repository (it contains the data pack). Azure then needs a
**classic** personal access token to pull it:
GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token**,
scope **read:packages** only, expiry after the hackathon. Copy it once. Do not paste it into chat or commit it.

## Step 3. MongoDB Atlas network access

Container Apps has no fixed outgoing IP address on the consumption plan, so Atlas must accept connections from anywhere:
Atlas → project **Bayer2026** → **Network Access → Add IP Address → Allow access from anywhere** (`0.0.0.0/0`).
Because of that, rotate the database password that was shared in chat earlier (**Database Access → Edit → Edit Password**) and use the
new one below.

## Step 4. Create the backend on Azure

1. Sign in at https://portal.azure.com with your Azure for Students account.
2. Open **Cloud Shell** (the `>_` icon at the top), choose **Bash**. No local install needed.
3. Get the script and run it:

```bash
git clone https://github.com/hoanlenguyen/bayer2026.git && cd bayer2026 && git checkout version-4
```

If the repository is private, use your GitHub username and the token from step 2 (or another token with repository read access) as
the password.

```bash
bash deploy/azure/containerapp.sh create
```

It asks for the GitHub username, the token from step 2, `OPENAI_API_KEY`, `MONGODB_URI` and, optionally, `TYPESAFE_API_KEY` for Jev
(typing is hidden; leave a prompt empty to skip it). It creates the resource
group `analytics-manager-rg` in France Central, a Container Apps environment without paid logging, and the app, then prints the
backend address, for example `https://analytics-manager-api.<id>.francecentral.azurecontainerapps.io`.

Check it: open `<backend address>/api/health`. The first call after creation or after a quiet period starts the container and can take
20 to 60 seconds. Expect `"provider": "openai"` and `"store": "mongodb"`.

If the region is blocked for student subscriptions, run `LOCATION=westeurope bash deploy/azure/containerapp.sh create`.

## Step 5. Deploy the frontend to Cloudflare (Free plan)

On your machine (Node.js 22; no Docker needed), from the repository:

1. Put the backend address from step 4 into `deploy/cloudflare/wrangler.free.jsonc`:
   `"BACKEND_URL": "https://analytics-manager-api.<id>.francecentral.azurecontainerapps.io"`
2. Deploy:

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
npm run deploy:free
```

It builds the frontend and uploads it with the small proxy Worker. The output ends with
`https://analytics-manager.<your-subdomain>.workers.dev`. Open it and run a starter question.

## Automatic deploys on push to main

After a one-time setup, every push to `main` starts **Deploy live**. It checks all three credentials first, then calls
**Backend image** to test, build, deploy Azure, and verify `/api/briefings/commercial`. Only after that passes does it call
**Frontend deploy** to run `npm run deploy:free` and verify the live `/briefings` page and proxied API.

Pushes to `version-2` and `version-4` only test and build the backend image; they never deploy.
Missing credentials fail the production workflow with the exact missing secret names; deployment is never silently skipped.

**One-time setup** (GitHub → **Settings → Secrets and variables → Actions → New repository secret**):

1. `AZURE_CREDENTIALS`: in Azure Cloud Shell, run

   ```bash
   cd ~/bayer2026 && git pull && bash deploy/azure/containerapp.sh github
   ```

   It creates a service principal that may change only the `analytics-manager-rg` resource group and prints a JSON block.
   Paste the whole JSON as the secret value, then run `clear` in Cloud Shell. It contains a password: never paste it anywhere else.
   If your school's Azure directory does not allow creating it ("Insufficient privileges"), keep updating the backend by hand
   (below); the frontend automation works regardless.
2. `CLOUDFLARE_API_TOKEN`: Cloudflare dashboard → **My Profile → API Tokens → Create Token → "Edit Cloudflare Workers"** template.
3. `CLOUDFLARE_ACCOUNT_ID`: Cloudflare dashboard → **Workers & Pages** → Account ID on the right.

Check: **Actions → Deploy live → Run workflow → main**. A successful release ends with **Live briefings** and its verified address
in the frontend job summary. Local Wrangler login is only needed for a manual deployment from your machine.

## Updating by hand

- **Backend:** push (the image builds by itself), wait for the workflow to finish, then in Cloud Shell:

```bash
cd ~/bayer2026 && bash deploy/azure/containerapp.sh update
```

- **Frontend:** `npm run deploy:free` in `deploy/cloudflare` again.

The separate **Legacy Cloudflare Containers (paid)** workflow is for the paid alternative, not this deployment.

## Daily operations (Cloud Shell, in `~/bayer2026`)

| Task | Command |
|---|---|
| Backend address | `bash deploy/azure/containerapp.sh url` |
| Live backend logs | `bash deploy/azure/containerapp.sh logs` |
| Turn Jev on (add or replace the TypeSafe key) | `bash deploy/azure/containerapp.sh jev` |
| Frontend logs | `npx wrangler tail -c wrangler.free.jsonc` in `deploy/cloudflare` |
| Delete everything on Azure | `az group delete -n analytics-manager-rg` |

## Things to know

- **Cold start:** with zero replicas when idle, the first request after a quiet period waits for the container. To keep it warm
  during the demo: `az containerapp update -n analytics-manager-api -g analytics-manager-rg --min-replicas 1`
  (uses more of the free grant; set it back to 0 afterwards).
- **One replica:** `--max-replicas 1`, so all users share the same in-memory state (vector store, requests created in the app).
- **Generated PBIP files** are written inside the container and are lost when it scales to zero. Download them in the same session.
- **Atlas vector index** is unchanged. If you change `EMBED_MODEL` or `EMBED_DIMS`, run `python -m app.build_vectors` locally again.
- The paid Cloudflare setup (`wrangler.jsonc`, Containers) and the VM setup (`deploy/server/`) stay in the repository as alternatives.
