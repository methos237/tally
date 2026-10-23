"""A stand-in for Tally's /internal endpoints so `airflow dags test` runs in CI.

Answers 200 to everything, refuses a missing token, and appends each request to the
file named by FAKE_TALLY_LOG so the workflow can assert the three calls happened in order.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = os.environ.get("FAKE_TALLY_LOG", "/tmp/fake-tally.log")


class Handler(BaseHTTPRequestHandler):
    def _answer(self) -> None:
        ok = self.headers.get("X-Internal-Token") == os.environ.get(
            "AIRFLOW_VAR_TALLY_INTERNAL_TOKEN"
        )
        with open(LOG, "a") as log:
            log.write(f"{self.command} {self.path} {'ok' if ok else 'unauthorized'}\n")
        body = json.dumps({"path": self.path}).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
