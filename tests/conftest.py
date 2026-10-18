from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="personal-agent-tests-"))
os.environ["DATA_DIR"] = str(_TEST_ROOT / "data")
os.environ["VAULT_DIR"] = str(_TEST_ROOT / "vault")
os.environ["HOST"] = "127.0.0.1"
os.environ["APP_PASSWORD"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["IMAP_HOST"] = ""
os.environ["SMTP_HOST"] = ""
