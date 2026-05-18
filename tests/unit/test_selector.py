import unittest

import cv2
import numpy as np

from app.schemas import ProcessedFrame
from app.selector.cpu_selector import CpuSelector


def textured_image(shift=0):
    image = np.zeros((160, 220, 3), dtype=np.uint8)
    for i in range(12):
        center = (20 + i * 15 + shift, 30 + (i % 5) * 20)
        cv2.circle(image, center, 7, (20 * i % 255, 255 - 10 * i, 50 + 12 * i), -1)
    cv2.putText(image, "KEYFRAME", (20 + shift, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return image


class CpuSelectorTest(unittest.TestCase):
    def test_keep_drop_decisions(self):
        selector = CpuSelector(min_interval_sec=0.0, blur_threshold=20.0, diff_threshold=5.0)
        img1 = textured_image(0)
        frame1 = ProcessedFrame(1, 1.0, img1.shape[1], img1.shape[0], img1)
        first = selector.decision(frame1, {})
        self.assertTrue(first["keep"])

        duplicate = ProcessedFrame(2, 2.0, img1.shape[1], img1.shape[0], img1.copy())
        dup = selector.decision(duplicate, {"last_keep_ts": 1.0, "last_keep_image": img1})
        self.assertFalse(dup["keep"])
        self.assertEqual(dup["reason"], "duplicate")

        blurry_img = cv2.GaussianBlur(img1, (31, 31), 0)
        blurry = ProcessedFrame(3, 3.0, blurry_img.shape[1], blurry_img.shape[0], blurry_img)
        blur_decision = selector.decision(blurry, {"last_keep_ts": 1.0, "last_keep_image": None})
        self.assertFalse(blur_decision["keep"])
        self.assertEqual(blur_decision["reason"], "blur")


if __name__ == "__main__":
    unittest.main()
