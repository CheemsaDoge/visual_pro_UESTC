import unittest

import numpy as np

from app.geometry.opencl_geometry import OpenCLGeometryEngine


class FakeFallback:
    def __init__(self, output=None):
        self.output = output if output is not None else np.full((2, 2, 3), 9, dtype=np.uint8)
        self.warp_calls = 0
        self.remap_calls = 0

    def warp_perspective(self, image, matrix, dsize, **kwargs):
        self.warp_calls += 1
        return self.output.copy()

    def remap(self, image, map1, map2, **kwargs):
        self.remap_calls += 1
        return self.output.copy()

    def status(self):
        return {"requested": "cpu", "actual": "cpu", "mode_tag": "geometry_cpu"}


class FakeRuntime:
    def __init__(self, available=True, warp_output=None, warp_error=None):
        self.available = available
        self.warp_output = warp_output if warp_output is not None else np.full((2, 2, 3), 7, dtype=np.uint8)
        self.warp_error = warp_error

    def status(self):
        return {
            "available": self.available,
            "reason": "ok" if self.available else "runtime unavailable",
            "platform_name": "ARM Platform" if self.available else "",
            "device_name": "Mali-G610 r0p0" if self.available else "",
            "lib_name": "libOpenCL.so",
        }

    def warp_perspective(self, image, matrix, dsize, **kwargs):
        if self.warp_error is not None:
            raise RuntimeError(self.warp_error)
        return self.warp_output.copy()


class OpenCLGeometryEngineTest(unittest.TestCase):
    def test_warp_uses_direct_runtime_when_available(self):
        fallback = FakeFallback()
        runtime = FakeRuntime(available=True, warp_output=np.full((3, 4, 3), 5, dtype=np.uint8))
        engine = OpenCLGeometryEngine(fallback=fallback, runtime=runtime)

        out = engine.warp_perspective(np.zeros((3, 4, 3), dtype=np.uint8), np.eye(3, dtype=np.float32), (4, 3))

        self.assertEqual(engine.actual_name, "opencl")
        self.assertEqual(engine.mode_tag, "geometry_opencl_direct")
        self.assertEqual(engine.active_calls, 1)
        self.assertEqual(engine.fallback_calls, 0)
        self.assertEqual(fallback.warp_calls, 0)
        self.assertTrue(np.array_equal(out, np.full((3, 4, 3), 5, dtype=np.uint8)))

    def test_warp_falls_back_when_direct_runtime_raises(self):
        fallback = FakeFallback(output=np.full((2, 2, 3), 3, dtype=np.uint8))
        runtime = FakeRuntime(available=True, warp_error="kernel launch failed")
        engine = OpenCLGeometryEngine(fallback=fallback, runtime=runtime)

        out = engine.warp_perspective(np.zeros((2, 2, 3), dtype=np.uint8), np.eye(3, dtype=np.float32), (2, 2))

        self.assertEqual(engine.active_calls, 0)
        self.assertEqual(engine.fallback_calls, 1)
        self.assertIn("kernel launch failed", engine.last_error)
        self.assertEqual(fallback.warp_calls, 1)
        self.assertTrue(np.array_equal(out, np.full((2, 2, 3), 3, dtype=np.uint8)))

    def test_remap_is_explicit_cpu_fallback_for_now(self):
        fallback = FakeFallback(output=np.full((2, 2, 3), 4, dtype=np.uint8))
        runtime = FakeRuntime(available=True)
        engine = OpenCLGeometryEngine(fallback=fallback, runtime=runtime)

        out = engine.remap(np.zeros((2, 2, 3), dtype=np.uint8), None, None)

        self.assertEqual(engine.remap_fallback_calls, 1)
        self.assertEqual(fallback.remap_calls, 1)
        self.assertIn("remap is not implemented", engine.last_error)
        self.assertTrue(np.array_equal(out, np.full((2, 2, 3), 4, dtype=np.uint8)))

    def test_status_reports_cpu_when_runtime_unavailable(self):
        fallback = FakeFallback()
        runtime = FakeRuntime(available=False)
        engine = OpenCLGeometryEngine(fallback=fallback, runtime=runtime)

        status = engine.status()

        self.assertEqual(status["actual"], "cpu")
        self.assertEqual(status["mode_tag"], "opencl_fallback_cpu")
        self.assertFalse(status["available"])


if __name__ == "__main__":
    unittest.main()
