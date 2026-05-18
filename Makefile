.PHONY: py-check test-camera-nv12 smoke-camera-rga smoke-camera-api-rga smoke-rga-rotate-matrix

PYTHON ?= python3

py-check:
	$(PYTHON) -m py_compile backend.py stitch_demo.py app/schemas.py app/capture/gst_capture.py app/capture/gst_raw_nv12_capture.py app/capture/v4l2_capture.py app/preprocess/cpu_engine.py app/preprocess/rga_engine.py app/services/camera_service.py tests/smoke/test_v4l2_nv12_rga_smoke.py tests/smoke/test_gst_nv12_rga_smoke.py tests/smoke/test_camera_api_rga_smoke.py tests/smoke/test_rga_rotate_matrix_smoke.py

test-camera-nv12:
	$(PYTHON) tests/smoke/test_v4l2_nv12_rga_smoke.py --frames 1

smoke-camera-rga:
	$(PYTHON) tests/smoke/test_v4l2_nv12_rga_smoke.py --frames 1 --require-rga

smoke-camera-api-rga:
	$(PYTHON) tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga

smoke-rga-rotate-matrix:
	$(PYTHON) tests/smoke/test_rga_rotate_matrix_smoke.py
