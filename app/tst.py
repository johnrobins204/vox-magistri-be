import json
import urllib.request

# Update with your actual endpoint URL and session/message IDs
url = "http://localhost:5000/api/v1/sessions/YOUR_SESSION_ID/messages/YOUR_MESSAGE_ID/status"

headers = {
    "Authorization": "Bearer dev",
    "Content-Type": "application/json",
}

try:
  req = urllib.request.Request(url, headers=headers, method="GET")
  with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode("utf-8"))
    print("Success! Response:")
    print(json.dumps(data, indent=2))
except Exception as e:
  print(f"Request failed: {e}")