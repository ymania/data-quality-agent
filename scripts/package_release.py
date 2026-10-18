"""Build the customer handoff archive from an explicit, secret-free manifest."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT.parent / "data-quality-agent.zip"
FILES = (
    'README.md',
    'DELIVERY_CHECKLIST.md',
    'DESIGN.md',
    'TEST_RECORD.md',
    'LEARNING.md',
    'DATA_INGESTION.md',
    'DOCKER_DEPLOY.md',
    'docs/README.md',
    'app/datasets.py',
    'app/upload_api.py',
    'tests/test_uploads.py',
    'tests/test_bruteforce_regressions.py',
    '.env.example',
    '.dockerignore',
    '.gitignore',
    'Dockerfile',
    'compose.yaml',
    'start-docker.sh',
    'start-docker.command',
    'start-docker.cmd',
    '启动Docker应用.desktop',
    'scripts/start-docker.ps1',
    'scripts/container_health.py',
    'scripts/verify_docker.py',
    'tests/test_deployment.py',
    'docs/架构故事.md',
    'requirements.txt',
    'start.sh',
    '启动数据质量Agent.desktop',
    'docs/问题三_自然语言规则与后端接口报告.md',
    'docs/问题五_数据管道与Docker部署.md',
    'docs/evidence/HERMES_TEST/测试报告.md',
    'docs/evidence/HERMES_TEST/screenshots/01_home.png',
    'docs/evidence/HERMES_TEST/screenshots/02_result_dialog.png',
    'docs/evidence/HERMES_TEST/screenshots/03_chat_traces.png',
    'docs/evidence/HERMES_TEST/screenshots/04_swagger_docs.png',
    'app/__init__.py',
    'app/agent.py',
    'app/db.py',
    'app/main.py',
    'app/model_client.py',
    'app/launcher.py',
    'app/quality.py',
    'app/settings.py',
    'app/static/app.js',
    'app/static/index.html',
    'app/static/setup.html',
    'app/static/setup.js',
    'app/static/style.css',
    'scripts/__init__.py',
    'scripts/generate_orders.py',
    'scripts/package_release.py',
    'scripts/setup_model.sh',
    'sql/create_user.sql',
    'sql/schema.sql',
    'sql/seed.sql',
    'tests/test_acceptance.py',
    'tests/test_agent_resilience.py',
    'tests/test_generator.py',
    'tests/test_settings.py',
)


def main() -> None:
    for relative in FILES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"Missing or unsafe release file: {relative}")
    with ZipFile(ARCHIVE, "w", compression=ZIP_DEFLATED) as archive:
        for relative in FILES:
            archive.write(ROOT / relative, f"data-quality-agent/{relative}")
    print(f"Built {ARCHIVE} with {len(FILES)} files; local .env is excluded")


if __name__ == "__main__":
    main()
