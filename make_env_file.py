"""Generate a Cloud Run --env-vars-file from the local .env file.

Run this in Cloud Shell before deploying:

    python3 make_env_file.py
    gcloud run deploy pyresec-agent \
        --source . \
        --region us-central1 \
        --allow-unauthenticated \
        --env-vars-file cloudrun.env

The generated `cloudrun.env` contains secrets — do not commit it.
Values are JSON-quoted so gcloud's YAML parser always sees strings
(bare `true`, empty values, etc. used to parse as null/bool and fail).
"""

import json
from pathlib import Path


def main():
    src = Path(".env")
    dst = Path("cloudrun.env")
    if not src.exists():
        raise SystemExit(".env not found")

    lines = []
    for raw in src.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        lines.append(f"{key}: {json.dumps(value)}")

    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated {dst} with {len(lines)} variables")


if __name__ == "__main__":
    main()
