#!/usr/bin/env python3
"""Local Wi-Fi RSSI monitor; Python standard library only."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json, re, subprocess, threading, time, math, random

BASE=Path(__file__).resolve().parent
CFG=BASE/"config.json"
DATA=BASE/"data"; DATA.mkdir(exist_ok=True)
LOG=DATA/"readings.csv"
DEFAULT={"mode":"demo","router_host":"192.168.1.2","ssh_user":"root","wifi_interface":"wlan-sta","poll_seconds":1,"drop_threshold_db":8,"ssh_options":["-o","BatchMode=yes","-o","ConnectTimeout=3","-o","StrictHostKeyChecking=accept-new"]}
if not CFG.exists(): CFG.write_text(json.dumps(DEFAULT,indent=2))
config={**DEFAULT,**json.loads(CFG.read_text())}
state={"connected":False,"rssi":None,"baseline":None,"status":"STARTING","message":"Waiting for first reading","last_seen":None,"history":[],"source":config["mode"]}
lock=threading.Lock()

def get_rssi():
    if config["mode"]=="demo":
        return round(-43+1.5*math.sin(time.time()/8)+random.uniform(-1.2,1.2))
    iface=config["wifi_interface"].strip()
    if not iface: raise RuntimeError("Set wifi_interface in config.json")
    cmd=["ssh",*config["ssh_options"],f'{config["ssh_user"]}@{config["router_host"]}',"iw","dev",iface,"link"]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=6)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout or "SSH failed").strip())
    if "Not connected" in p.stdout: raise RuntimeError("Wireless uplink interface is not connected")
    m=re.search(r"signal:\s*(-?\d+)\s*dBm",p.stdout,re.I)
    if not m: raise RuntimeError("RSSI not found in `iw dev <interface> link` output")
    return int(m.group(1))

def monitor():
    while True:
        try:
            r=get_rssi()
            from datetime import datetime
            ts=datetime.now().astimezone().isoformat(timespec="seconds")
            with lock:
                b=state["baseline"]
                b=r if b is None else .95*b+.05*r
                drop=b-r
                status="ALERT" if drop>=float(config["drop_threshold_db"]) else "NORMAL"
                state.update(connected=True,rssi=r,baseline=b,status=status,
                    message=f"RSSI dropped {drop:.1f} dB from rolling baseline" if status=="ALERT" else "Signal within threshold",
                    last_seen=ts,source=config["mode"])
                state["history"].append({"time":ts,"rssi":r,"status":status})
                state["history"]=state["history"][-180:]
            new=not LOG.exists()
            with LOG.open("a",encoding="utf-8") as f:
                if new: f.write("timestamp,rssi_dbm,status,source\n")
                f.write(f"{ts},{r},{status},{config['mode']}\n")
        except Exception as e:
            with lock: state.update(connected=False,status="NO DATA",message=str(e),source=config["mode"])
        time.sleep(max(1,int(config["poll_seconds"])))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(BASE/"static"),**kw)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/status":
            with lock: data=dict(state); data["history"]=list(state["history"])
            body=json.dumps(data).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        elif path=="/api/log.csv":
            if not LOG.exists(): self.send_error(404,"No readings yet"); return
            body=LOG.read_bytes(); self.send_response(200); self.send_header("Content-Type","text/csv"); self.send_header("Content-Disposition",'attachment; filename="wifi-readings.csv"'); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            if path=="/": self.path="/index.html"
            super().do_GET()
    def log_message(self,fmt,*args): print("[HTTP]",fmt%args)

if __name__=="__main__":
    print("WiFi RSSI Monitor: http://127.0.0.1:58080")
    print(f"Mode: {config['mode']} (demo values are simulated)")
    threading.Thread(target=monitor,daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1",58080),Handler).serve_forever()
