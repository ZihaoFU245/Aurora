import sys
from pathlib import Path

# Ensure project root is importable
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from fastapi.testclient import TestClient  # type: ignore
from Web.main import app

client = TestClient(app)

r = client.get("/")
print("GET /:", r.status_code)
print("Contains /static/css/style.css:", "/static/css/style.css" in r.text)
print("Contains /static/js/main.js:", "/static/js/main.js" in r.text)

rcss = client.get("/static/css/style.css")
print("GET /static/css/style.css:", rcss.status_code, "length:", len(rcss.text))

rjs = client.get("/static/js/main.js")
print("GET /static/js/main.js:", rjs.status_code, "length:", len(rjs.text))

