# RouterGuard AI

Real-time, read-only security visibility for two routers and the LAN they serve.

## What this MVP does
- Checks configured router IPs for ICMP reachability and common TCP management/service ports.
- Reads the macOS/Linux ARP neighbor table and inventories visible LAN devices.
- Flags newly observed MAC addresses as **unknown** until you approve them.
- Records router/device events in SQLite and serves a live dashboard/API.
- Does not attempt exploitation, password guessing, packet interception, deauthentication, or configuration changes.

## Important topology note
A Wi-Fi repeater/bridge often places both access points on one Layer-2 network. In that case, the client device list is usually shared, and a laptop cannot reliably attribute every device to a particular physical router. Configure each router's management IP if known. Router B can be marked unreachable if its management interface is isolated; that is not proof of compromise.

## Requirements
- macOS or Linux
- Python 3.10+
- Your MacBook connected to your own Wi-Fi network
- Router management IPs (often visible as the gateway in Network settings)

## Run locally on macOS (recommended)
Running natively gives the scanner access to the Mac's LAN and ARP table. Docker Desktop on macOS uses a VM network and may not see the LAN in the same way.

```bash
git clone https://github.com/pratikchaudhari123/routerguard-ai.git
cd routerguard-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set ROUTER_A_IP / ROUTER_B_IP
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

## Configuration
Edit `.env`:
- `ROUTER_A_IP`: Jio router management IP
- `ROUTER_B_IP`: repeater/bridge management IP
- `SCAN_INTERVAL_SECONDS`: polling interval (minimum 10 seconds)
- `KNOWN_MACS`: comma-separated MAC addresses you recognize, e.g. `AA:BB:CC:DD:EE:FF`

Never put router passwords, API keys, or private credentials in Git.

## Docker
`docker compose up --build` runs the dashboard in a container. On Docker Desktop for macOS, LAN/ARP visibility can be limited. For accurate local device discovery, use the native macOS instructions above. Docker is useful for API/UI testing and persistent SQLite storage.

## API
- `GET /api/status` — router and device snapshot
- `GET /api/events?limit=100` — recent events
- `POST /api/scan` — request an immediate scan
- `GET /health` — health check

## Interpreting alerts
An unknown MAC means the device was not in your approved list; it does **not** prove an intrusion. Identify it from your router's connected-device page before approving it. A failed ping or closed port is not proof of breach. Router configuration integrity checks require supported router APIs or manual configuration exports; this MVP does not claim to inspect hidden router settings.

## Safety
Use only on networks and devices you own or are authorized to administer. Keep router firmware updated, use WPA2-AES/WPA3, disable WPS if not needed, change default admin credentials, and review remote administration settings.
