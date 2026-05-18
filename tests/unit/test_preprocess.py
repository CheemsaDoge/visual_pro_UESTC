import unittest

import cv2
import numpy as np

from app.preprocess.cpu_engine import CpuPreprocessEngine
from app.preprocess.rga_engine import RgaPreprocessEngine
from app.schemas import FramePacket


class CpuPreprocessEngineTest(unittest.TestCase):
    def test_preview_and_save_outputs(self):
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        image[:, :60] = (0, 0, 255)
        packet = FramePacket(seq=1, timestamp=1.0, width=120, height=80, pixel_format="BGR", source="unit", data=image)
        engine = CpuPreprocessEngine(rotation="ccw90", preview_max_dim=64, preview_jpeg_quality=80)

        preview = engine.process_for_preview(packet)
        saved = engine.process_for_save(packet)

        self.assertEqual(preview.seq, 1)
        self.assertEqual((preview.width, preview.height), (80, 120))
        self.assertGreater(len(preview.preview_jpeg), 100)
        decoded = cv2.imdecode(np.frombuffer(preview.preview_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertLessEqual(max(decoded.shape[:2]), 64)
        self.assertEqual(saved.bgr_image.shape[:2], (120, 80))
        self.assertEqual(saved.meta["engine"], "cpu")

    def test_rga_missing_wrapper_falls_back_for_nv12(self):
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        image[:, :60] = (0, 255, 0)
        i420 = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).reshape(-1)
        y_size = 120 * 80
        uv_size = y_size // 4
        y = i420[:y_size].reshape((80, 120))
        u = i420[y_size:y_size + uv_size].reshape((40, 60))
        v = i420[y_size + uv_size:y_size + uv_size * 2].reshape((40, 60))
        uv = np.empty((40, 120), dtype=np.uint8)
        uv[:, 0::2] = u
        uv[:, 1::2] = v
        nv12 = np.vstack((y, uv))
        packet = FramePacket(seq=2, timestamp=2.0, width=120, height=80, pixel_format="NV12", source="unit", data=nv12)
        engine = RgaPreprocessEngine(
            fallback=CpuPreprocessEngine(rotation="none"),
            lib_path="/definitely/missing/libmyui_rga.so",
        )

        saved = engine.process_for_save(packet)

        self.assertEqual(saved.meta["engine"], "cpu")
        self.assertEqual(saved.meta["requested_engine"], "rga")
        self.assertEqual(saved.meta["mode_tag"], "rga_fallback_cpu")
        self.assertTrue(saved.meta["fallback"])
        self.assertIn("libmyui_rga.so", saved.meta["fallback_reason"])
        self.assertEqual(saved.bgr_image.shape[:2], (80, 120))


if __name__ == "__main__":
    unittest.main()
