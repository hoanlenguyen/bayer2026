#!/usr/bin/env bash
# Backend on Azure Container Apps (consumption plan, free monthly grant, scales to zero).
# Run in Azure Cloud Shell (Bash) or anywhere with the Azure CLI, after `az login`.
#
#   bash containerapp.sh create   first time: resource group, environment, app with secrets
#   bash containerapp.sh update   after a new image was pushed: start a new revision with the latest image
#   bash containerapp.sh url      print the backend address (BACKEND_URL for the Cloudflare Worker)
#   bash containerapp.sh image    print the image and revision that serve production now
#   bash containerapp.sh logs     follow the backend's console output
#   bash containerapp.sh jev      add or replace the TypeSafe key (Jev) on an existing app
#   bash containerapp.sh github   let GitHub Actions deploy on push to main (managed identity + OIDC, no password)
#
# Secrets are read from the keyboard, never written to a file.
set -euo pipefail

RG="${RG:-analytics-manager-rg}"
LOCATION="${LOCATION:-francecentral}"          # Paris, next to the Atlas cluster. Try westeurope if blocked.
ENV_NAME="${ENV_NAME:-analytics-manager-env}"
APP="${APP:-analytics-manager-api}"
GH_OWNER="${GH_OWNER:-hoanlenguyen}"
IMAGE="${IMAGE:-ghcr.io/${GH_OWNER}/bayer2026-backend:latest}"

# The containerapp commands live in an Azure CLI extension; install it without prompting (CI and fresh machines).
ext() { az extension add --name containerapp --upgrade --only-show-errors; }

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

    secrets=(); envs=(LLM_PROVIDER=auto EMBEDDINGS=auto MONGODB_DB=analytics_manager)
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
    ext
    # A new revision suffix also makes a reused tag (:latest) pull again. To deploy one release, pass
    # IMAGE=ghcr.io/<owner>/bayer2026-backend:<commit sha>.
    echo "Deploying $IMAGE"
    az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --revision-suffix "r$(date +%m%d%H%M)" -o none
    echo "Updated: $(url)"
    ;;
  image)
    ext
    az containerapp show -n "$APP" -g "$RG" \
      --query "{image: properties.template.containers[0].image, revision: properties.latestReadyRevisionName, running: properties.runningStatus}" -o table
    az containerapp revision list -n "$APP" -g "$RG" \
      --query "[?properties.active].{revision: name, image: properties.template.containers[0].image, traffic: properties.trafficWeight, health: properties.healthState}" -o table
    ;;
  jev)
    ext
    read -rsp "TYPESAFE_API_KEY: " TYPESAFE_API_KEY; echo
    [ -n "$TYPESAFE_API_KEY" ] || { echo "No key entered, nothing changed."; exit 1; }
    az containerapp secret set -n "$APP" -g "$RG" --secrets "typesafe-api-key=$TYPESAFE_API_KEY" -o none
    # Changing env vars starts a new revision, so the backend restarts and reads the key.
    az containerapp update -n "$APP" -g "$RG" -o none \
      --set-env-vars TYPESAFE_API_KEY=secretref:typesafe-api-key JEV_MODEL=jev-1.14.0
    echo "Jev key set. Check: $(url)/api/health should show \"jev\": true"
    ;;
  github)
    # Lets GitHub Actions deploy on push to main, without a password and without an app registration
    # (school directories often block those): a user-assigned managed identity in this resource group,
    # allowed to change only this resource group, trusted for this repository's main branch (OIDC).
    ext
    GH_REPO="${GH_REPO:-hoanlenguyen/bayer2026}"
    ID_NAME="${ID_NAME:-bayer2026-github-deploy}"
    SUB=$(az account show --query id -o tsv)
    TENANT=$(az account show --query tenantId -o tsv)
    echo "Creating managed identity $ID_NAME in $RG..."
    az identity create -n "$ID_NAME" -g "$RG" -l "$LOCATION" -o none
    CLIENT_ID=$(az identity show -n "$ID_NAME" -g "$RG" --query clientId -o tsv)
    PRINCIPAL_ID=$(az identity show -n "$ID_NAME" -g "$RG" --query principalId -o tsv)
    echo "Allowing it to change resource group $RG (Contributor)..."
    SCOPE="/subscriptions/$SUB/resourceGroups/$RG"
    # A new identity can take a minute to become visible to role assignments: only that case is retried.
    # Any other error is printed as Azure reports it, with what it usually means.
    for attempt in 1 2 3 4 5 6; do
      if err=$(az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
                 --role Contributor --scope "$SCOPE" -o none 2>&1); then break; fi
      case "$err" in
        *RoleAssignmentExists*|*"already exists"*)
          echo "The identity already has this role."; break ;;
        *PrincipalNotFound*|*"does not exist in the directory"*)
          if [ "$attempt" -lt 6 ]; then echo "  Identity not visible yet (attempt $attempt of 6), retrying in 15 s..."; sleep "${RETRY_WAIT:-15}"; continue; fi ;;
      esac
      echo
      echo "Role assignment failed. Azure said:"
      printf '%s\n' "$err" | sed 's/^/  /'
      echo
      case "$err" in
        *AuthorizationFailed*|*"does not have authorization"*|*"roleAssignments/write"*)
          echo "Meaning: your account may not give roles to others on $RG. That needs Owner or User Access"
          echo "Administrator on the subscription or the resource group (Contributor is not enough)."
          echo "Your roles there, as Azure lists them:"
          az role assignment list --scope "$SCOPE" --include-inherited \
            --query "[?principalType=='User'].{role: roleDefinitionName, scope: scope}" -o table 2>&1 | sed 's/^/  /'
          echo "Ask the subscription owner to run this script, or to give you Owner on $RG." ;;
        *PrincipalNotFound*|*"does not exist in the directory"*)
          echo "Meaning: the new identity is still not visible to Azure. Wait a few minutes and run this command again." ;;
        *)
          echo "Run this command again in a minute. If the same error appears, send it to the team." ;;
      esac
      exit 1
    done
    echo "Trusting GitHub Actions on $GH_REPO, branch main..."
    az identity federated-credential create --name github-main --identity-name "$ID_NAME" -g "$RG" \
      --issuer https://token.actions.githubusercontent.com --subject "repo:$GH_REPO:ref:refs/heads/main" \
      --audiences api://AzureADTokenExchange -o none
    echo
    echo "Add these 3 repository secrets in GitHub (Settings > Secrets and variables > Actions):"
    echo "  AZURE_CLIENT_ID        $CLIENT_ID"
    echo "  AZURE_TENANT_ID        $TENANT"
    echo "  AZURE_SUBSCRIPTION_ID  $SUB"
    echo "They are IDs, not passwords. GitHub signs in with a short-lived token for each run."
    ;;
  url)  ext; url ;;
  logs) ext; az containerapp logs show -n "$APP" -g "$RG" --follow --format text ;;
  *)    echo "usage: bash containerapp.sh create|update|image|jev|github|url|logs"; exit 1 ;;
esac
