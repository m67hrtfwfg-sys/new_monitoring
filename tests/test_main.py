import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(file))))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
  response = client.get("/health")
  assert response.status_code in [200,401]
