"""Container readiness requires both the HTTP API and its database."""
import json
from urllib.request import build_opener, ProxyHandler


def main():
    # Ignore host/proxy configuration for the container's own health probe.
    with build_opener(ProxyHandler({})).open(
        "http://127.0.0.1:8000/api/health", timeout=8
    ) as response:
        healthy = json.load(response).get("database") == "ok"
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
