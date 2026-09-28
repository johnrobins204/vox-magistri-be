import json
import urllib.request

BASE = "http://localhost:5000/api/v1"
AUTH = {"Authorization": "Bearer dev", "Content-Type": "application/json"}

def http(method, url, data=None):
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=AUTH, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ------------------------------------------------------------
# 1. Create a session
# ------------------------------------------------------------
session = http("POST", f"{BASE}/sessions")
session_id = session["session_id"]
print("Session:", session_id)

# ------------------------------------------------------------
# 2. Send a message (enqueue inference job)
# ------------------------------------------------------------
msg = http(
    "POST",
    f"{BASE}/sessions/{session_id}/messages",
    {"content": "Hello, what can you do?"}
)
message_id = msg["message_id"]
print("Message:", message_id)

# ------------------------------------------------------------
# 3. Poll status until completed
# ------------------------------------------------------------
import time

while True:
    status = http(
        "GET",
        f"{BASE}/sessions/{session_id}/messages/{message_id}/status"
    )
    print("Status:", status)

    if status["status"] in ("completed", "error", "cancelled"):
        break

    time.sleep(1)

# ------------------------------------------------------------
# 4. Retrieve the completed message
# ------------------------------------------------------------
result = http(
    "GET",
    f"{BASE}/sessions/{session_id}/messages/{message_id}"
)
print("Final message:")
print(json.dumps(result, indent=2))
