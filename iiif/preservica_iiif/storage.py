"""Where tiles and manifests go: S3 in AWS, or a local folder for trying the pipeline out."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


class LocalStore:
    """Two folders standing in for the tiles and manifest buckets. Metadata sits in <key>.meta.json."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.tiles = self.root / "tiles"
        self.public = self.root / "public"
        self.tiles.mkdir(parents=True, exist_ok=True)
        self.public.mkdir(parents=True, exist_ok=True)

    def put_tile(self, key: str, path: str) -> None:
        shutil.copyfile(path, self.tiles / key)

    def list_tiles(self, prefix: str) -> list[str]:
        return sorted(p.name for p in self.tiles.glob(f"{prefix}*") if p.is_file())

    def delete_tiles(self, keys: list[str]) -> None:
        for k in keys:
            (self.tiles / k).unlink(missing_ok=True)

    def put_json(self, key: str, obj: dict, metadata: dict | None = None) -> None:
        p = self.public / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        Path(f"{p}.meta.json").write_text(json.dumps(metadata or {}), encoding="utf-8")

    def get_json(self, key: str) -> dict | None:
        p = self.public / key
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def head(self, key: str) -> dict | None:
        p = Path(f"{self.public / key}.meta.json")
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def list_json(self, prefix: str) -> list[str]:
        base = self.public / prefix
        if not base.exists():
            return []
        return sorted(f"{prefix}{p.name}" for p in base.glob("*.json") if not p.name.endswith(".meta.json"))

    def delete_json(self, keys: list[str]) -> None:
        for k in keys:
            (self.public / k).unlink(missing_ok=True)
            Path(f"{self.public / k}.meta.json").unlink(missing_ok=True)

    def invalidate(self, paths: list[str]) -> None:
        pass


class S3Store:
    """Tiles in one bucket (serverless-iiif's source), manifests and status files in another (behind CloudFront)."""

    def __init__(self, tiles_bucket: str, public_bucket: str, distribution_id: str | None = None, s3=None, cloudfront=None):
        import boto3

        self.s3 = s3 or boto3.client("s3")
        self.cf = cloudfront or (boto3.client("cloudfront") if distribution_id else None)
        self.tiles_bucket, self.public_bucket, self.distribution_id = tiles_bucket, public_bucket, distribution_id

    def put_tile(self, key: str, path: str) -> None:
        self.s3.upload_file(path, self.tiles_bucket, key, ExtraArgs={"ContentType": "image/tiff"})

    def _list(self, bucket: str, prefix: str) -> list[str]:
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)

    def _delete(self, bucket: str, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):
            self.s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]],
                                                          "Quiet": True})

    def list_tiles(self, prefix: str) -> list[str]:
        return self._list(self.tiles_bucket, prefix)

    def delete_tiles(self, keys: list[str]) -> None:
        self._delete(self.tiles_bucket, keys)

    def put_json(self, key: str, obj: dict, metadata: dict | None = None) -> None:
        self.s3.put_object(Bucket=self.public_bucket, Key=key, ContentType="application/json",
                           CacheControl="public, max-age=3600",
                           Body=json.dumps(obj, ensure_ascii=False).encode("utf-8"), Metadata=metadata or {})

    def get_json(self, key: str) -> dict | None:
        try:
            return json.loads(self.s3.get_object(Bucket=self.public_bucket, Key=key)["Body"].read())
        except self.s3.exceptions.NoSuchKey:
            return None

    def head(self, key: str) -> dict | None:
        from botocore.exceptions import ClientError

        try:
            return self.s3.head_object(Bucket=self.public_bucket, Key=key).get("Metadata", {})
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def list_json(self, prefix: str) -> list[str]:
        return [k for k in self._list(self.public_bucket, prefix) if k.endswith(".json")]

    def delete_json(self, keys: list[str]) -> None:
        self._delete(self.public_bucket, keys)

    def invalidate(self, paths: list[str]) -> None:
        """Drop withdrawn items from CloudFront's cache straight away rather than waiting for it to expire."""
        if not (self.cf and self.distribution_id and paths):
            return
        self.cf.create_invalidation(DistributionId=self.distribution_id, InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths}, "CallerReference": f"withdraw-{time.time_ns()}"})
