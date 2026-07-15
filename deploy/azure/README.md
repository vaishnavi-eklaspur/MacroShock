# Deploy to Azure Container Apps

One-command, always-on deployment (no cold-start sleep) of the API + dashboard.

```bash
az login
RG=macroshock LOC=centralindia ./deploy/azure/deploy.sh
```

**What it does**

1. Creates a resource group, an Azure Container Registry, and a Container Apps environment.
2. Builds both images *in ACR* (`az acr build`) — no local Docker required.
3. Deploys `macroshock-api` and `macroshock-dashboard` as Container Apps with
   **`--min-replicas 1`**, so an instance is always warm — a recruiter clicking the link
   never hits a 30–60s cold start.

**Why Container Apps:** it runs the existing containers unchanged, scales on HTTP, has a free
grant, and gives real HTTPS URLs. Redis is skipped (the cache degrades gracefully); add Azure
Cache for Redis and set `REDIS_URL` if you want the cache live.

**Security:** set `MACROSHOCK_API_KEY` before running to require an `X-API-Key` header on write
endpoints (the dashboard is passed the same key automatically).

**Cost control:** `az group delete -n <RG> --yes --no-wait` removes everything.

**Health probe:** the API exposes `GET /health`; Container Apps uses it for readiness.
