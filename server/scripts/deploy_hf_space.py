"""Deploy the committed repository to a Hugging Face Docker Space.

Requires a Hugging Face login with write access (`hf auth login`). Then, from
the repository root:

    .venv310/bin/python server/scripts/deploy_hf_space.py [--space NAME]

Steps:
1. Create the Space (Docker SDK) if it does not exist.
2. Copy the API keys from `.env` into Space secrets. Values are never printed.
3. Upload the files of the current git commit (`git archive HEAD`). Untracked
   and ignored files, including `.env`, are never uploaded.
"""

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ("CONTACT_EMAIL", "CLIMATIQ_API_KEY", "HANDOVER_WEBHOOK_URL")
VARIABLES = ("CLIMATIQ_DATA_VERSION", "HANDOVER_RETENTION_DAYS", "LIVE_API_TIMEOUT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space", default="eco-travel-advisor", help="Space name (owner is the logged-in user)")
    parser.add_argument("--private", action="store_true", help="Create the Space as private")
    args = parser.parse_args()

    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                      capture_output=True, text=True, check=True).stdout.strip():
        print("Uncommitted changes would not be deployed. Commit them first.", file=sys.stderr)
        return 1

    api = HfApi()
    user = api.whoami()["name"]
    repo_id = f"{user}/{args.space}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
    print(f"Space: https://huggingface.co/spaces/{repo_id}")

    env = dotenv_values(ROOT / ".env")
    for key in SECRETS:
        if env.get(key):
            api.add_space_secret(repo_id, key, env[key])
            print(f"secret   {key}: set")
    for key in VARIABLES:
        if env.get(key):
            api.add_space_variable(repo_id, key, env[key])
            print(f"variable {key}: {env[key]}")

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "src.tar"
        subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), "HEAD"], cwd=ROOT, check=True)
        src = Path(tmp) / "src"
        with tarfile.open(archive) as tar:
            tar.extractall(src, filter="data")
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=str(src),
                          commit_message=f"Deploy {commit}", delete_patterns=["*"])
    print(f"Uploaded commit {commit}. Build logs: https://huggingface.co/spaces/{repo_id}?logs=build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
