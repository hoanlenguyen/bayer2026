#!/usr/bin/env bash
# Backend on Azure Container Apps (consumption plan, free monthly grant, scales to zero).
# Run in Azure Cloud Shell (Bash) or anywhere with the Azure CLI, after `az login`.
#
#   bash containerapp.sh create   first time: resource group, environment, app with secrets
#   bash containerapp.sh update   after a new image was pushed: start a new revision with the latest image
#   bash containerapp.sh url      print the backend address (BACKEND_URL for the Cloudflare Worker)
#   bash containerapp.sh logs     follow the backend's console output
#   bash containerapp.sh jev      add or replace the TypeSafe key (Jev) on an existing app
#
# Secrets are read from the keyboard, never written to a file.
set -euo pipefail

RG="${RG:-analytics-manager-rg}"
LOCATION="${LOCATION:-francecentral}"          # Paris, next to the Atlas cluster. Try westeurope if blocked.
ENV_NAME="${ENV_NAME:-analytics-manager-env}"
APP="${APP:-analytics-manager-api}"
GH_OWNER="${GH_OWNER:-hoanlenguyen}"
IMAGE="${IMAGE:-ghcr.io/${GH_OWNER}/bayer2026-backend:latest}"

url() { az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv | sed 's#^#https://#'; }

case "${1:-}" in
  create)
    az extension add --name containerapp --upgrade --only-show-errors
    az provider register --namespace Microsoft.App --wait
    az provider register --namespace Microsoft.OperationalInsights --wait

    read -rp  "GitHub username for ghcr.io [$GH_OWNER]: " GH_USER; GH_USER="${GH_USER:-$GH_OWNER}"
    read -rsp "GitHub token with read:packages (for the private image): " GH_TOKEN; echo
    read -rsp "OPENAI_API_KEY (empty = offline mock mode): " OPENAI_API_KEY; echo
    read -rsp "MONGODB_URI (empty = in-memory store): " MONGODB_URI; echo
    read -rsp "TYPESAFE_API_KEY for Jev (empty = Jev off, GPT and rules decide): " TYPESAFE_API_KEY; echo

    az group create -n "$RG" -l "$LOCATION" -o none
    # No Log Analytics workspace: avoids its charges. Live logs still work with `bash containerapp.sh logs`.
    az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" --logs-destination none -o none

    secrets=(); envs=(LLM_PROVIDER=auto EMBEDDINGS=auto STAGE_DELAY=0.35 MONGODB_DB=analytics_manager)
    if [ -n "$OPENAI_API_KEY" ]; then secrets+=("openai-api-key=$OPENAI_API_KEY"); envs+=("OPENAI_API_KEY=secretref:openai-api-key"); fi
    if [ -n "$MONGODB_URI" ]; then secrets+=("mongodb-uri=$MONGODB_URI"); envs+=("MONGODB_URI=secretref:mongodb-uri"); fi
    # Jev runs the simulator's conversation phase whenever the key is set. Ask-flow phases need JEV_PHASES
    # (relevance,kpis,urgency), set later only after scripts/eval_classification.py passes for them.
    if [ -n "$TYPESAFE_API_KEY" ]; then
      secrets+=("typesafe-api-key=$TYPESAFE_API_KEY"); envs+=("TYPESAFE_API_KEY=secretref:typesafe-api-key" "JEV_MODEL=jev-1.14.0")
    fi
    secret_args=()
    if [ "${#secrets[@]}" -gt 0 ]; then secret_args=(--secrets "${secrets[@]}"); fi

    # One replica at most: users share the in-memory state (vector store, live requests).
    # Zero at least: no cost while idle; the first request after a quiet period waits for a cold start.
    az containerapp create -n "$APP" -g "$RG" --environment "$ENV_NAME" \
      --image "$IMAGE" --registry-server ghcr.io --registry-username "$GH_USER" --registry-password "$GH_TOKEN" \
      --target-port 8000 --ingress external \
      --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
      "${secret_args[@]}" --env-vars "${envs[@]}" -o none
    echo "Backend: $(url)"
    echo "Next: set BACKEND_URL to this address in deploy/cloudflare (docs/DEPLOY_FREE.md step 5)."
    ;;
  update)
    # Same tag (:latest), so force a new revision to pull it again.
    az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --revision-suffix "r$(date +%m%d%H%M)" -o none
    echo "Updated: $(url)"
    ;;
  jev)
    read -rsp "TYPESAFE_API_KEY: " TYPESAFE_API_KEY; echo
    [ -n "$TYPESAFE_API_KEY" ] || { echo "No key entered, nothing changed."; exit 1; }
    az containerapp secret set -n "$APP" -g "$RG" --secrets "typesafe-api-key=$TYPESAFE_API_KEY" -o none
    # Changing env vars starts a new revision, so the backend restarts and reads the key.
    az containerapp update -n "$APP" -g "$RG" -o none \
      --set-env-vars TYPESAFE_API_KEY=secretref:typesafe-api-key JEV_MODEL=jev-1.14.0
    echo "Jev key set. Check: $(url)/api/health should show \"jev\": true"
    ;;
  url)  url ;;
  logs) az containerapp logs show -n "$APP" -g "$RG" --follow --format text ;;
  *)    echo "usage: bash containerapp.sh create|update|jev|url|logs"; exit 1 ;;
esac
