import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import social_scanner as ss

code = "import os\n\ndef get(user):\n    return os.popen('ls ' + user).read()\n"
r = ss.sponsored_quick_scan(code)
if r:
    findings = r.get("sast_findings", [])
    print(f"SCAN OK — {len(findings)} findings")
    for f in findings[:3]:
        print(" ", f.get("severity"), f.get("type"), "line", f.get("line_number"))
else:
    print("scan returned None")
