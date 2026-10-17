"""Generate a Cloud Run --env-vars-file from the local .env file.

Run this in Cloud Shell before deploying:

    python3 make_env_file.py
    gcloud run deploy pyresec-agent \
        --source . \
        --region us-central1 \
        --allow-unauthenticated \
        --env-vars-file cloudrun.env

The generated `cloudrun.env` contains secrets — do not commit it.

gcloud parses --env-vars-file with python-dotenv (strict KEY=VALUE, NOT
YAML). Its vendored parser returns None for empty or malformed values and
gcloud then rejects the deploy ("values must be strings ... Found None").
This generator therefore:
  * keeps strict single-line KEY=VALUE format (proven in production deploys)
  * drops empty values (unset beats None; code uses getenv defaults)
  * strips embedded newlines (a multiline value would otherwise emit a
    continuation line with no '=' -> None)
  * skips keys that aren't C identifiers (dotenv would choke)
  * reads utf-8-sig (tolerates a BOM from Windows editors)
"""

import re
from pathlib import Path

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def main():
    src = Path(".env")
    dst = Path("cloudrun.env")
    if not src.exists():
        raise SystemExit(".env not found")

    lines, skipped_empty, skipped_bad = [], [], []
    for raw in src.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not KEY_RE.match(key):
            skipped_bad.append(key)
            continue
        if not value:
            skipped_empty.append(key)
            continue
        # single-line guarantee: no continuation lines for gcloud's parser
        value = value.replace("\r", " ").replace("\n", " ")
        lines.append(f"{key}={value}")

    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated {dst} with {len(lines)} variables")
    if skipped_empty:
        print(f"  dropped empty: {', '.join(skipped_empty)}")
    if skipped_bad:
        print(f"  dropped malformed keys: {', '.join(skipped_bad)}")


if __name__ == "__main__":
    main()
