"""Settings come from environment variables (set by the CloudFormation template).

Secrets (the Preservica password, the webhook secret) are read from AWS Secrets Manager
when a *_SECRET_ARN variable is set, or from the plain variable for local runs.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# Bump when the conversion or the manifest changes, so the next run rebuilds everything.
PIPELINE_VERSION = "1"


def _list(value: str | None, default: list[str]) -> list[str]:
    if value is None or not value.strip():
        return list(default)
    return [v.strip() for v in value.split(",") if v.strip()]


def read_secret(arn_var: str, plain_var: str, key: str | None = None) -> str | None:
    """The secret from Secrets Manager (plain string, or a JSON object's `key`), else the plain variable."""
    arn = os.environ.get(arn_var)
    if not arn:
        return os.environ.get(plain_var)
    import boto3

    value = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
    if key:
        try:
            obj = json.loads(value)
        except ValueError:
            return value
        if isinstance(obj, dict):
            return obj.get(key)
    return value


@dataclass
class Settings:
    public_base_url: str                       # e.g. https://iiif.lib.uni.edu
    image_api_base: str = ""                   # default {public_base_url}/iiif/3
    manifest_prefix: str = "manifests/"
    status_prefix: str = "status/"
    public_security_tags: list[str] = field(default_factory=lambda: ["open"])
    representation_order: list[str] = field(default_factory=lambda: ["Access", "Preservation"])
    root_folders: list[str] = field(default_factory=list)   # empty = the whole repository
    landing_url_template: str = ""
    attribution: str = "Rod Library, University of Northern Iowa"
    provider_label: str = "Rod Library, University of Northern Iowa"
    provider_homepage: str = "https://library.uni.edu/"
    max_source_bytes: int = 3 * 1024 ** 3      # larger files go to the CLI on a bigger machine
    max_delete_fraction: float = 0.1
    tile_size: int = 256
    jpeg_quality: int = 90

    def __post_init__(self):
        self.public_base_url = self.public_base_url.rstrip("/")
        if not self.image_api_base:
            self.image_api_base = f"{self.public_base_url}/iiif/3"
        self.image_api_base = self.image_api_base.rstrip("/")

    @property
    def image_api_version(self) -> int:
        return 2 if "/iiif/2" in self.image_api_base else 3

    def manifest_key(self, ref: str) -> str:
        return f"{self.manifest_prefix}{ref}.json"

    def manifest_url(self, ref: str) -> str:
        return f"{self.public_base_url}/{self.manifest_key(ref)}"

    def status_key(self, ref: str) -> str:
        return f"{self.status_prefix}{ref}.json"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            public_base_url=env["PUBLIC_BASE_URL"],
            image_api_base=env.get("IIIF_IMAGE_API_BASE", ""),
            public_security_tags=_list(env.get("PUBLIC_SECURITY_TAGS"), ["open"]),
            representation_order=_list(env.get("REPRESENTATION_ORDER"), ["Access", "Preservation"]),
            root_folders=_list(env.get("ROOT_FOLDERS"), []),
            landing_url_template=env.get("LANDING_URL_TEMPLATE", ""),
            attribution=env.get("ATTRIBUTION", cls.attribution),
            max_source_bytes=int(env.get("MAX_SOURCE_BYTES", cls.max_source_bytes)),
            max_delete_fraction=float(env.get("MAX_DELETE_FRACTION", cls.max_delete_fraction)),
        )
