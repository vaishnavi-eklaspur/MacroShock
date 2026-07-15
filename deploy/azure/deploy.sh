#!/usr/bin/env bash
# Deploy MacroShock to Azure Container Apps (API + dashboard), always-on (no cold starts).
#
# Prereqs: az CLI logged in (`az login`), a subscription selected.
# Usage:   RG=macroshock LOC=centralindia ./deploy.sh
set -euo pipefail

RG="${RG:-macroshock-rg}"
LOC="${LOC:-centralindia}"
ACR="${ACR:-macroshock$RANDOM}"          # must be globally unique
ENV="${ENV:-macroshock-env}"
API_KEY="${MACROSHOCK_API_KEY:-}"        # optional; if set, write endpoints require it

echo "==> Resource group + registry + Container Apps environment"
az group create -n "$RG" -l "$LOC" -o none
az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true -o none
az containerapp env create -n "$ENV" -g "$RG" -l "$LOC" -o none

echo "==> Build images in ACR (no local Docker needed)"
az acr build -r "$ACR" -t macroshock-api:latest ./backend
az acr build -r "$ACR" -t macroshock-dashboard:latest ./frontend
LOGIN=$(az acr show -n "$ACR" --query loginServer -o tsv)

# API key handled as a Container Apps SECRET (not a plaintext env var), referenced via secretref.
API_SECRET=()
API_ENVKEY=()
if [ -n "$API_KEY" ]; then
  API_SECRET=(--secrets "api-key=$API_KEY")
  API_ENVKEY=("MACROSHOCK_API_KEY=secretref:api-key")
fi

echo "==> API container app (min-replicas=1 => no cold start)"
az containerapp create -n macroshock-api -g "$RG" --environment "$ENV" \
  --image "$LOGIN/macroshock-api:latest" --registry-server "$LOGIN" \
  --target-port 5000 --ingress external --min-replicas 1 --max-replicas 3 \
  --cpu 0.5 --memory 1.0Gi "${API_SECRET[@]}" \
  --env-vars "MACROSHOCK_DB=/app/dbdata/macroshock.db" "${API_ENVKEY[@]}" \
  -o none
API_URL="https://$(az containerapp show -n macroshock-api -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"

echo "==> Dashboard container app (min-replicas=1)"
az containerapp create -n macroshock-dashboard -g "$RG" --environment "$ENV" \
  --image "$LOGIN/macroshock-dashboard:latest" --registry-server "$LOGIN" \
  --target-port 8501 --ingress external --min-replicas 1 --max-replicas 2 \
  --cpu 0.5 --memory 1.0Gi "${API_SECRET[@]}" \
  --env-vars "API_BASE=$API_URL" "${API_ENVKEY[@]}" \
  -o none
APP_URL="https://$(az containerapp show -n macroshock-dashboard -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"

echo ""
echo "API:       $API_URL/health"
echo "Dashboard: $APP_URL"
echo "Tear down: az group delete -n $RG --yes --no-wait"
