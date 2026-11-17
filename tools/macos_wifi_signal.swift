import Foundation
import CoreWLAN

let client = CWWiFiClient.shared()
guard let wifi = client.interface(), wifi.powerOn() else {
    print("{\"connected\":false,\"error\":\"No active Wi-Fi interface\"}")
    exit(0)
}
let rssi = wifi.rssiValue()
let noise = wifi.noiseMeasurement()
let channel = wifi.wlanChannel()?.channelNumber ?? 0
let ssid = wifi.ssid() ?? ""
let txRate = wifi.transmitRate()
let connected = rssi < 0
let result: [String: Any] = [
    "connected": connected,
    "ssid": ssid,
    "interface": wifi.interfaceName,
    "rssi": connected ? rssi : NSNull(),
    "noise": connected ? noise : NSNull(),
    "channel": channel > 0 ? channel : NSNull(),
    "tx_rate_mbps": txRate > 0 ? txRate : NSNull(),
    "source": "Apple CoreWLAN"
]
if let data = try? JSONSerialization.data(withJSONObject: result, options: [.fragmentsAllowed]),
   let output = String(data: data, encoding: .utf8) {
    print(output)
}
