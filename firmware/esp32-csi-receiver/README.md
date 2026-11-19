# ESP32 CSI receiver for RouterGuard AI

This is the first hardware path for **one existing Wi-Fi router + one ESP32-S3 CSI receiver + the MacBook running RouterGuard AI**. No second router/extender is required for this first link.

It is based on Espressif's official `csi_recv_router` approach: the ESP32 joins the existing access point, sends ping traffic to its gateway, captures CSI from the AP's replies, converts each complex subcarrier sample to an amplitude, and POSTs measured vectors to the MacBook API.

## Important compatibility boundary

- This firmware is an ESP-IDF project for an ESP32-S3 development board. It is not firmware for a JioFiber router.
- It does not configure or reset the JioFiber router.
- Router/AP behavior matters. The receiver must obtain CSI from the AP's ping replies; if the AP does not provide usable replies/CSI in this mode, this exact one-link method will not work with that AP.
- The MacBook's Apple RSSI is never substituted for CSI.
- A CSI deviation is only a movement/presence candidate. Fans, doors, pets, moving objects, multipath and interference can also change CSI.
- This first single-link setup does not provide reliable room-wide localization or human-vs-object identity.

## Wiring and network layout

1. Leave the JioFiber router powered on and unchanged.
2. Connect the ESP32-S3 board to the MacBook with a USB data cable for flashing and power.
3. The ESP32 joins the **same Wi-Fi network** as the MacBook (wirelessly).
4. The MacBook app must be reachable at its LAN address, for example `http://192.168.31.131:8000`. Use the MacBook's current LAN IP, not `127.0.0.1`, in the firmware configuration.
5. Place the ESP32 at a fixed position in the area to be tested. Keep it and the router stationary during a trial.

No Ethernet connection between routers is involved. Do not factory-reset the JioFiber router.

## Build and flash

Install Espressif ESP-IDF using its official installation instructions, then open an ESP-IDF terminal.

From this directory:

```bash
idf.py set-target esp32s3
idf.py menuconfig
```

Open **WiFiSense receiver configuration** and set:
- Wi-Fi SSID: the exact SSID used by the MacBook
- Wi-Fi password: that network's password
- RouterGuard API URL: `http://192.168.31.131:8000/api/csi` (replace the IP with the MacBook's current LAN IP)
- Device ID: `esp32-s3-csi-01`

Then build and flash:

```bash
idf.py build
idf.py -p PORT flash monitor
```

Replace `PORT` with the ESP32 serial port shown on the Mac. The USB cable is used for programming/serial logs; CSI data is sent over Wi-Fi to the MacBook.

## Dashboard procedure

1. Start RouterGuard AI on the MacBook and open `http://127.0.0.1:8000`.
2. Confirm the MacBook and ESP32 are on the same LAN.
3. Watch the CSI receiver panel. It must show a recent real CSI packet before calibration.
4. Leave the test area empty and still. Start **Calibrate empty room (60 CSI packets)**.
5. Wait for the dashboard to report that the baseline is ready.
6. Walk across the router-to-ESP32 radio path and observe candidate events.
7. Repeat empty-room, human movement, and non-human disturbance trials. Export and compare the measurements before making accuracy claims.

## If no CSI packets arrive

Check the ESP32 serial log for Wi-Fi connection, gateway address, and HTTP POST errors. Confirm:
- MacBook LAN IP has not changed.
- macOS firewall allows the local Python server on port 8000.
- ESP32 and MacBook are on the same local network (guest/client isolation must be off).
- The configured API URL uses the MacBook LAN IP, not localhost.
- The router responds to ping from a Wi-Fi client.

The MacBook cannot remotely turn an ordinary JioFiber router into a CSI receiver. If this AP does not support the router-reply capture path, the next option is a second ESP32 as a dedicated transmitter (ESP32-to-ESP32 CSI), not buying/resetting another ordinary router.

## Official reference

- Espressif ESP-CSI: https://github.com/espressif/esp-csi
- Router-as-transmitter example: https://github.com/espressif/esp-csi/tree/master/examples/get-started/csi_recv_router
- ESP-CSI guide: https://documentation.espressif.com/esp-csi/master/README.md


## Critical distinction for a two-router WDS installation

This firmware does **not** measure the JioAirFiber-to-TP-Link WDS link. It associates with one access point and filters CSI frames to that AP's BSSID. If configured to join the TP-Link SSID, it measures frames from TP-Link to the ESP32-S3; if configured to join Jio directly, it measures frames from Jio to the ESP32-S3. It cannot inspect the TP-Link's WDS receive chain or obtain the Jio-to-TP-Link RSSI from the MacBook. Do not describe these CSI packets as WDS-link CSI. For room sensing, treat the ESP32 link as its own fixed sensing path and validate it independently.
