# SPDX-License-Identifier: MIT
# CI Engine - S3 Artifact Storage

import os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from aiobotocore.session import get_session
from botocore.exceptions import ClientError


class ArtifactStorageError(Exception):
    """Base exception for artifact storage errors."""

    pass


class ArtifactNotFoundError(ArtifactStorageError):
    """Artifact not found in storage."""

    pass


class ArtifactUploadError(ArtifactStorageError):
    """Failed to upload artifact."""

    pass


class ArtifactDownloadError(ArtifactStorageError):
    """Failed to download artifact."""

    pass


@dataclass
class UploadResult:
    """Result of artifact upload."""

    key: str
    storage_location: str
    size: int


@dataclass
class ArtifactMetadata:
    """Metadata for stored artifacts."""

    key: str
    size: int
    content_type: str
    created_at: datetime
    build_id: int
    job_id: Optional[int]
    checksum: Optional[str] = None


class S3ArtifactStorage:
    """Async S3 artifact storage for CI build artifacts."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        prefix: str = "ci-artifacts",
    ):
        self.bucket = bucket or os.environ.get("CI_ENGINE_S3_BUCKET", "ci-engine-artifacts")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.prefix = prefix
        self._session = get_session()
        self._client = None

    async def _get_client(self):
        """Get or create S3 client."""
        if self._client is None:
            self._client = await self._session.create_client(
                "s3",
                region_name=self.region,
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
            )
        return self._client

    async def close(self):
        """Close the S3 client."""
        if self._client:
            await self._client.close()
            self._client = None

    def _make_key(self, build_id: int, job_id: Optional[int], filename: str) -> str:
        """Generate S3 key for artifact."""
        if job_id:
            return f"{self.prefix}/builds/{build_id}/jobs/{job_id}/{filename}"
        return f"{self.prefix}/builds/{build_id}/{filename}"

    async def upload_artifact(
        self,
        data: bytes,
        build_id: int,
        job_id: Optional[int],
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> UploadResult:
        """Upload artifact to S3."""
        client = await self._get_client()
        key = self._make_key(build_id, job_id, filename)

        try:
            await client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={
                    "build_id": str(build_id),
                    "job_id": str(job_id) if job_id else "",
                    "original_filename": filename,
                },
            )
            return UploadResult(
                key=key,
                storage_location=f"s3://{self.bucket}/{key}",
                size=len(data),
            )
        except ClientError as e:
            raise ArtifactUploadError(f"Failed to upload artifact: {e}") from e

    async def download_artifact(
        self,
        build_id: int,
        job_id: Optional[int],
        filename: str,
    ) -> bytes:
        """Download artifact from S3."""
        client = await self._get_client()
        key = self._make_key(build_id, job_id, filename)

        try:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                data = await stream.read()
            return data
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                raise ArtifactNotFoundError(f"Artifact not found: {key}") from e
            raise ArtifactDownloadError(f"Failed to download artifact: {e}") from e

    async def list_artifacts(
        self,
        build_id: int,
        job_id: Optional[int] = None,
    ) -> list[ArtifactMetadata]:
        """List artifacts for a build/job."""
        client = await self._get_client()

        if job_id:
            prefix = f"{self.prefix}/builds/{build_id}/jobs/{job_id}/"
        else:
            prefix = f"{self.prefix}/builds/{build_id}/"

        try:
            response = await client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
            )

            artifacts = []
            for obj in response.get("Contents", []):
                key = obj["Key"]
                artifacts.append(
                    ArtifactMetadata(
                        key=key,
                        size=obj["Size"],
                        content_type=obj.get("ContentType", "application/octet-stream"),
                        created_at=obj["LastModified"],
                        build_id=build_id,
                        job_id=job_id,
                        checksum=obj.get("ETag", "").strip('"'),
                    )
                )

            return artifacts
        except ClientError as e:
            raise ArtifactStorageError(f"Failed to list artifacts: {e}") from e

    async def delete_artifact(
        self,
        build_id: int,
        job_id: Optional[int],
        filename: str,
    ) -> None:
        """Delete artifact from S3."""
        client = await self._get_client()
        key = self._make_key(build_id, job_id, filename)

        try:
            await client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            raise ArtifactStorageError(f"Failed to delete artifact: {e}") from e

    async def delete_build_artifacts(self, build_id: int) -> int:
        """Delete all artifacts for a build. Returns count of deleted objects."""
        client = await self._get_client()
        prefix = f"{self.prefix}/builds/{build_id}/"

        try:
            response = await client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            objects = response.get("Contents", [])

            if not objects:
                return 0

            delete_keys = [{"Key": obj["Key"]} for obj in objects]

            await client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": delete_keys},
            )

            return len(delete_keys)
        except ClientError as e:
            raise ArtifactStorageError(f"Failed to delete build artifacts: {e}") from e

    async def get_presigned_url(
        self,
        build_id: int,
        job_id: Optional[int],
        filename: str,
        expires_in: int = 3600,
    ) -> str:
        """Generate presigned URL for downloading artifact."""
        client = await self._get_client()
        key = self._make_key(build_id, job_id, filename)

        try:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        except ClientError as e:
            raise ArtifactStorageError(f"Failed to generate presigned URL: {e}") from e


_storage: Optional[S3ArtifactStorage] = None


def get_artifact_storage() -> S3ArtifactStorage:
    """Get the artifact storage singleton."""
    global _storage
    if _storage is None:
        _storage = S3ArtifactStorage()
    return _storage
