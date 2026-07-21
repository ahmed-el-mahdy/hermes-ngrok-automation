import json
import os
import sqlite3
import time


gateway_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_SERVER_KEY")
nara_key = os.environ.get("NARA_ROUTER_API_KEY")
if not gateway_key or not nara_key:
    raise SystemExit("Required gateway or NaraRouter credential is missing")

db = sqlite3.connect("/app/backend/data/webui.db", timeout=30)
db.execute("pragma busy_timeout=30000")
row = db.execute("select data from config where id = 1").fetchone()
if not row:
    raise SystemExit("Open WebUI config row is missing")

config = json.loads(row[0])
openai = config.setdefault("openai", {})
openai["enable"] = True
openai["api_base_urls"] = [
    "http://hermes-agent:8642/v1",
    "https://router.bynara.id/v1",
]
openai["api_keys"] = [gateway_key, nara_key]
openai["api_configs"] = {
    "0": {
        "enable": True,
        "tags": [],
        "prefix_id": "",
        "model_ids": ["hermes-agent"],
        "connection_type": "external",
        "auth_type": "bearer",
    },
    "1": {
        "enable": True,
        "tags": [{"name": "cloud-fallback"}],
        "prefix_id": "",
        "model_ids": ["mistral-large", "glm-5.2-free"],
        "connection_type": "external",
        "auth_type": "bearer",
    },
}

db.execute(
    "update config set data = ?, updated_at = ? where id = 1",
    (
        json.dumps(config, separators=(",", ":")),
        int(time.time()),
    ),
)
db.commit()
print("integrity=" + str(db.execute("pragma integrity_check").fetchone()[0]))
db.close()
