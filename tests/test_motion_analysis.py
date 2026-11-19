import tempfile
import unittest
from pathlib import Path
from tools.analyze_motion_trials import analyze

class MotionAnalysisTests(unittest.TestCase):
    def test_groups_and_empty_baseline_comparison(self):
        content = (
            "timestamp_utc,zone,condition,trial_label,rssi_dbm,noise_dbm,rolling_rssi_range_db\n"
            "2026-01-01T00:00:00Z,A,empty,e1,-40,-90,1\n"
            "2026-01-01T00:00:01Z,A,empty,e1,-42,-90,2\n"
            "2026-01-01T00:00:02Z,A,walking,w1,-50,-90,5\n"
            "2026-01-01T00:00:03Z,A,walking,w1,-52,-90,6\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trial.csv"
            path.write_text(content, encoding="utf-8")
            result = analyze(path)
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["comparisons_vs_empty"][0]["mean_shift_db"], -10.0)
        self.assertIn("not identify", result["interpretation"])

if __name__ == "__main__":
    unittest.main()
