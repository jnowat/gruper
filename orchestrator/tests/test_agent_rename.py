"""
Tests for PATCH /v1/agents/{id} — updating an agent's name and/or role.

Covers the happy paths (rename, role change, both at once), that updates are
reflected in GET /agents, that a role change replaces only capabilities.roles
(models/hardware untouched), and the owner-scoped isolation (a non-owner or a
bad id gets an indistinguishable 404).
"""

import base64
import secrets

from starlette.testclient import TestClient


def _rand_pubkey() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _capabilities() -> dict:
    return {
        "models": ["llama3.1:8b", "gemma3:4b"],
        "default_model": "gemma3:4b",
        "roles": ["philosopher"],
        "tools": [],
        "hardware": {"cpu_cores": 8, "ram_gb": 16},
    }


def _new_user(client: TestClient) -> str:
    resp = client.post("/v1/auth/token", json={"pubkey": _rand_pubkey(), "display_name": "U"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _register_agent(client: TestClient, token: str, name: str = "Local Agent") -> str:
    resp = client.post(
        "/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "pubkey": _rand_pubkey(),
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.1.0",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestAgentRename:
    def test_rename_updates_name(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token, "Local Agent")

        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "gemma3 · philosopher"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "gemma3 · philosopher"

        # Reflected in the list.
        listing = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
        names = {a["id"]: a["name"] for a in listing.json()}
        assert names[agent_id] == "gemma3 · philosopher"

    def test_rename_requires_auth(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        resp = client.patch(f"/v1/agents/{agent_id}", json={"name": "x"})
        assert resp.status_code in (401, 403)

    def test_rename_other_owners_agent_is_404(self, client: TestClient) -> None:
        owner = _new_user(client)
        agent_id = _register_agent(client, owner)

        other = _new_user(client)
        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {other}"},
            json={"name": "hijacked"},
        )
        # Indistinguishable from "not found" — no existence oracle.
        assert resp.status_code == 404, resp.text

        # And the real owner's agent is untouched.
        listing = client.get("/v1/agents", headers={"Authorization": f"Bearer {owner}"})
        names = {a["id"]: a["name"] for a in listing.json()}
        assert names[agent_id] == "Local Agent"

    def test_rename_bad_uuid_is_404(self, client: TestClient) -> None:
        token = _new_user(client)
        resp = client.patch(
            "/v1/agents/not-a-uuid",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "x"},
        )
        assert resp.status_code == 404

    def test_rename_empty_name_rejected(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": ""},
        )
        assert resp.status_code == 422


class TestAgentRoleUpdate:
    def test_role_update_replaces_primary_role(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "critic"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["capabilities"]["roles"] == ["critic"]
        # Everything else in capabilities is untouched.
        assert body["capabilities"]["models"] == ["llama3.1:8b", "gemma3:4b"]
        assert body["capabilities"]["default_model"] == "gemma3:4b"
        assert body["capabilities"]["hardware"] == {"cpu_cores": 8, "ram_gb": 16}
        # Name unchanged when only the role is patched.
        assert body["name"] == "Local Agent"

    def test_role_update_reflected_in_list(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "engineer"},
        )
        assert resp.status_code == 200, resp.text

        listing = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
        roles = {a["id"]: a["capabilities"]["roles"] for a in listing.json()}
        assert roles[agent_id] == ["engineer"]

    def test_name_and_role_together(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Sage", "role": "scientist"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Sage"
        assert body["capabilities"]["roles"] == ["scientist"]

    def test_empty_patch_rejected(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert resp.status_code == 422

    def test_empty_role_rejected(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": ""},
        )
        assert resp.status_code == 422

    def test_role_outside_contract_enum_rejected(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "wizard"},
        )
        assert resp.status_code == 422

    def test_role_update_preserves_secondary_roles(self, client: TestClient) -> None:
        token = _new_user(client)
        caps = _capabilities()
        caps["roles"] = ["philosopher", "critic"]
        resp = client.post(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Multi",
                "pubkey": _rand_pubkey(),
                "capabilities": caps,
                "runtime_version": "gd-0.1.0",
            },
        )
        assert resp.status_code == 201, resp.text
        agent_id = resp.json()["id"]

        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "creative"},
        )
        assert resp.status_code == 200, resp.text
        # roles[0] replaced, secondary roles intact (per the contract).
        assert resp.json()["capabilities"]["roles"] == ["creative", "critic"]

    def test_role_update_other_owners_agent_is_404(self, client: TestClient) -> None:
        owner = _new_user(client)
        agent_id = _register_agent(client, owner)

        other = _new_user(client)
        resp = client.patch(
            f"/v1/agents/{agent_id}",
            headers={"Authorization": f"Bearer {other}"},
            json={"role": "critic"},
        )
        assert resp.status_code == 404, resp.text

        listing = client.get("/v1/agents", headers={"Authorization": f"Bearer {owner}"})
        roles = {a["id"]: a["capabilities"]["roles"] for a in listing.json()}
        assert roles[agent_id] == ["philosopher"]
