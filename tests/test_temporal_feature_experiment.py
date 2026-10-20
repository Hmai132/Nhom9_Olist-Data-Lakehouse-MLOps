import unittest

import numpy as np
import pandas as pd

from pipeline.classification_baseline import MODEL_FEATURES
from pipeline.temporal_feature_experiment import (
    VARIANTS, build_variant, features_for_variant, red_band_metrics,
)


class TemporalFeatureExperimentTests(unittest.TestCase):
    def test_feature_variants_change_only_requested_columns(self):
        frame = pd.DataFrame({name: [1, 12] for name in MODEL_FEATURES})
        frame["feature_purchase_month"] = [1, 12]
        for variant in VARIANTS:
            transformed = features_for_variant(frame, variant)
            self.assertNotIn("feature_customer_zip_code_prefix", transformed)
            self.assertEqual("feature_promised_delivery_days" in transformed,
                             variant != "no_promised_days")
            self.assertEqual("feature_purchase_month" in transformed,
                             variant not in ("no_month", "cyclic_month"))
            self.assertEqual("purchase_month_sin" in transformed, variant == "cyclic_month")
            self.assertEqual("purchase_month_cos" in transformed, variant == "cyclic_month")
            self.assertIsNotNone(build_variant(variant))
        cyclic = features_for_variant(frame, "cyclic_month")
        self.assertAlmostEqual(cyclic.purchase_month_sin.iloc[0], 0)
        self.assertAlmostEqual(cyclic.purchase_month_cos.iloc[0], 1)

    def test_shift_red_band_does_not_use_unknown_label(self):
        n = 40
        ids = pd.Series([f"order-{i:02d}" for i in range(n)])
        timestamps = pd.Series([pd.Timestamp("2018-04-01 01:00:00")] * n)
        scores = np.arange(n, 0, -1, dtype=float) / n
        labels = pd.Series([pd.NA, True] + [False] * (n - 2), dtype="boolean")
        result = red_band_metrics(ids, timestamps, scores, labels)
        self.assertEqual(result["red_orders"], 2)
        self.assertEqual(result["red_with_known_label"], 1)
        self.assertEqual(result["red_with_unknown_label"], 1)
        self.assertEqual(result["known_late_in_red"], 1)


if __name__ == "__main__":
    unittest.main()
