import os
import tempfile
import unittest

import cv2
import numpy as np

from app.preprocess.cpu_engine import CpuPreprocessEngine
from app.schemas import FramePacket
from app.selector.cpu_selector import CpuSelector
from app.stitch_engine.opencv_engine import OpenCVStitchEngine
from tests.unit.test_stitch_engine import create_overlap_pair


class PipelineIntegrationTest(unittest.TestCase):
    def test_preprocess_selector_stitch_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1, p2 = create_overlap_pair(tmpdir)
            engine = CpuPreprocessEngine(rotation="none", preview_max_dim=320)
            selector = CpuSelector(min_interval_sec=0.0, blur_threshold=5.0, diff_threshold=1.0)
            kept = []
            last_keep_image = None
            last_keep_ts = 0.0
            for seq, path in enumerate([p1, p2], start=1):
                image = cv2.imread(path)
                packet = FramePacket(seq, float(seq), image.shape[1], image.shape[0], "BGR", path, image)
                processed = engine.process_for_save(packet)
                decision = selector.decision(processed, {"last_keep_ts": last_keep_ts, "last_keep_image": last_keep_image})
                if decision["keep"]:
                    out = os.path.join(tmpdir, f"kept_{seq}.jpg")
                    cv2.imwrite(out, processed.bgr_image)
                    kept.append(out)
                    last_keep_image = processed.bgr_image.copy()
                    last_keep_ts = processed.timestamp
            self.assertGreaterEqual(len(kept), 2)
            output = os.path.join(tmpdir, "stitched.jpg")
            ok, msg = OpenCVStitchEngine().stitch(kept, output, auto_crop=True)
            self.assertTrue(ok, msg)
            self.assertTrue(os.path.isfile(output))


if __name__ == "__main__":
    unittest.main()
