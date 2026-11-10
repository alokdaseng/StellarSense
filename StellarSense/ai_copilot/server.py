"""
=====================================================================================
 STELLARSENSE / ORBITGUARD — GEMMA 4 AUTONOMOUS FLIGHT DIRECTOR REST API SERVER
 Standard: Agent Skill Open Standard v1.0
 Target: Real-Time Telemetry Diagnostic & Autonomous Telecommand HTTP Bridge
 Port: 8001
=====================================================================================
"""

import json
import sys
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any

# Ensure module path is accessible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_copilot.harness import GemmaFlightHarness
from ai_copilot.tools import VALID_COMMANDS

harness_instance = GemmaFlightHarness()
SERVER_START_TIME = time.time()


class GemmaApiHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP Handler for Gemma 4 Flight Copilot API."""

    def _set_cors_headers(self, status_code: int = 200, content_type: str = "application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_cors_headers(204)

    def do_GET(self):
        if self.path == "/api/status" or self.path == "/":
            uptime = round(time.time() - SERVER_START_TIME, 1)
            response_data = {
                "status": "ONLINE",
                "system": "StellarSense / OrbitGuard Flight Director",
                "model": harness_instance.model_name,
                "agent_skill": "satellite-fdir (Agent Skill Open Standard v1.0)",
                "context_buffer_depth": len(harness_instance.telemetry_history),
                "autonomous_uplink_active": harness_instance.autonomous_uplink_enabled,
                "uptime_seconds": uptime,
                "supported_telecommands": list(VALID_COMMANDS.keys())
            }
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(response_data, indent=2).encode("utf-8"))
        else:
            self._set_cors_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            payload = json.loads(post_data.decode("utf-8"))
        except Exception as e:
            self._set_cors_headers(400)
            self.wfile.write(json.dumps({"error": "Invalid JSON payload", "details": str(e)}).encode("utf-8"))
            return

        if self.path == "/api/telemetry":
            # Run Gemma 4 Model Harness analysis
            analysis = harness_instance.analyze_telemetry(payload)
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(analysis, indent=2).encode("utf-8"))

        elif self.path == "/api/telecommand":
            cmd = payload.get("command", "")
            rationale = payload.get("rationale", "Operator manual telecommand uplink.")
            res = harness_instance.tool_executor.execute_tool("uplink_telecommand", {
                "command": cmd,
                "rationale": rationale
            })
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(res, indent=2).encode("utf-8"))

        elif self.path == "/api/config":
            if "autonomous_uplink" in payload:
                harness_instance.autonomous_uplink_enabled = bool(payload["autonomous_uplink"])
            self._set_cors_headers(200)
            self.wfile.write(json.dumps({
                "status": "CONFIG_UPDATED",
                "autonomous_uplink": harness_instance.autonomous_uplink_enabled
            }).encode("utf-8"))

        else:
            self._set_cors_headers(404)
            self.wfile.write(json.dumps({"error": "Unknown POST route"}).encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP access logs
        return


def run_server(port: int = 8001):
    server_address = ("", port)
    httpd = HTTPServer(server_address, GemmaApiHandler)
    print(f"🛰️ Gemma 4 Flight Copilot API Server online at http://localhost:{port}/")
    print(f"  • Model Harness: {harness_instance.model_name}")
    print(f"  • Agent Skill: satellite-fdir (Agent Skill Open Standard v1.0)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Gemma 4 server.")
        httpd.server_close()


if __name__ == "__main__":
    port = 8001
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)

