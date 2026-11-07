# Deploy to Azure for Students (frontend + backend on one VM)

One small Azure Linux VM runs two containers with Docker Compose (`deploy/server/`):

```
Browser ──► https://analytics-manager.<region>.cloudapp.azure.com   (certificate from Let's Encrypt, renewed by Caddy)
              │
              └─ web (Caddy)  ── /, /cala-graph, /assets/*  → React build
                              └─ /api/*                     → backend:8000 (FastAPI, backend/Dockerfile)
                                                               └─► MongoDB Atlas, OpenAI API
```

Port 8000 is not published: only Caddy reaches the backend. Frontend and API share one address, so no CORS setup and no `VITE_API_BASE`.

Tested end to end with Docker (mock model, in-memory store): health check, frontend routes, the streaming `/api/chat` flow up to approval,
approval with PBIP rendering, PBIP files kept on the `pbip-output` volume. The backend uses about 70 MB of memory after a full run.

## What it costs on Azure for Students

Azure for Students gives USD 100 credit for 12 months (no credit card) and 12 months of free services, including **750 hours per month of
small Linux VMs** (`B2ats_v2`, `B2pts_v2`, `B1s`). One VM running all month stays inside the 750 hours.

To stay at (almost) zero:

| Resource | Choice | Cost |
|---|---|---|
| VM size | **Standard_B2ats_v2** (2 vCPU, 1 GiB). If not offered in the region, `Standard_B1s`. | Free (750 h/month) |
| OS | **Ubuntu Server 24.04 LTS** (Linux, not Windows) | Free |
| OS disk | **Standard SSD or Premium SSD, 64 GiB** (P6). The default 127 GiB disk is not free. | Free within the limit |
| Public IP | Standard, static (created with the VM) | A few dollars a month, taken from the USD 100 credit |
| Outbound traffic | 15 GB per month free | Enough for a demo |

Check usage at any time: Azure portal → **Cost Management → Cost analysis**, or the [Education Hub](https://portal.azure.com/#view/Microsoft_Azure_Education/EducationMenuBlade/~/overview).

## Step 1. Activate Azure for Students

1. https://azure.microsoft.com/free/students → **Start free**, sign in with your school e-mail and verify student status.
2. The Azure portal then shows the subscription **Azure for Students**.

## Step 2. Create the VM

Azure portal → **Create a resource → Virtual machine** (or search "free services" and pick the Linux VM there, which preselects free options).

**Basics**
- Resource group: new, `analytics-manager-rg`.
- Virtual machine name: `analytics-manager`.
- Region: **France Central** (Paris, next to the team's Atlas cluster in AWS Paris). If the size is not offered or the region is blocked
  for student subscriptions, try West Europe, North Europe or Sweden Central.
- Image: **Ubuntu Server 24.04 LTS - x64 Gen2**.
- Size: **Standard_B2ats_v2** ("free services eligible" is shown next to eligible sizes).
- Authentication: **SSH public key**, username `azureuser`, let Azure generate a key pair and download the `.pem` file when asked.
- Inbound ports: allow **SSH (22), HTTP (80), HTTPS (443)**.

**Disks**
- OS disk size: **64 GiB (P6)**, type Standard SSD or Premium SSD. Do not add data disks.

**Networking**
- Public IP: keep the new one Azure suggests (Standard SKU, static).

Review + create → **Create**. When it finishes, open the VM resource and note the **Public IP address**.

**DNS name (free HTTPS address):** on the VM page select the public IP → **Configuration → DNS name label** → `analytics-manager` → Save.
The VM is now reachable at `analytics-manager.francecentral.cloudapp.azure.com` (the region part matches your region).

## Step 3. Allow the VM in MongoDB Atlas

The IP is static, so allow only that address:

Atlas → project **Bayer2026** → **Network Access → Add IP Address** → `<public IP>/32`.

Also rotate the database password that was shared in chat earlier (**Database Access → Edit → Edit Password**) and use the new one below.

## Step 4. Prepare the VM (once)

From your computer (PowerShell on Windows works the same):

```bash
ssh -i path/to/analytics-manager_key.pem azureuser@analytics-manager.francecentral.cloudapp.azure.com
```

On the VM:

```bash
git clone https://github.com/hoanlenguyen/bayer2026.git && cd bayer2026 && git checkout version-2
```

If the repository is private, GitHub asks for a username and a password: use a
[fine-grained personal access token](https://github.com/settings/personal-access-tokens) with read access to this repository as the password.

```bash
sudo bash deploy/server/setup.sh
```

This installs Docker, adds 2 GB of swap (the 1 GiB VM needs it for the image build) and opens only ports 22, 80 and 443.

Let your user run Docker without `sudo`, then reconnect:

```bash
sudo usermod -aG docker azureuser && exit
```

## Step 5. Configuration (once)

Backend keys, the same file you use locally:

```bash
cd bayer2026 && cp backend/.env.example backend/.env && nano backend/.env
```

Fill in `OPENAI_API_KEY` and `MONGODB_URI` (with the new password). Leave `CORS_ORIGINS` as it is. Save with Ctrl+O, exit with Ctrl+X.
This file stays on the VM and is never committed.

Public address:

```bash
cp deploy/server/.env.example deploy/server/.env && nano deploy/server/.env
```

Set `SITE_ADDRESS=analytics-manager.francecentral.cloudapp.azure.com` (your DNS name from step 2). Caddy then gets an HTTPS certificate
for it on first start. `:80` gives plain HTTP on the IP address, for a first test only.

## Step 6. Start

```bash
cd deploy/server && docker compose up -d --build
```

The first build takes several minutes on this small VM. Then check:

```bash
docker compose ps
```

Both services should be `Up`, and the backend `healthy` after about 20 seconds.

Open `https://analytics-manager.francecentral.cloudapp.azure.com/api/health`. Expect `"provider": "openai"` and `"store": "mongodb"`.
Then open the address without `/api/health` and run a starter question.

## Updating after new commits

```bash
cd ~/bayer2026 && git pull && cd deploy/server && docker compose up -d --build
```

## Daily operations

| Task | Command (in `~/bayer2026/deploy/server`) |
|---|---|
| Live logs | `docker compose logs -f backend` |
| Restart | `docker compose restart` |
| Stop the app | `docker compose down` |
| Generated PBIP files | `docker compose exec backend ls output` |
| Copy PBIP files to the VM disk | `docker compose cp backend:/app/backend/output ./pbip-output` |

Containers restart on their own after a crash or a VM reboot (`restart: unless-stopped`).

## Things to know

- **Stop vs deallocate:** to pause the VM and its compute hours, use **Stop** in the portal (it deallocates). Shutting down from inside
  Linux does not. The public IP and disk are still billed while stopped. After the hackathon, delete the whole resource group.
- **Certificates:** Caddy gets and renews them. Ports 80 and 443 must stay open in the VM's network security group.
- **One backend process:** all users share the same in-memory state (vector store, requests created in the app), as in local runs.
- **Atlas vector index** is unchanged. If you change `EMBED_MODEL` or `EMBED_DIMS`, run
  `docker compose exec backend python -m app.build_vectors`.
- **Other hosts:** `deploy/server/` works on any Ubuntu server (Vultr, DigitalOcean, a lab machine). Only the address in
  `deploy/server/.env` changes.
