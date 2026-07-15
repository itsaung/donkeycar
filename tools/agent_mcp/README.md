# Donkeycar Agent MCP

Thin Cursor MCP server that talks to the robot Agent API (`HAVE_AGENT_API`).

## Setup

```bash
pip install mcp httpx
```

On the car (or sim), in `myconfig.py`:

```python
HAVE_AGENT_API = True
AGENT_API_PORT = 8891
# AGENT_API_TOKEN = "optional-shared-secret"
```

Start drive as usual (`python manage.py drive`). Human UI stays on port 8887.

## Cursor config

Add to your MCP config (e.g. `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "donkeycar-agent": {
      "command": "python",
      "args": ["/absolute/path/to/donkeycar/tools/agent_mcp/server.py"],
      "env": {
        "AGENT_API_BASE_URL": "http://127.0.0.1:8891"
      }
    }
  }
}
```

Use the car's hostname for a physical robot, e.g. `http://donkeypi.local:8891`.

## Tools

| Tool | Action |
|------|--------|
| `robot_health` | Liveness check |
| `robot_state` | Mode, controls, IMU, etc. |
| `robot_camera` | Latest JPEG (base64) |
| `robot_set_active` | Claim / release agent control |
| `robot_set_control` | Set steering + throttle |

## Safety

- Agent starts **inactive**; call `robot_set_active(true)` or send a control command to claim.
- If commands stop arriving within `AGENT_API_COMMAND_TIMEOUT_SECS` (default 0.5s), throttle goes to 0 and the agent deactivates.
- Human web UI / joystick still works when the agent is inactive.
- Keep a physical kill switch when testing on hardware.
