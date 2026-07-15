#!/usr/bin/env python3
"""
Cursor MCP server wrapping the donkeycar Agent API.

Exposes tools so Claude can read sensors and send steering/throttle to a
running car/sim that has HAVE_AGENT_API = True.

Environment:
  AGENT_API_BASE_URL  Base URL of the robot Agent API
                      (default: http://127.0.0.1:8891)
  AGENT_API_TOKEN     Optional Bearer token (must match car config)

Cursor MCP config example (~/.cursor/mcp.json)::

  {
    "mcpServers": {
      "donkeycar-agent": {
        "command": "python",
        "args": ["/absolute/path/to/donkeycar/tools/agent_mcp/server.py"],
        "env": {
          "AGENT_API_BASE_URL": "http://raspberrypi.local:8891"
        }
      }
    }
  }

Requires: pip install mcp httpx
"""

from __future__ import annotations

import base64
import os
import sys
from typing import Any, Optional

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Missing dependency: pip install mcp httpx",
        file=sys.stderr,
    )
    raise

BASE_URL = os.environ.get("AGENT_API_BASE_URL", "http://127.0.0.1:8891").rstrip(
    "/")
TOKEN = os.environ.get("AGENT_API_TOKEN", "")

mcp = FastMCP("donkeycar-agent")


def _headers() -> dict:
    if TOKEN:
        return {"Authorization": f"Bearer {TOKEN}"}
    return {}


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=10.0)


@mcp.tool()
def robot_health() -> dict[str, Any]:
    """Check that the donkeycar Agent API is reachable."""
    with _client() as client:
        r = client.get("/api/v1/health")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def robot_state() -> dict[str, Any]:
    """
    Get current robot state: agent_active, steering, throttle, mode,
    recording, imu (accel/gyro), enc_speed, timestamp.
    """
    with _client() as client:
        r = client.get("/api/v1/state")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def robot_camera() -> dict[str, Any]:
    """
    Fetch the latest camera JPEG as base64.

    Returns keys: content_type, jpeg_base64, byte_length.
    """
    with _client() as client:
        r = client.get("/api/v1/camera.jpg")
        if r.status_code == 404:
            return {"error": "no camera frame", "jpeg_base64": None}
        r.raise_for_status()
        data = r.content
        return {
            "content_type": "image/jpeg",
            "jpeg_base64": base64.b64encode(data).decode("ascii"),
            "byte_length": len(data),
        }


@mcp.tool()
def robot_set_active(active: bool) -> dict[str, Any]:
    """
    Claim or release agent control.

    active=True: agent may drive (still requires control commands;
    commands time out and stop the car if they stop arriving).
    active=False: release control; human web/joystick takes over.
    """
    with _client() as client:
        r = client.post("/api/v1/active", json={"active": active})
        r.raise_for_status()
        return r.json()


@mcp.tool()
def robot_set_control(
    steering: float,
    throttle: float,
    mode: Optional[str] = None,
    recording: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Send steering and throttle. Activates the agent if not already active.

    steering: -1.0 (left) .. 1.0 (right)
    throttle: typically -1.0 .. 1.0 (car-dependent; keep small when testing)
    mode: optional 'user' | 'local_angle' | 'local'
    recording: optional bool

    Keep sending commands within the car's AGENT_API_COMMAND_TIMEOUT_SECS
    (default 0.5s) or the car zeros throttle and deactivates the agent.
    """
    payload: dict[str, Any] = {
        "steering": float(steering),
        "throttle": float(throttle),
    }
    if mode is not None:
        payload["mode"] = mode
    if recording is not None:
        payload["recording"] = recording
    with _client() as client:
        r = client.post("/api/v1/control", json=payload)
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    mcp.run()
