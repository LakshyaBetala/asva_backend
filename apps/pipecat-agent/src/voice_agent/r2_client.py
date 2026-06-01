"""Cloudflare R2 client implementing the R2Reader / R2Writer protocols
used by intro_cache and phrase_cache.

R2 is S3-compatible, so we use boto3 with a custom endpoint. We wrap the
blocking boto3 calls in asyncio.to_thread() so the audio loop never blocks.

Environment expected:
  R2_ENDPOINT          = https://<account>.r2.cloudflarestorage.com
  R2_ACCESS_KEY_ID     = <s3-style key>
  R2_SECRET_ACCESS_KEY = <s3-style secret>
  R2_BUCKET            = ai-voice-intro-cache
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # avoid the import cost at module load; boto3 is heavy.
    from botocore.client import BaseClient


@dataclass
class R2Config:
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    region: str = "auto"  # Cloudflare R2 uses "auto"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "R2Config":
        env = env or os.environ  # type: ignore[assignment]
        try:
            return cls(
                endpoint_url=env["R2_ENDPOINT"],
                access_key_id=env["R2_ACCESS_KEY_ID"],
                secret_access_key=env["R2_SECRET_ACCESS_KEY"],
                bucket=env["R2_BUCKET"],
                region=env.get("R2_REGION", "auto"),
            )
        except KeyError as exc:
            raise R2ConfigError(f"missing env var: {exc.args[0]}") from exc


class R2ConfigError(RuntimeError):
    """Missing or invalid R2 configuration."""


class R2Client:
    """Async R2 reader+writer satisfying the R2Reader and R2Writer protocols.

    Construction is lazy (boto3 client created on first call) so importing
    this module is cheap and unit tests can inject a fake _s3.
    """

    def __init__(self, config: R2Config, *, s3_client: Optional[Any] = None) -> None:
        self._cfg = config
        self._s3 = s3_client  # injectable for tests

    def _client(self) -> Any:
        if self._s3 is not None:
            return self._s3
        import boto3  # local import — boto3 is heavy.
        from botocore.config import Config

        self._s3 = boto3.client(
            "s3",
            endpoint_url=self._cfg.endpoint_url,
            aws_access_key_id=self._cfg.access_key_id,
            aws_secret_access_key=self._cfg.secret_access_key,
            region_name=self._cfg.region,
            config=Config(
                signature_version="s3v4",
                # Telephony-friendly timeouts: fail fast so we fall through
                # to live TTS instead of stalling the call.
                connect_timeout=2,
                read_timeout=4,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )
        return self._s3

    async def get(self, key: str) -> bytes | None:
        """Return object bytes or None if the key does not exist.

        404 / NoSuchKey is treated as a cache miss, NOT an error — the
        whole point of the cache layer is to fall through gracefully.
        """

        def _blocking() -> bytes | None:
            try:
                resp = self._client().get_object(Bucket=self._cfg.bucket, Key=key)
                return resp["Body"].read()
            except Exception as exc:
                if _is_not_found(exc):
                    return None
                raise

        return await asyncio.to_thread(_blocking)

    async def put(
        self, key: str, body: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        def _blocking() -> None:
            self._client().put_object(
                Bucket=self._cfg.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )

        await asyncio.to_thread(_blocking)

    async def head_exists(self, key: str) -> bool:
        def _blocking() -> bool:
            try:
                self._client().head_object(Bucket=self._cfg.bucket, Key=key)
                return True
            except Exception as exc:
                if _is_not_found(exc):
                    return False
                raise

        return await asyncio.to_thread(_blocking)

    async def delete(self, key: str) -> None:
        def _blocking() -> None:
            self._client().delete_object(Bucket=self._cfg.bucket, Key=key)

        await asyncio.to_thread(_blocking)


def _is_not_found(exc: BaseException) -> bool:
    """Detect a 404 / NoSuchKey across boto3 exception shapes.

    boto3 raises ClientError with response['Error']['Code'] but the
    code varies ('NoSuchKey', '404', 'NotFound'). We avoid importing
    botocore at module top.
    """
    # Best-effort string scan that works whether or not botocore is loaded.
    code = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = ((response.get("Error") or {}).get("Code") or "").lower()
    if code in {"nosuchkey", "404", "notfound"}:
        return True
    # Fall back to type name + message scan.
    msg = f"{type(exc).__name__}:{exc}".lower()
    return "nosuchkey" in msg or "not found" in msg or "404" in msg
