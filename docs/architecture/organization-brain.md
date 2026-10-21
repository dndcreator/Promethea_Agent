# Organization Brain

The Organization Brain is an optional Promethea component. It provides governed organization context without changing ownership of personal Memory or Python Core services.

## Authority Boundaries

```text
Organization membership and roles
        -> source documents and revisions
        -> review and publication
        -> governed knowledge items
        -> optional Neo4j graph projection
        -> passive prompt context / organization.recall
```

- `OrgBrainStore` is the authority for organizations, membership, source lineage, review state, portable knowledge, and audit records.
- `OrgContextService` owns extraction, retrieval, graph projection, and prompt-facing organization context.
- Neo4j is an optional, rebuildable graph projection. Switching a personal Memory backend does not change organization identity or lineage.
- Personal Memory and organization knowledge never dual-write. `context_only` collaboration exposes separate bounded prompt blocks; `off` suppresses personal recall when organization context is active.

## Lifecycle

1. Enabling `org_brain` and selecting an `org_id` activates the component for that user.
2. The first authorized user creates the organization authority and becomes its owner.
3. Ingest creates a checksum-addressed document revision and extracted knowledge proposals.
4. With `confirmation_queue=true`, proposals remain unavailable to recall until an owner or administrator approves the revision.
5. Publishing a newer revision supersedes previously published knowledge from that document.
6. Revoking a document removes its knowledge from governed recall and its graph projection.

Roles are `owner`, `admin`, `editor`, and `reader`. Optional audience scopes further restrict recall. A request cannot select an organization different from the user's configured organization.

## Portability

`GET /api/org-brain/export` returns a versioned JSON bundle with stable ordering and a SHA-256 integrity checksum. It contains source revisions and governed knowledge, but no passwords, provider keys, tokens, or personal Memory. `POST /api/org-brain/import` validates the checksum and can restore the bundle under another organization id; the importing user becomes the target owner.

Runtime data is stored under `config/users/org_brain.sqlite3` and is excluded from source control.
