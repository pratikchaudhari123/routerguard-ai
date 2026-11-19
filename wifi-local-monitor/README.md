# WiFi — Local RSSI Monitor

## Run on Mac
```bash
cd wifi-local-monitor
python3 app.py
```
Open http://127.0.0.1:58080. No pip packages required.

The default `demo` mode uses simulated values only. It does NOT measure your routers.

## Enable real readings (supported routers only)
Edit `config.json`:
- set `"mode": "router"`
- set `router_host` to the TP-Link router's LAN IP
- set `ssh_user` and `wifi_interface` to the actual SSH user and wireless uplink interface
- leave the poll interval and threshold adjustable after collecting baseline data

This implementation requires SSH access to TP-Link and OpenWrt/Linux-compatible `iw`:
```bash
ssh root@192.168.1.2
iw dev
iw dev wlan-sta link
```
Use the actual interface shown by `iw dev`. Configure SSH key authentication from your Mac first. Restart the app after changing config.

Many TP-Link stock firmwares do not expose SSH or `iw`; in that case router mode will not work. Do not flash firmware or change settings to force it. Share the exact TP-Link model, hardware version, and wireless operating mode so the correct read method can be selected.

Samples are saved to `data/readings.csv`. Detection compares RSSI to a slowly adapting baseline. RSSI changes can be caused by movement or interference as well as a door; calibrate with labelled open/closed trials. This project reads router-reported RSSI, not CSI, and does not substitute the Mac's Wi-Fi signal.
