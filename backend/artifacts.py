"""Object-store publication of workflow artifacts.

A finished analysis produces files, not just a JSON response, and those files need to outlive the
request and be shareable. This publishes a run's artifacts to any S3-compatible object store and
hands back time-limited presigned URLs.

`boto3` against an S3 endpoint is used rather than a vendor SDK on purpose: the same code targets
MinIO locally, AWS S3, and Ceph/RadosGW (what large research infrastructures typically run), so
the deployment target is configuration rather than a code change.

Degrades gracefully: with no endpoint configured (or boto3 absent) the store is disabled and
artifacts simply stay on the local filesystem — the analysis must never fail because optional
infrastructure is missing.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("macroshock.artifacts")

DEFAULT_EXPIRY_SECONDS = 3600


class ArtifactStore:
    """Publishes run artifacts to an S3-compatible bucket."""

    def __init__(
        self,
        endpoint: str | None = None,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        expiry: int | None = None,
    ):
        self.endpoint = endpoint or os.getenv("MACROSHOCK_S3_ENDPOINT")
        self.bucket = bucket or os.getenv("MACROSHOCK_S3_BUCKET", "macroshock")
        self.region = region or os.getenv("MACROSHOCK_S3_REGION", "us-east-1")
        self.expiry = int(expiry or os.getenv("MACROSHOCK_S3_EXPIRY", DEFAULT_EXPIRY_SECONDS))
        self._client = None

        if not self.endpoint:
            logger.info("No object store configured; artifacts stay on local disk.")
            return

        access = access_key or os.getenv("MACROSHOCK_S3_ACCESS_KEY")
        secret = secret_key or os.getenv("MACROSHOCK_S3_SECRET_KEY")
        try:
            import boto3  # noqa: PLC0415 - optional dependency
            from botocore.client import Config  # noqa: PLC0415

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                region_name=self.region,
                # Path-style addressing: MinIO/Ceph don't do virtual-host buckets by default.
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                              connect_timeout=3, retries={"max_attempts": 2}),
            )
            self._ensure_bucket()
            logger.info("Object store ready at %s (bucket %s).", self.endpoint, self.bucket)
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("Object store unavailable (%s); artifacts stay on local disk.", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def publish_directory(self, local_dir: str | Path, prefix: str) -> list[dict]:
        """Upload every file in `local_dir` under `prefix`; return artifact records.

        A failure to publish is reported, not raised: the computation already succeeded and its
        results are on disk, so losing the upload must not turn a good run into a failed one.
        """
        if not self.enabled:
            return []

        local_dir = Path(local_dir)
        published: list[dict] = []
        for path in sorted(local_dir.rglob("*")):
            if not path.is_file():
                continue
            key = f"{prefix.strip('/')}/{path.relative_to(local_dir).as_posix()}"
            try:
                self._client.upload_file(str(path), self.bucket, key)
                published.append({
                    "key": key,
                    "size_bytes": path.stat().st_size,
                    "url": self._client.generate_presigned_url(
                        "get_object", Params={"Bucket": self.bucket, "Key": key},
                        ExpiresIn=self.expiry),
                    "expires_in_seconds": self.expiry,
                })
            except Exception as exc:  # pragma: no cover - environment dependent
                logger.warning("Failed to publish %s: %s", key, exc)
        return published
