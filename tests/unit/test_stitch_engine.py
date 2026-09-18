import os
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

from app.stitch_engine.opencv_engine import OpenCVStitchEngine
from app.stitch_engine.scans_engine import ScansStitchEngine
from app.stitch_engine.sequential_engine import SequentialPanoEngine
from app.stitch_engine.common import get_canvas_plan, postprocess_image


def create_overlap_pair(tmpdir):
    canvas = np.zeros((240, 420, 3), dtype=np.uint8)
    rng = np.random.default_rng(123)
    for i in range(60):
        x = int(rng.integers(10, 410))
        y = int(rng.integers(10, 230))
        color = tuple(int(v) for v in rng.integers(40, 255, size=3))
        cv2.circle(canvas, (x, y), int(rng.integers(3, 9)), color, -1)
    cv2.putText(canvas, "RK3588-PANO", (60, 125), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    left = canvas[:, :280]
    right = canvas[:, 140:420]
    p1 = os.path.join(tmpdir, "left.jpg")
    p2 = os.path.join(tmpdir, "right.jpg")
    cv2.imwrite(p1, left)
    cv2.imwrite(p2, right)
    return p1, p2


def create_overlap_triplet(tmpdir):
    canvas = np.zeros((240, 520, 3), dtype=np.uint8)
    rng = np.random.default_rng(456)
    for i in range(90):
        x = int(rng.integers(10, 510))
        y = int(rng.integers(10, 230))
        color = tuple(int(v) for v in rng.integers(50, 255, size=3))
        cv2.circle(canvas, (x, y), int(rng.integers(3, 8)), color, -1)
    for x in range(30, 500, 70):
        cv2.line(canvas, (x, 20), (x + 25, 220), (255, 255, 255), 2)
    cv2.putText(canvas, "SEQUENTIAL", (85, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    slices = [(0, 220), (140, 360), (280, 500)]
    paths = []
    for index, (start_x, end_x) in enumerate(slices, start=1):
        path = os.path.join(tmpdir, f"seq_{index}.jpg")
        cv2.imwrite(path, canvas[:, start_x:end_x])
        paths.append(path)
    return paths


class OpenCVStitchEngineTest(unittest.TestCase):
    def test_orb_match_downscale_keeps_full_resolution_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1, p2 = create_overlap_pair(tmpdir)
            left = cv2.imread(p1)
            right = cv2.imread(p2)
            left = cv2.resize(left, (1400, 1200), interpolation=cv2.INTER_LINEAR)
            right = cv2.resize(right, (1400, 1200), interpolation=cv2.INTER_LINEAR)
            cv2.imwrite(p1, left)
            cv2.imwrite(p2, right)
            output = os.path.join(tmpdir, "out_downscaled_match.jpg")
            engine = SequentialPanoEngine()
            ok, message = engine.stitch([p1, p2], output, auto_crop=True)
            self.assertTrue(ok, message)
            detail = engine.get_last_run_detail()
            pair_stage = next(stage for stage in detail["stages"] if stage["name"] == "pairwise_orb")
            self.assertEqual(pair_stage["match_images"]["max_width"], 960)
            self.assertEqual(pair_stage["match_images"]["left"]["width"], 960)
            self.assertGreater(pair_stage["canvas"]["width"], 960)

    def test_large_postprocess_skips_expensive_denoise(self):
        class FastCv:
            @staticmethod
            def GaussianBlur(image, kernel, sigma):
                return image

            @staticmethod
            def addWeighted(image, alpha, blurred, beta, gamma):
                return image

            @staticmethod
            def fastNlMeansDenoisingColored(*args):
                raise AssertionError("denoise must not run on an oversized result")

        telemetry = {}
        with mock.patch("app.stitch_engine.common.config.MAX_STITCH_DENOISE_PIXELS", 10):
            image = np.zeros((4, 4, 3), dtype=np.uint8)
            result = postprocess_image(image, FastCv(), telemetry=telemetry)
        self.assertIs(result, image)
        self.assertEqual(telemetry["denoise"], "skipped_for_size")

    def test_canvas_plan_rejects_oversized_warp_before_allocation(self):
        ok, message, use_multiband, pixels = get_canvas_plan(8000, 2000, 1920, 1080, 1920, 1080)
        self.assertFalse(ok)
        self.assertIn("safe board memory", message)
        self.assertFalse(use_multiband)
        self.assertEqual(pixels, 16_000_000)

    def test_canvas_plan_uses_low_memory_blend_above_multiband_limit(self):
        ok, message, use_multiband, pixels = get_canvas_plan(2000, 1800, 1920, 1080, 1920, 1080)
        self.assertTrue(ok, message)
        self.assertFalse(use_multiband)
        self.assertEqual(pixels, 3_600_000)

    def test_two_image_stitch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1, p2 = create_overlap_pair(tmpdir)
            output = os.path.join(tmpdir, "out.jpg")
            ok, msg = OpenCVStitchEngine().stitch([p1, p2], output, auto_crop=True)
            self.assertTrue(ok, msg)
            self.assertTrue(os.path.isfile(output))
            self.assertGreater(os.path.getsize(output), 1000)

    def test_orb_fallback_uses_geometry_engine(self):
        class CountingGeometry:
            def __init__(self):
                self.calls = 0

            def warp_perspective(self, image, matrix, dsize, **kwargs):
                self.calls += 1
                return cv2.warpPerspective(image, matrix, dsize, **kwargs)

            def status(self):
                return {"requested": "test", "actual": "test", "mode_tag": "test_geometry"}

        with tempfile.TemporaryDirectory() as tmpdir:
            p1, p2 = create_overlap_pair(tmpdir)
            output = os.path.join(tmpdir, "out_orb.jpg")
            geometry = CountingGeometry()
            engine = OpenCVStitchEngine(geometry_engine=geometry)
            with mock.patch.object(OpenCVStitchEngine, "_create_stitcher", return_value=None):
                ok, msg = engine.stitch([p1, p2], output, auto_crop=True)
            self.assertTrue(ok, msg)
            self.assertEqual(geometry.calls, 1)
            self.assertTrue(os.path.isfile(output))

    def test_sequential_engine_pairwise_stitch(self):
        class CountingGeometry:
            def __init__(self):
                self.calls = 0

            def warp_perspective(self, image, matrix, dsize, **kwargs):
                self.calls += 1
                return cv2.warpPerspective(image, matrix, dsize, **kwargs)

            def status(self):
                return {"requested": "test", "actual": "test", "mode_tag": "test_geometry"}

        class FailingFallback:
            def stitch(self, image_paths, output_path, auto_crop=False):
                return False, "fallback should not be used"

            def status(self):
                return {"requested": "fallback", "actual": "fallback", "mode_tag": "fallback"}

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = create_overlap_triplet(tmpdir)
            output = os.path.join(tmpdir, "out_seq.jpg")
            geometry = CountingGeometry()
            engine = SequentialPanoEngine(geometry_engine=geometry, fallback=FailingFallback())
            ok, msg = engine.stitch(paths, output, auto_crop=True)
            self.assertTrue(ok, msg)
            self.assertGreaterEqual(geometry.calls, 2)
            self.assertTrue(os.path.isfile(output))

    def test_scans_engine_uses_registration_resol_and_saves_output(self):
        class FakeStitcher:
            def __init__(self):
                self.registration_resol = None

            def setRegistrationResol(self, value):
                self.registration_resol = value

            def stitch(self, images):
                return 0, cv2.hconcat(images[:2])

        with tempfile.TemporaryDirectory() as tmpdir:
            p1, p2 = create_overlap_pair(tmpdir)
            output = os.path.join(tmpdir, "out_scans.jpg")
            fake = FakeStitcher()
            engine = ScansStitchEngine()
            with mock.patch.object(ScansStitchEngine, "_create_stitcher", return_value=fake):
                ok, msg = engine.stitch([p1, p2], output, auto_crop=True)
            self.assertTrue(ok, msg)
            self.assertEqual(fake.registration_resol, 0.6)
            self.assertTrue(os.path.isfile(output))


if __name__ == "__main__":
    unittest.main()
