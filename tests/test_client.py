import base64
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from decken import DeckenClient, DeckenError

MOCK_PPTX = b"PK\x03\x04python-sdk-pptx"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer py_secret":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"Unauthorized"}')
            return
        if self.path == "/v1/capabilities":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"service":"decken-reconstruct-api","defaultModelId":"qwen/qwen3.8-flash"}')
            return
        if self.path == "/v1/jobs/job_async_1":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "jobId": "job_async_1",
                        "status": "completed",
                        "pptxUrl": "/v1/jobs/job_async_1/pptx",
                        "metrics": {"slideCount": 2, "totalObjectCount": 24},
                        "usage": {"totalTokens": 4000, "costUsd": 0.002},
                        "slides": [],
                    }
                ).encode()
            )
            return
        if self.path == "/v1/jobs/job_async_1/pptx":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(MOCK_PPTX)
            return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode())
        if self.path == "/v1/decks":
            scenario = (
                "improve_material"
                if body.get("source")
                else ("from_outline_with_reference" if body.get("reference") else "from_outline")
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "jobId": "deck_py_1",
                        "scenario": scenario,
                        "status": "completed",
                        "pptxUrl": "/v1/decks/deck_py_1/pptx",
                        "pollUrl": "/v1/decks/deck_py_1",
                        "pptxBase64": base64.b64encode(MOCK_PPTX).decode(),
                        "metrics": {"slideCount": 2, "totalObjectCount": 18},
                        "agentDiagnostics": {"editabilityVerdict": "native_editable"},
                        "usage": {"totalTokens": 2400, "costUsd": 0.0011},
                        "slides": [],
                    }
                ).encode()
            )
            return
        if body.get("mode") == "async":
            self.send_response(202)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "jobId": "job_async_1",
                        "status": "queued",
                        "pptxUrl": "/v1/jobs/job_async_1/pptx",
                        "pollUrl": "/v1/jobs/job_async_1",
                        "usage": {"totalTokens": 0, "costUsd": 0},
                        "slides": [],
                    }
                ).encode()
            )
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "jobId": "job_sync_1",
                    "status": "completed",
                    "pptxUrl": "/v1/jobs/job_sync_1/pptx",
                    "pollUrl": "/v1/jobs/job_sync_1",
                    "pptxBase64": base64.b64encode(MOCK_PPTX).decode(),
                    "metrics": {"slideCount": 1, "meanWholePageMae": 0.015, "totalObjectCount": 12},
                    "usage": {"totalTokens": 2100, "costUsd": 0.001},
                    "slides": [],
                }
            ).encode()
        )


class DeckenPythonSdkTest(unittest.TestCase):
    def test_origin_safety_and_sync_async_reconstruction(self):
        with self.assertRaises(DeckenError):
            DeckenClient(api_key="py_secret", base_url="http://remote.example.com")

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            client = DeckenClient(api_key="py_secret", base_url=base_url)
            caps = client.get_capabilities()
            self.assertEqual(caps["defaultModelId"], "qwen/qwen3.8-flash")

            with tempfile.TemporaryDirectory() as tmp:
                img = Path(tmp) / "slide.png"
                img.write_bytes(b"\x89PNG\r\n\x1a\n")
                out_sync = Path(tmp) / "sync.pptx"
                job = client.reconstruct_slide(image_path=img, output_path=out_sync)
                self.assertEqual(job["status"], "completed")
                self.assertEqual(out_sync.read_bytes(), MOCK_PPTX)

                tpl = Path(tmp) / "brand.pptx"
                tpl.write_bytes(MOCK_PPTX)
                g1 = client.generate(outline="## Slide 1\n- Fact", output_path=Path(tmp) / "g1.pptx")
                self.assertEqual(g1["scenario"], "from_outline")
                g2 = client.generate(outline="## Slide 1\n- Fact", reference=tpl, output_path=Path(tmp) / "g2.pptx")
                self.assertEqual(g2["scenario"], "from_outline_with_reference")
                g3 = client.generate(source=tpl, prompt="Upgrade layout", output_path=Path(tmp) / "g3.pptx")
                self.assertEqual(g3["scenario"], "improve_material")

                out_deck = Path(tmp) / "deck.pptx"
                deck_job = client.reconstruct_deck(
                    [{"image_path": img}, {"image_path": img}],
                    output_path=out_deck,
                    poll_interval=0.02,
                )
                self.assertEqual(deck_job["metrics"]["slideCount"], 2)
                self.assertEqual(out_deck.read_bytes(), MOCK_PPTX)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
