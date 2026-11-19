import tempfile
import unittest
from pathlib import Path
from tools.evaluate_detection import evaluate


class DetectionEvaluationTests(unittest.TestCase):
    def test_confusion_matrix_and_metrics(self):
        content = (
            "timestamp_utc,ground_truth,prediction\n"
            "2026-11-20T10:00:00+00:00,presence,presence\n"
            "2026-11-20T10:01:00+00:00,absence,absence\n"
            "2026-11-20T10:02:00+00:00,absence,presence\n"
            "2026-11-20T10:03:00+00:00,presence,absence\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.csv"
            path.write_text(content, encoding="utf-8")
            result = evaluate(path)
        self.assertEqual(result["confusion_matrix"], {
            "true_positive": 1, "true_negative": 1,
            "false_positive": 1, "false_negative": 1,
        })
        self.assertEqual(result["metrics"]["accuracy"], 0.5)
        self.assertEqual(result["metrics"]["precision"], 0.5)
        self.assertEqual(result["metrics"]["recall_sensitivity"], 0.5)
        self.assertEqual(result["metrics"]["balanced_accuracy"], 0.5)
        self.assertIsNotNone(result["false_alarms_per_hour"])

    def test_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("rssi\n-50\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate(path)


if __name__ == "__main__":
    unittest.main()
