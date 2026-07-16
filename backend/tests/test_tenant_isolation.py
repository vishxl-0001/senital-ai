"""
Phase 1 verification — trust boundary / tenant isolation.

Proves the dashboard-facing routes derive tenant_id from the *verified* Clerk
session JWT (org_id claim) and scope every read/write to that tenant, so a
token for tenant B can never see or mutate tenant A's data.

Covered:
  • A creates an incident → A can read it, B gets 404 (read isolation)
  • B cannot approve A's fix → 404 (write isolation)
  • Listing is tenant-scoped (A's incident absent from B's list)
  • Policies are tenant-scoped the same way
  • Missing token → 401, valid token without an org → 403
  • Expired / tampered tokens → 401 (real signature + expiry verification)
"""

from tests.conftest import auth

from app.models.incident import Incident, IncidentStatus, Severity

ORG_A = "org_AAAAAAAAAAAAAAAAAAAAAAA"
ORG_B = "org_BBBBBBBBBBBBBBBBBBBBBBB"

# Per-tenant incident number counters so seeded rows satisfy the
# (tenant_id, incident_number) unique constraint.
_counters: dict = {}


async def _seed_incident(db_session, tenant_id: str, title: str) -> str:
    _counters[tenant_id] = _counters.get(tenant_id, 0) + 1
    inc = Incident(
        tenant_id=tenant_id,
        incident_number=_counters[tenant_id],
        title=title,
        source="test",
        status=IncidentStatus.FIX_PROPOSED,
        severity=Severity.HIGH,
    )
    db_session.add(inc)
    await db_session.commit()
    await db_session.refresh(inc)
    return str(inc.id)


# ── Core isolation: A's incident is invisible to B ─────────────────────────

async def test_incident_read_is_tenant_isolated(client, db_session, make_token):
    iid = await _seed_incident(db_session, ORG_A, "A's confidential incident")
    token_a = make_token(org_id=ORG_A)
    token_b = make_token(org_id=ORG_B)

    # Tenant A (the owner) can read it.
    r = await client.get(f"/api/v1/incidents/{iid}", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == iid

    # Tenant B must NOT be able to read it.
    r = await client.get(f"/api/v1/incidents/{iid}", headers=auth(token_b))
    assert r.status_code == 404, r.text


async def test_incident_write_is_tenant_isolated(client, db_session, make_token):
    iid = await _seed_incident(db_session, ORG_A, "A's incident pending approval")
    token_b = make_token(org_id=ORG_B)

    # Tenant B must NOT be able to approve/execute A's fix.
    r = await client.post(f"/api/v1/incidents/{iid}/approve-fix", headers=auth(token_b))
    assert r.status_code == 404, r.text


async def test_incident_list_is_tenant_scoped(client, db_session, make_token):
    iid = await _seed_incident(db_session, ORG_A, "A-only listing incident")
    token_a = make_token(org_id=ORG_A)
    token_b = make_token(org_id=ORG_B)

    r = await client.get("/api/v1/incidents", headers=auth(token_b))
    assert r.status_code == 200, r.text
    assert iid not in [i["id"] for i in r.json()["incidents"]]

    r = await client.get("/api/v1/incidents", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert iid in [i["id"] for i in r.json()["incidents"]]


async def test_policies_are_tenant_scoped(client, make_token):
    token_a = make_token(org_id=ORG_A)
    token_b = make_token(org_id=ORG_B)

    r = await client.post(
        "/api/v1/policies/",
        json={"name": "A-secret-policy", "action_type": "restart_pod"},
        headers=auth(token_a),
    )
    assert r.status_code == 200, r.text

    # B cannot see A's policy.
    r = await client.get("/api/v1/policies", headers=auth(token_b))
    assert r.status_code == 200, r.text
    assert "A-secret-policy" not in [p["name"] for p in r.json()["policies"]]

    # A can.
    r = await client.get("/api/v1/policies", headers=auth(token_a))
    assert "A-secret-policy" in [p["name"] for p in r.json()["policies"]]


# ── Auth boundary: the verifier actually verifies ──────────────────────────

async def test_missing_token_is_401(client):
    r = await client.get("/api/v1/incidents")
    assert r.status_code == 401, r.text


async def test_token_without_org_is_403(client, make_token):
    # Authenticated user, but no active organization → no tenant context.
    token = make_token(omit_org=True, sub="user_without_org")
    r = await client.get("/api/v1/incidents", headers=auth(token))
    assert r.status_code == 403, r.text


async def test_v2_session_token_org_claim(client, make_token, rsa_keypair):
    # Clerk session token v2 (API 2025-04-10+) nests the active org under the
    # compact `o` claim (o.id) instead of a top-level org_id.
    from datetime import datetime, timedelta, timezone
    from jose import jwt as jose_jwt
    from tests.conftest import TEST_ISSUER

    now = datetime.now(timezone.utc)
    token = jose_jwt.encode(
        {
            "iss": TEST_ISSUER,
            "sub": "user_v2",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "o": {"id": ORG_A, "slg": "org-a", "rol": "admin"},
        },
        rsa_keypair["private"],
        algorithm="RS256",
        headers={"kid": rsa_keypair["kid"]},
    )
    r = await client.get("/api/v1/incidents", headers=auth(token))
    assert r.status_code == 200, r.text


async def test_expired_token_is_401(client, make_token):
    token = make_token(org_id=ORG_A, expired=True)
    r = await client.get("/api/v1/incidents", headers=auth(token))
    assert r.status_code == 401, r.text


async def test_tampered_token_is_401(client, make_token):
    token = make_token(org_id=ORG_A)
    # Flip the last few payload chars → signature no longer matches.
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    r = await client.get("/api/v1/incidents", headers=auth(tampered))
    assert r.status_code == 401, r.text


async def test_wrong_issuer_is_401(client, make_token):
    # Correctly signed by our key, but with an issuer we don't trust.
    token = make_token(org_id=ORG_A, issuer="https://evil.example.com")
    r = await client.get("/api/v1/incidents", headers=auth(token))
    assert r.status_code == 401, r.text
