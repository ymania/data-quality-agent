"""Real Docker integration check. Creates and removes ONLY its own temporary stack.

Run from the unpacked project: python3 scripts/verify_docker.py
No API key is needed. This checks deployment + real MySQL, not LLM inference.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = "dq-verify-" + secrets.token_hex(6)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("DQ_")}
    with tempfile.TemporaryDirectory(prefix="dq-docker-test-") as directory:
        config = Path(directory) / "config.env"
        config.write_text(f"DQ_DB_PASSWORD={secrets.token_hex(32)}\nDQ_ROOT_PASSWORD={secrets.token_hex(32)}\nDQ_HTTP_PORT={port}\n")
        config.chmod(0o600)
        compose = ["docker", "compose", "-p", project, "--env-file", str(config), "-f", str(ROOT / "compose.yaml")]

        image = os.getenv("DQ_VERIFY_IMAGE")
        if image:
            override = Path(directory) / "image.json"
            override.write_text(json.dumps({"services": {"agent": {"image": image}}}))
            compose.extend(["-f", str(override)])

        def run(*args):
            subprocess.run([*compose, *args], cwd=ROOT, env=env, check=True, timeout=3600)

        def sql(statement):
            # Only fixed test SQL is sent to this isolated, newly created database.
            code = "from app import settings; from app.db import connect; c=connect(); c.cursor().execute(" + repr(statement) + "); c.commit(); c.close()"
            run("exec", "-T", "agent", "python", "-c", code)

        opener = build_opener(ProxyHandler({}))

        def api(path, body=None):
            req = Request(f"http://127.0.0.1:{port}{path}",
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
            with opener.open(req, timeout=15) as response:
                return json.load(response)

        def ready():
            for _ in range(60):
                try:
                    if api("/api/health")["database"] == "ok":
                        return
                except (OSError, URLError, ValueError):
                    pass
                time.sleep(2)
            raise AssertionError("API/database did not become ready")

        def counts(result, expected):
            assert result["status"] == "SUCCEEDED", result
            assert tuple(result[k] for k in ("total_count", "checked_count", "passed_count", "failed_count", "skipped_count")) == expected, result

        print(f"Isolated Docker verification: {project}, port {port}", flush=True)
        try:
            run("config", "--quiet")
            run("up", "--no-build" if image else "--build", "-d", "--quiet-pull", "--wait", "--wait-timeout", "180")
            ready()
            run("cp", str(ROOT / "tests"), "agent:/tmp/tests")
            run("exec", "-T", "-e", "PYTHONPATH=/app", "agent", "python", "-m", "pytest", "/tmp/tests/test_uploads.py", "/tmp/tests/test_acceptance.py", "/tmp/tests/test_agent_resilience.py", "/tmp/tests/test_bruteforce_regressions.py", "-q", "-p", "no:cacheprovider")
            assert api("/api/settings/test-database", {})["demo_orders"] == 20
            assert not api("/api/settings")["model_api_key_set"]
            session = "docker-verification"
            rule_ids = []
            for column, kind, params in (("customer_name", "NOT_NULL", {}),
                                         ("order_status", "ENUM", {"allowed_values": ["NEW", "PAID", "CANCELLED"]})):
                created = api("/api/rules", {"name": "Docker " + kind, "table_name": "demo_orders", "column_name": column,
                                              "rule_type": kind, "params": params, "session_id": session})
                rule_ids.append(created["rule_id"])
            first = [api(f"/api/rules/{rid}/run", {"session_id": session}) for rid in rule_ids]
            counts(first[0], (20, 20, 17, 3, 0))
            counts(first[1], (20, 19, 17, 2, 1))
            assert [s["order_id"] for s in first[0]["samples"]] == [1, 2, 3]
            assert [s["order_id"] for s in first[1]["samples"]] == [4, 5]
            assert [s["field_value"] for s in first[0]["samples"]] == [None, "", "   "]
            assert [s["field_value"] for s in first[1]["samples"]] == ["UNKNOWN", "REFUNDED"]
            assert [result["pass_rate"] for result in first] == ["85.00", "89.47"]
            uploaded_before = api("/api/datasets")
            snapshots = [api(f'/api/results/{result["execution_id"]}') for result in first]
            print("PASS fresh database: 20 orders; failures 3 / 2 and correct sample IDs", flush=True)

            sql("INSERT INTO demo_orders VALUES (900001,NULL,'BROKEN',1,'2026-01-01')")
            second = [api(f"/api/rules/{rid}/run", {"session_id": session}) for rid in rule_ids]
            counts(second[0], (21, 21, 17, 4, 0))
            counts(second[1], (21, 20, 17, 3, 1))
            assert all(api(f'/api/results/{old["execution_id"]}') == old for old in snapshots)
            print("PASS changed data: new failures 4 / 3; old statistics and samples unchanged", flush=True)

            api("/api/settings", {"model_name": "docker-persistence-test", "model_base_url": "https://example.invalid/v1",
                                   "model_api_key": "docker-test-dummy-key", "model_proxy_mode": "direct"})
            run("down")  # Preserve the two named volumes, then recreate both containers.
            run("up", "-d", "--wait", "--wait-timeout", "180")
            ready()
            config_view = api("/api/settings")
            assert config_view["model_name"] == "docker-persistence-test" and config_view["model_api_key_set"]
            assert api("/api/settings/test-database", {})["demo_orders"] == 21
            assert all(api(f'/api/results/{old["execution_id"]}') == old for old in snapshots)
            assert api(f"/api/sessions/{session}/messages")
            assert api("/api/datasets") == uploaded_before
            print("PASS container recreation: rules, executions, session traces, model settings and 21 rows retained", flush=True)

            run("stop", "mysql")
            assert api("/api/health")["database"] == "unavailable"
            try:
                api(f"/api/rules/{rule_ids[0]}/run", {"session_id": session})
                raise AssertionError("Database outage incorrectly reported execution success")
            except HTTPError as exc:
                assert exc.code == 503, exc.code
            print("PASS database outage: unhealthy status and HTTP 503, no false success", flush=True)
            run("up", "-d", "--wait", "--wait-timeout", "180")
            ready()
            assert all(api(f'/api/results/{old["execution_id"]}') == old for old in snapshots)
            print("PASS database recovery; Docker integration verification complete", flush=True)
        finally:
            # Unique project generated above: never targets the user's dq-desktop stack.
            run("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
