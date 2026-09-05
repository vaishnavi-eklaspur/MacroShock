"""Render the Helm chart into plain Kubernetes manifests under `k8s/`.

The chart is the single source of truth. These manifests exist so the deployment can be read
(or applied with `kubectl apply -f k8s/`) without installing Helm — but they are *generated*,
never hand-edited, so the two can't drift apart. CI regenerates them and fails if the committed
files differ from what the chart produces.

Run:  python scripts/render_k8s.py          (needs `helm` on PATH, or $HELM_BIN)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CHART = REPO / "charts" / "macroshock"
OUT = REPO / "k8s"

HEADER = """# GENERATED FILE - DO NOT EDIT.
# Rendered from charts/macroshock by scripts/render_k8s.py; edit the chart instead.
# Regenerate with:  python scripts/render_k8s.py
"""

README = """# Plain Kubernetes manifests

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
"""


def helm_binary() -> str:
    found = os.environ.get("HELM_BIN") or shutil.which("helm")
    if not found:
        sys.exit("helm not found: install it or set HELM_BIN to the binary path.")
    return found


def main() -> int:
    rendered = subprocess.run(
        [helm_binary(), "template", "macroshock", str(CHART)],
        capture_output=True, text=True, check=True,
    ).stdout

    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("*.yaml"):
        stale.unlink()

    written = []
    for doc in rendered.split("\n---\n"):
        if not doc.strip():
            continue
        parsed = yaml.safe_load(doc)
        if not parsed:
            continue
        kind = parsed["kind"].lower()
        component = (parsed.get("metadata", {})
                     .get("labels", {})
                     .get("app.kubernetes.io/component", parsed["metadata"]["name"]))
        path = OUT / f"{component}-{kind}.yaml"
        path.write_text(HEADER + doc.strip() + "\n", encoding="utf-8")
        written.append(path.name)

    (OUT / "README.md").write_text(README, encoding="utf-8")
    print(f"rendered {len(written)} manifest(s) into k8s/: {', '.join(sorted(written))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
