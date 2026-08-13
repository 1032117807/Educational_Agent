from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ResourceFile
from server.storage import ObjectStorage
from server.tenant_session import set_session_tenant


def index_resource_from_object_store(
    *,
    payload: dict[str, object],
    session_factory: Callable[[], Session],
    storage: ObjectStorage,
    pipeline_factory: Callable[[Path, str], object],
) -> dict[str, object]:
    """Download an authorized object to an isolated temporary workspace, then index it.

    `pipeline_factory` keeps the current parser/splitter pipeline reusable while
    the SaaS worker controls all object storage access and tenant validation.
    """
    resource_id = int(payload["resource_id"])
    tenant_id = str(payload["tenant_id"])
    with session_factory() as session:
        set_session_tenant(session, tenant_id)
        resource = session.scalar(
            select(ResourceFile).where(
                ResourceFile.id == resource_id,
                ResourceFile.tenant_id == tenant_id,
                ResourceFile.trashed.is_(False),
            )
        )
        if resource is None:
            raise ValueError("resource not found in tenant")
        object_key = resource.relative_path
        filename = Path(resource.name).name

    with tempfile.TemporaryDirectory(prefix="learning-index-") as temporary:
        workspace = Path(temporary)
        destination = workspace / filename
        storage.download_to(key=object_key, destination=destination)
        result = pipeline_factory(workspace, tenant_id).index_resource(
            resource_id,
            source_path_override=destination,
        )
    return {"resource_id": resource_id, "document_index_id": result.document_index_id, "chunk_count": result.chunk_count}
