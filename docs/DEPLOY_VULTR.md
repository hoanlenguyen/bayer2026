# Deploy to Vultr (frontend + backend on one server)

One Vultr server runs two containers with Docker Compose:

```
Browser ──► https://<your-address>   (port 443, certificate from Let's Encrypt, renewed by Caddy)
              │
              └─ web (Caddy)  ── /, /cala-graph, /assets/*  → React build
                              └─ /api/*                     → backend:8000 (FastAPI, backend/Dockerfile)
                                                               └─► MongoDB Atlas, OpenAI API
```

Port 8000 is not published: only Caddy reaches the backend. The frontend and the API share one address, so no CORS setup and no
`VITE_API_BASE` are needed.

Files: `deploy/vultr/docker-compose.yml`, `deploy/vultr/Caddyfile`, `deploy/vultr/web.Dockerfile`, `deploy/vultr/setup.sh`,
`deploy/vultr/.env.example`.

Tested end to end with Docker (mock model, in-memory store): health check, frontend routes, the streaming `/api/chat` flow up to approval,
approval with PBIP rendering, and PBIP files kept on the `pbip-output` volume.

## Step 1. Create the server

1. https://my.vultr.com → **Deploy → Cloud Compute (Shared CPU)**.
2. **Location: Paris.** The team's Atlas cluster runs in AWS Paris (`eu-west-3`), so the database is close.
3. **Image: Ubuntu 24.04 LTS.**
4. **Plan: 2 GB memory** or more (1 vCPU is enough). 1 GB works for running but the frontend build can run out of memory; the setup
   script adds swap either way. Check the current price on the plan list.
5. Add your **SSH key** (recommended) and a hostname such as `analytics-manager`. Deploy.
6. Note the server's **public IPv4 address**, for example `203.0.113.7`.

## Step 2. Allow the server in MongoDB Atlas

The server keeps the same IP address, so allow only that address:

Atlas → project **Bayer2026** → **Network Access → Add IP Address** → `203.0.113.7/32` (your server's address).

Also rotate the database password that was shared in chat earlier (**Database Access → Edit → Edit Password**) and use the new one below.

## Step 3. Prepare the server (once)

From your computer:

```bash
ssh root@203.0.113.7
```

On the server:

```bash
git clone https://github.com/hoanlenguyen/bayer2026.git && cd bayer2026 && git checkout version-2
```

If the repository is private, GitHub asks for a username and a password: use a
[fine-grained personal access token](https://github.com/settings/personal-access-tokens) with read access to this repository as the password.

```bash
bash deploy/vultr/setup.sh
```

This installs Docker, adds 2 GB of swap and opens only ports 22, 80 and 443 in the firewall.

## Step 4. Configuration (once)

Backend keys, the same file you use locally:

```bash
cp backend/.env.example backend/.env && nano backend/.env
```

Fill in `OPENAI_API_KEY` and `MONGODB_URI` (with the new password). Leave `CORS_ORIGINS` as it is. Save with Ctrl+O, exit with Ctrl+X.
This file stays on the server and is never committed.

Public address:

```bash
cp deploy/vultr/.env.example deploy/vultr/.env && nano deploy/vultr/.env
```

| `SITE_ADDRESS` | Result |
|---|---|
| `203.0.113.7.sslip.io` (your IP + `.sslip.io`) | HTTPS with a free certificate, no domain needed. Recommended. |
| `analytics.example.com` | HTTPS on your own domain. First add a DNS `A` record pointing to the server IP. |
| `:80` | Plain HTTP on the IP address. For a first test only. |

## Step 5. Start

```bash
cd deploy/vultr && docker compose up -d --build
```

The first build takes a few minutes. Then check:

```bash
docker compose ps
```

Both services should be `Up`, and the backend `healthy` after about 20 seconds.

Open `https://203.0.113.7.sslip.io/api/health` (or your address). Expect `"provider": "openai"` and `"store": "mongodb"`.
Then open the address without `/api/health` and run a starter question.

## Updating after new commits

```bash
cd ~/bayer2026 && git pull && cd deploy/vultr && docker compose up -d --build
```

## Daily operations

| Task | Command (in `~/bayer2026/deploy/vultr`) |
|---|---|
| Live logs | `docker compose logs -f backend` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` |
| Generated PBIP files | `docker compose exec backend ls output` |
| Copy PBIP files to the server disk | `docker compose cp backend:/app/backend/output ./pbip-output` |

Containers restart on their own after a crash or a server reboot (`restart: unless-stopped`).

## Things to know

- **Certificates:** Caddy gets and renews them by itself. Ports 80 and 443 must stay open, and `SITE_ADDRESS` must resolve to the server.
- **One backend process:** all users share the same in-memory state (vector store, requests created in the app), as with local runs.
- **Atlas vector index** is unchanged. If you change `EMBED_MODEL` or `EMBED_DIMS`, run `python -m app.build_vectors` again
  (locally or with `docker compose exec backend python -m app.build_vectors`).
- **Snapshots:** Vultr can back up the whole server (Backups option); turn it on if the demo server must not be lost.
- **Cost control:** delete the server after the hackathon. A stopped Vultr server is still billed.
