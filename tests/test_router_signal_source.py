import unittest
from backend.router_diagnostics import _extract_wds_rssi


class RouterSignalSourceTests(unittest.TestCase):
    def test_accepts_explicit_wds_peer_rssi(self):
        html = "<div>WDS Peer RSSI: -61 dBm</div>"
        self.assertEqual(_extract_wds_rssi(html), -61)

    def test_rejects_generic_wireless_client_rssi(self):
        html = "<div>Wireless Client Signal Strength: -48 dBm</div>"
        self.assertIsNone(_extract_wds_rssi(html))

    def test_rejects_rssi_without_wds_peer_context(self):
        html = "<div>RSSI: -42 dBm</div>"
        self.assertIsNone(_extract_wds_rssi(html))

    def test_rejects_out_of_range_values(self):
        html = "<div>WDS RSSI: -140 dBm</div>"
        self.assertIsNone(_extract_wds_rssi(html))


if __name__ == "__main__":
    unittest.main()
