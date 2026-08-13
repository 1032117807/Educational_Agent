from server.storage import resource_key


def test_resource_key_is_tenant_scoped_and_discards_path_components() -> None:
    key = resource_key(
        tenant_id="tenant-1",
        resource_id="resource-1",
        filename="../../chemistry notes.pdf",
    )
    assert key == "tenant-1/resources/resource-1/chemistry_notes.pdf"
