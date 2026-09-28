"""PYRESEC Probe — free local proof engine for outreach.

Runs the same SAST/SCA/gas engines as the live API but locally: no x402
payment, no LLM call, no cost per lead. Used to produce the proof that
opens every high-ticket conversation.

Also provides GitHub file/metadata fetch helpers shared by the engines.
"""

import sys
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_controller import (  # noqa: E402
    run_sast_scan,
    run_sca_scan,
    run_gas_optimization_scan,
    compute_file_hash,
)


def local_scan(code: str) -> dict:
    """Pattern-based scan identical to the API's non-LLM layers. Free."""
    sast = run_sast_scan(code, full=True)
    sca = run_sca_scan(code)
    gas = run_gas_optimization_scan(code)
    return {
        "status": "success",
        "tier": "Local Proof Scan (free)",
        "file_hash": compute_file_hash(code),
        "sast_findings": sast,
        "sca_findings": sca,
        "gas_findings": gas,
        "total_findings": len(sast) + len(sca) + len(gas),
        "model": "pyresec-local-sast",
    }


def fetch_github_file(repo: str, filepath: str) -> Optional[str]:
    url = f"https://raw.githubusercontent.com/{repo}/main/{filepath}"
    with httpx.Client(timeout=15.0) as client:
        for branch in ("main", "master"):
            try:
                resp = client.get(url.replace("/main/", f"/{branch}/"))
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                pass
    return None


def fetch_repo_main_file(repo: str) -> Optional[str]:
    """Fetch the most likely entry-point source file."""
    candidates = [
        "main.py", "app.py", "index.js", "index.ts", "server.js",
        "src/main.py", "src/app.py", "src/index.js", "src/index.ts",
        "app/main.py", "bot.py", "cli.py", "hardhat.config.js",
        "foundry.toml",
    ]
    for filepath in candidates:
        content = fetch_github_file(repo, filepath)
        if content and len(content.strip()) > 50:
            return content
    return None


def repo_info(full_name: str) -> Optional[dict]:
    """GitHub repo metadata (stars, topics, homepage...) for ICP scoring."""
    token = None
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        import os
        token = os.getenv("GITHUB_TOKEN")
    except Exception:
        pass
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(f"https://api.github.com/repos/{full_name}",
                         headers=headers, timeout=20.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


if __name__ == "__main__":
    import json
    demo = "import os\npassword = 'hunter2'\ndef run(u):\n    os.system('ls ' + u)\nel.innerHTML = q\n"
    print(json.dumps(local_scan(demo), indent=2))
