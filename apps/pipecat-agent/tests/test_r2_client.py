"""Tests for the R2 client.

We do NOT spin up real R2 here — boto3 is mocked via a stub client.
This lets us test the asyncio.to_thread wrap, not-found handling, and
the protocol surface intro_cache/phrase_cache depend on.
"""
from __future__ import annotations

import io

import pytest

from voice_agent.r2_client import (
    R2Client,
    R2Config,
    R2ConfigError,
    _is_not_found,
)


class FakeS3:
    """Minimal stub mirroring boto3's S3 surface for get_object/put_object/head_object."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, str, bytes, str]] = []  # bucket, key, body, ct
        self.delete_calls: list[tuple[str, str]] = []

    # Synchronous on purpose: R2Client wraps in to_thread.
    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        if Key not in self.store:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.store[Key])}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str):  # noqa: N803
        self.put_calls.append((Bucket, Key, Body, ContentType))
        self.store[Key] = Body

    def head_object(self, Bucket: str, Key: str):  # noqa: N803
        if Key not in self.store:
            raise FakeClientError("NoSuchKey")
        return {"ContentLength": len(self.store[Key])}

    def delete_object(self, Bucket: str, Key: str):  # noqa: N803
        self.delete_calls.append((Bucket, Key))
        self.store.pop(Key, None)


class FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError's shape."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def _config() -> R2Config:
    return R2Config(
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        access_key_id="ak",
        secret_access_key="sk",
        bucket="ai-voice-intro-cache",
    )


def test_is_not_found_detects_nosuchkey():
    assert _is_not_found(FakeClientError("NoSuchKey")) is True
    assert _is_not_found(FakeClientError("404")) is True
    assert _is_not_found(FakeClientError("AccessDenied")) is False


def test_config_from_env_reads_required_keys():
    cfg = R2Config.from_env(
        {
            "R2_ENDPOINT": "https://e",
            "R2_ACCESS_KEY_ID": "k",
            "R2_SECRET_ACCESS_KEY": "s",
            "R2_BUCKET": "b",
        }
    )
    assert cfg.bucket == "b"
    assert cfg.region == "auto"


def test_config_from_env_raises_on_missing():
    with pytest.raises(R2ConfigError, match="R2_BUCKET"):
        R2Config.from_env({"R2_ENDPOINT": "https://e", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s"})


@pytest.mark.asyncio
async def test_put_then_get_roundtrips_bytes():
    fake = FakeS3()
    client = R2Client(_config(), s3_client=fake)
    await client.put("phrase/hi-IN/abc.mp3", b"WAV-BYTES", "audio/mpeg")
    out = await client.get("phrase/hi-IN/abc.mp3")
    assert out == b"WAV-BYTES"
    assert fake.put_calls[0][1] == "phrase/hi-IN/abc.mp3"
    assert fake.put_calls[0][3] == "audio/mpeg"


@pytest.mark.asyncio
async def test_get_returns_none_on_not_found_instead_of_raising():
    fake = FakeS3()
    client = R2Client(_config(), s3_client=fake)
    out = await client.get("missing.mp3")
    assert out is None


@pytest.mark.asyncio
async def test_head_exists_returns_true_only_when_present():
    fake = FakeS3()
    client = R2Client(_config(), s3_client=fake)
    assert await client.head_exists("missing.mp3") is False
    await client.put("present.mp3", b"x", "audio/mpeg")
    assert await client.head_exists("present.mp3") is True


@pytest.mark.asyncio
async def test_delete_removes_object():
    fake = FakeS3()
    client = R2Client(_config(), s3_client=fake)
    await client.put("k", b"v", "application/octet-stream")
    await client.delete("k")
    assert "k" not in fake.store
    assert fake.delete_calls == [("ai-voice-intro-cache", "k")]


@pytest.mark.asyncio
async def test_get_propagates_non_notfound_errors():
    class AngryS3:
        def get_object(self, Bucket, Key):  # noqa: N803
            raise FakeClientError("AccessDenied")

    client = R2Client(_config(), s3_client=AngryS3())
    with pytest.raises(FakeClientError):
        await client.get("k")
