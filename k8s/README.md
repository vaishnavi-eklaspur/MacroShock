# Plain Kubernetes manifests

These are **generated** from the Helm chart in [`../charts/macroshock`](../charts/macroshock) so
the deployment can be read or applied without Helm:

```bash
kubectl apply -f k8s/
```

They are rendered with the chart's default values. **Do not edit them by hand** — change the
chart and regenerate:

```bash
python scripts/render_k8s.py
```

CI re-renders them on every push and fails if the committed files differ from the chart, so the
two can never drift apart. For anything configurable (image tags, ingress, ServiceMonitor,
replica counts, the API-key Secret) use the chart directly — that is what `values.yaml` is for.
