from __future__ import annotations

import pytest

from gateway.org_brain_store import OrgBrainStore
from gateway.org_context_service import OrgContextService


def test_membership_roles_enforce_organization_boundary(tmp_path):
    store = OrgBrainStore(tmp_path / "org.sqlite3")
    store.ensure_organization(org_id="acme", owner_user_id="owner")
    store.upsert_member(org_id="acme", actor_user_id="owner", user_id="reader", role="reader", audiences=["board"])

    assert store.require_access(org_id="acme", user_id="reader")["role"] == "reader"
    with pytest.raises(PermissionError):
        store.require_access(org_id="acme", user_id="reader", write=True)
    with pytest.raises(PermissionError):
        store.require_access(org_id="acme", user_id="outsider")


@pytest.mark.asyncio
async def test_reviewed_revision_is_only_recalled_after_approval(tmp_path):
    store = OrgBrainStore(tmp_path / "org.sqlite3")
    service = OrgContextService(store=store)
    config = {
        "org_brain": {
            "enabled": True,
            "org_id": "acme",
            "confirmation_queue": True,
        }
    }
    result = await service.ingest_document(
        org_id="acme",
        user_id="owner",
        source_doc_id="policy",
        text="Travel policy: approval is required before booking.",
        audience="staff",
        register="formal",
        use_llm=False,
        user_config=config,
    )
    assert result["accepted"] == 0
    assert result["pending_review"] == 1

    before = await service.recall_for_turn(query="Travel policy", user_id="owner", user_config=config)
    assert before["recalled"] is False

    await service.review_revision(
        org_id="acme",
        user_id="owner",
        revision_id=result["revision"]["revision_id"],
        approve=True,
    )
    after = await service.recall_for_turn(query="Travel policy", user_id="owner", user_config=config)
    assert after["recalled"] is True
    assert after["items"][0]["source_name"] == "policy"


@pytest.mark.asyncio
async def test_bundle_round_trip_preserves_published_knowledge(tmp_path):
    source = OrgContextService(store=OrgBrainStore(tmp_path / "source.sqlite3"))
    config = {"org_brain": {"enabled": True, "org_id": "acme", "confirmation_queue": False}}
    await source.ingest_document(
        org_id="acme",
        user_id="owner",
        source_doc_id="style-guide",
        text="Executive summaries: begin with the decision and supporting evidence.",
        audience="board",
        register="concise",
        use_llm=False,
        user_config=config,
    )
    bundle = source.export_bundle(org_id="acme", user_id="owner")

    target = OrgContextService(store=OrgBrainStore(tmp_path / "target.sqlite3"))
    imported = target.import_bundle(bundle=bundle, user_id="new-owner", target_org_id="restored")
    assert imported["documents"] == 1
    recalled = await target.recall_org_context(
        org_id="restored",
        topic="Executive summaries",
        audience="board",
        context_type="writing",
        top_k=5,
        user_id="new-owner",
    )
    assert recalled["recalled"] is True

    bundle["data"]["knowledge_items"][0]["expression"] = "tampered"
    with pytest.raises(ValueError, match="checksum"):
        target.import_bundle(bundle=bundle, user_id="new-owner", target_org_id="tampered")
