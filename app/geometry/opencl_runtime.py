#!/usr/bin/env python3
"""Minimal direct OpenCL runtime for geometry operations."""
from __future__ import annotations

import ctypes
from typing import Any, Dict, Tuple

import numpy as np


CL_SUCCESS = 0
CL_DEVICE_TYPE_ALL = 0xFFFFFFFF
CL_MEM_READ_ONLY = 1 << 2
CL_MEM_WRITE_ONLY = 1 << 1
CL_PROGRAM_BUILD_LOG = 0x1183

CV_INTER_NEAREST = 0
CV_INTER_LINEAR = 1
CV_WARP_INVERSE_MAP = 16
CV_BORDER_CONSTANT = 0

KERNEL_SOURCE = r"""
inline uchar read_channel(
    __global const uchar* src,
    int src_w,
    int src_h,
    int src_stride,
    int x,
    int y,
    int c,
    uchar border
) {
    if (x < 0 || y < 0 || x >= src_w || y >= src_h) {
        return border;
    }
    return src[y * src_stride + x * 3 + c];
}

__kernel void warp_perspective_bgr(
    __global const uchar* src,
    int src_w,
    int src_h,
    int src_stride,
    __global uchar* dst,
    int dst_w,
    int dst_h,
    int dst_stride,
    __global const float* inv_m,
    int interpolation,
    uchar border_b,
    uchar border_g,
    uchar border_r
) {
    int x = get_global_id(0);
    int y = get_global_id(1);
    if (x >= dst_w || y >= dst_h) {
        return;
    }

    int dst_idx = y * dst_stride + x * 3;
    float denom = inv_m[6] * (float)x + inv_m[7] * (float)y + inv_m[8];
    if (fabs(denom) < 1e-8f) {
        dst[dst_idx + 0] = border_b;
        dst[dst_idx + 1] = border_g;
        dst[dst_idx + 2] = border_r;
        return;
    }

    float src_x = (inv_m[0] * (float)x + inv_m[1] * (float)y + inv_m[2]) / denom;
    float src_y = (inv_m[3] * (float)x + inv_m[4] * (float)y + inv_m[5]) / denom;

    uchar borders[3] = {border_b, border_g, border_r};
    if (interpolation == 0) {
        int sx = (int)floor(src_x + 0.5f);
        int sy = (int)floor(src_y + 0.5f);
        dst[dst_idx + 0] = read_channel(src, src_w, src_h, src_stride, sx, sy, 0, border_b);
        dst[dst_idx + 1] = read_channel(src, src_w, src_h, src_stride, sx, sy, 1, border_g);
        dst[dst_idx + 2] = read_channel(src, src_w, src_h, src_stride, sx, sy, 2, border_r);
        return;
    }

    int x0 = (int)floor(src_x);
    int y0 = (int)floor(src_y);
    int x1 = x0 + 1;
    int y1 = y0 + 1;
    float fx = src_x - (float)x0;
    float fy = src_y - (float)y0;

    for (int c = 0; c < 3; ++c) {
        float v00 = (float)read_channel(src, src_w, src_h, src_stride, x0, y0, c, borders[c]);
        float v10 = (float)read_channel(src, src_w, src_h, src_stride, x1, y0, c, borders[c]);
        float v01 = (float)read_channel(src, src_w, src_h, src_stride, x0, y1, c, borders[c]);
        float v11 = (float)read_channel(src, src_w, src_h, src_stride, x1, y1, c, borders[c]);
        float top = v00 + (v10 - v00) * fx;
        float bottom = v01 + (v11 - v01) * fx;
        float value = top + (bottom - top) * fy;
        float clipped = fmax(0.0f, fmin(255.0f, value));
        dst[dst_idx + c] = (uchar)(clipped + 0.5f);
    }
}

__kernel void linear_blend_bgr(
    __global const uchar* base,
    __global const uchar* warped,
    __global const uchar* mask1,
    __global const uchar* mask2,
    __global uchar* out,
    int pixel_count
) {
    int index = get_global_id(0);
    if (index >= pixel_count) {
        return;
    }
    int offset = index * 3;
    if (mask2[index] == 0) {
        out[offset] = base[offset];
        out[offset + 1] = base[offset + 1];
        out[offset + 2] = base[offset + 2];
    } else if (mask1[index] == 0) {
        out[offset] = warped[offset];
        out[offset + 1] = warped[offset + 1];
        out[offset + 2] = warped[offset + 2];
    } else {
        out[offset] = (uchar)(((int)base[offset] + (int)warped[offset]) / 2);
        out[offset + 1] = (uchar)(((int)base[offset + 1] + (int)warped[offset + 1]) / 2);
        out[offset + 2] = (uchar)(((int)base[offset + 2] + (int)warped[offset + 2]) / 2);
    }
}

inline uchar sample_bgr_clamped(
    __global const uchar* src,
    int width,
    int height,
    int stride,
    int x,
    int y,
    int channel
) {
    x = max(0, min(width - 1, x));
    y = max(0, min(height - 1, y));
    return src[y * stride + x * 3 + channel];
}

__kernel void unsharp_bgr(
    __global const uchar* src,
    int width,
    int height,
    int src_stride,
    __global uchar* dst,
    int dst_stride
) {
    int x = get_global_id(0);
    int y = get_global_id(1);
    if (x >= width || y >= height) {
        return;
    }
    int weights[5] = {1, 4, 6, 4, 1};
    int offset = y * dst_stride + x * 3;
    for (int channel = 0; channel < 3; ++channel) {
        int sum = 0;
        for (int ky = -2; ky <= 2; ++ky) {
            for (int kx = -2; kx <= 2; ++kx) {
                sum += weights[kx + 2] * weights[ky + 2]
                    * (int)sample_bgr_clamped(src, width, height, src_stride, x + kx, y + ky, channel);
            }
        }
        float blur = (float)sum / 256.0f;
        float sharpened = 1.3f * (float)src[y * src_stride + x * 3 + channel] - 0.3f * blur;
        dst[offset + channel] = convert_uchar_sat_rte(sharpened);
    }
}
"""


class DirectOpenCLRuntime:
    """Small ctypes-based OpenCL runtime for BGR warpPerspective."""

    def __init__(self, lib_name: str = "libOpenCL.so", kernel_source: str = KERNEL_SOURCE) -> None:
        self.lib_name = lib_name
        self.kernel_source = kernel_source
        self.available = False
        self.reason = ""
        self.platform_name = ""
        self.platform_vendor = ""
        self.device_name = ""
        self.context = None
        self.queue = None
        self.program = None
        self.kernel = None
        self.kernels = {}
        self._init_types()
        try:
            self.lib = ctypes.CDLL(self.lib_name)
        except Exception as exc:
            self.reason = f"load failed: {exc}"
            self.lib = None
            return
        try:
            self._bind()
            self._create_runtime()
        except Exception as exc:
            self.reason = f"runtime init failed: {exc}"
            self.close()

    def _init_types(self) -> None:
        self.cl_bool = ctypes.c_uint
        self.cl_uint = ctypes.c_uint
        self.cl_int = ctypes.c_int
        self.cl_ulong = ctypes.c_ulong
        self.size_t = ctypes.c_size_t
        self.cl_platform_id = ctypes.c_void_p
        self.cl_device_id = ctypes.c_void_p
        self.cl_context = ctypes.c_void_p
        self.cl_command_queue = ctypes.c_void_p
        self.cl_mem = ctypes.c_void_p
        self.cl_program = ctypes.c_void_p
        self.cl_kernel = ctypes.c_void_p

    def _bind(self) -> None:
        lib = self.lib
        lib.clGetPlatformIDs.argtypes = [
            self.cl_uint,
            ctypes.POINTER(self.cl_platform_id),
            ctypes.POINTER(self.cl_uint),
        ]
        lib.clGetPlatformIDs.restype = self.cl_int
        lib.clGetPlatformInfo.argtypes = [
            self.cl_platform_id,
            self.cl_uint,
            self.size_t,
            ctypes.c_void_p,
            ctypes.POINTER(self.size_t),
        ]
        lib.clGetPlatformInfo.restype = self.cl_int
        lib.clGetDeviceIDs.argtypes = [
            self.cl_platform_id,
            self.cl_ulong,
            self.cl_uint,
            ctypes.POINTER(self.cl_device_id),
            ctypes.POINTER(self.cl_uint),
        ]
        lib.clGetDeviceIDs.restype = self.cl_int
        lib.clGetDeviceInfo.argtypes = [
            self.cl_device_id,
            self.cl_uint,
            self.size_t,
            ctypes.c_void_p,
            ctypes.POINTER(self.size_t),
        ]
        lib.clGetDeviceInfo.restype = self.cl_int
        lib.clCreateContext.argtypes = [
            ctypes.c_void_p,
            self.cl_uint,
            ctypes.POINTER(self.cl_device_id),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(self.cl_int),
        ]
        lib.clCreateContext.restype = self.cl_context
        lib.clCreateCommandQueue.argtypes = [
            self.cl_context,
            self.cl_device_id,
            self.cl_ulong,
            ctypes.POINTER(self.cl_int),
        ]
        lib.clCreateCommandQueue.restype = self.cl_command_queue
        lib.clCreateBuffer.argtypes = [
            self.cl_context,
            self.cl_ulong,
            self.size_t,
            ctypes.c_void_p,
            ctypes.POINTER(self.cl_int),
        ]
        lib.clCreateBuffer.restype = self.cl_mem
        lib.clCreateProgramWithSource.argtypes = [
            self.cl_context,
            self.cl_uint,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(self.size_t),
            ctypes.POINTER(self.cl_int),
        ]
        lib.clCreateProgramWithSource.restype = self.cl_program
        lib.clBuildProgram.argtypes = [
            self.cl_program,
            self.cl_uint,
            ctypes.POINTER(self.cl_device_id),
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.clBuildProgram.restype = self.cl_int
        lib.clGetProgramBuildInfo.argtypes = [
            self.cl_program,
            self.cl_device_id,
            self.cl_uint,
            self.size_t,
            ctypes.c_void_p,
            ctypes.POINTER(self.size_t),
        ]
        lib.clGetProgramBuildInfo.restype = self.cl_int
        lib.clCreateKernel.argtypes = [
            self.cl_program,
            ctypes.c_char_p,
            ctypes.POINTER(self.cl_int),
        ]
        lib.clCreateKernel.restype = self.cl_kernel
        lib.clSetKernelArg.argtypes = [
            self.cl_kernel,
            self.cl_uint,
            self.size_t,
            ctypes.c_void_p,
        ]
        lib.clSetKernelArg.restype = self.cl_int
        lib.clEnqueueWriteBuffer.argtypes = [
            self.cl_command_queue,
            self.cl_mem,
            self.cl_bool,
            self.size_t,
            self.size_t,
            ctypes.c_void_p,
            self.cl_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.clEnqueueWriteBuffer.restype = self.cl_int
        lib.clEnqueueNDRangeKernel.argtypes = [
            self.cl_command_queue,
            self.cl_kernel,
            self.cl_uint,
            ctypes.POINTER(self.size_t),
            ctypes.POINTER(self.size_t),
            ctypes.POINTER(self.size_t),
            self.cl_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.clEnqueueNDRangeKernel.restype = self.cl_int
        lib.clEnqueueReadBuffer.argtypes = [
            self.cl_command_queue,
            self.cl_mem,
            self.cl_bool,
            self.size_t,
            self.size_t,
            ctypes.c_void_p,
            self.cl_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.clEnqueueReadBuffer.restype = self.cl_int
        lib.clFinish.argtypes = [self.cl_command_queue]
        lib.clFinish.restype = self.cl_int
        lib.clReleaseMemObject.argtypes = [self.cl_mem]
        lib.clReleaseMemObject.restype = self.cl_int
        lib.clReleaseKernel.argtypes = [self.cl_kernel]
        lib.clReleaseKernel.restype = self.cl_int
        lib.clReleaseProgram.argtypes = [self.cl_program]
        lib.clReleaseProgram.restype = self.cl_int
        lib.clReleaseCommandQueue.argtypes = [self.cl_command_queue]
        lib.clReleaseCommandQueue.restype = self.cl_int
        lib.clReleaseContext.argtypes = [self.cl_context]
        lib.clReleaseContext.restype = self.cl_int

    def _get_info_string(self, fn, obj, key: int) -> str:
        size = self.size_t()
        rc = fn(obj, key, 0, None, ctypes.byref(size))
        if rc != CL_SUCCESS or not size.value:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        rc = fn(obj, key, size.value, buf, None)
        if rc != CL_SUCCESS:
            return ""
        return buf.value.decode("utf-8", "ignore")

    def _get_build_log(self, program, device) -> str:
        size = self.size_t()
        rc = self.lib.clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, 0, None, ctypes.byref(size))
        if rc != CL_SUCCESS or not size.value:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        rc = self.lib.clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, size.value, buf, None)
        if rc != CL_SUCCESS:
            return ""
        return buf.value.decode("utf-8", "ignore")

    def _create_runtime(self) -> None:
        num_platforms = self.cl_uint()
        rc = self.lib.clGetPlatformIDs(0, None, ctypes.byref(num_platforms))
        if rc != CL_SUCCESS or num_platforms.value == 0:
            raise RuntimeError(f"clGetPlatformIDs rc={int(rc)} count={int(num_platforms.value)}")
        platforms = (self.cl_platform_id * num_platforms.value)()
        rc = self.lib.clGetPlatformIDs(num_platforms.value, platforms, None)
        if rc != CL_SUCCESS:
            raise RuntimeError(f"clGetPlatformIDs(fetch) rc={int(rc)}")
        platform = self.cl_platform_id(platforms[0])
        self.platform_name = self._get_info_string(self.lib.clGetPlatformInfo, platform, 0x0902)
        self.platform_vendor = self._get_info_string(self.lib.clGetPlatformInfo, platform, 0x0903)

        num_devices = self.cl_uint()
        rc = self.lib.clGetDeviceIDs(platform, CL_DEVICE_TYPE_ALL, 0, None, ctypes.byref(num_devices))
        if rc != CL_SUCCESS or num_devices.value == 0:
            raise RuntimeError(f"clGetDeviceIDs rc={int(rc)} count={int(num_devices.value)}")
        devices = (self.cl_device_id * num_devices.value)()
        rc = self.lib.clGetDeviceIDs(platform, CL_DEVICE_TYPE_ALL, num_devices.value, devices, None)
        if rc != CL_SUCCESS:
            raise RuntimeError(f"clGetDeviceIDs(fetch) rc={int(rc)}")
        self.device = self.cl_device_id(devices[0])
        self.device_name = self._get_info_string(self.lib.clGetDeviceInfo, self.device, 0x102B)

        err = self.cl_int()
        self.context = self.lib.clCreateContext(None, 1, ctypes.byref(self.device), None, None, ctypes.byref(err))
        if not self.context or err.value != CL_SUCCESS:
            raise RuntimeError(f"clCreateContext rc={int(err.value)}")
        self.queue = self.lib.clCreateCommandQueue(self.context, self.device, 0, ctypes.byref(err))
        if not self.queue or err.value != CL_SUCCESS:
            raise RuntimeError(f"clCreateCommandQueue rc={int(err.value)}")

        source_bytes = self.kernel_source.encode("utf-8")
        source_ptr = ctypes.c_char_p(source_bytes)
        source_len = self.size_t(len(source_bytes))
        self.program = self.lib.clCreateProgramWithSource(
            self.context,
            1,
            ctypes.byref(source_ptr),
            ctypes.byref(source_len),
            ctypes.byref(err),
        )
        if not self.program or err.value != CL_SUCCESS:
            raise RuntimeError(f"clCreateProgramWithSource rc={int(err.value)}")
        rc = self.lib.clBuildProgram(self.program, 1, ctypes.byref(self.device), None, None, None)
        if rc != CL_SUCCESS:
            raise RuntimeError(f"clBuildProgram rc={int(rc)} log={self._get_build_log(self.program, self.device)}")
        for kernel_name in ("warp_perspective_bgr", "linear_blend_bgr", "unsharp_bgr"):
            kernel = self.lib.clCreateKernel(self.program, kernel_name.encode("ascii"), ctypes.byref(err))
            if not kernel or err.value != CL_SUCCESS:
                raise RuntimeError(f"clCreateKernel({kernel_name}) rc={int(err.value)}")
            self.kernels[kernel_name] = kernel
        self.kernel = self.kernels["warp_perspective_bgr"]
        self.available = True
        self.reason = "ok"

    def _require_supported(self, flags: int, border_mode: int) -> int:
        interpolation = int(flags & 7)
        if interpolation not in (CV_INTER_NEAREST, CV_INTER_LINEAR):
            raise ValueError(f"unsupported interpolation: {interpolation}")
        if int(border_mode) != CV_BORDER_CONSTANT:
            raise ValueError(f"unsupported border mode: {border_mode}")
        return interpolation

    @staticmethod
    def _normalize_border_value(border_value: Any) -> Tuple[int, int, int]:
        if isinstance(border_value, (tuple, list)):
            values = list(border_value[:3]) + [0, 0, 0]
            return tuple(max(0, min(255, int(v))) for v in values[:3])
        scalar = max(0, min(255, int(border_value)))
        return (scalar, scalar, scalar)

    def _inverse_matrix(self, matrix: Any, flags: int) -> np.ndarray:
        mat = np.asarray(matrix, dtype=np.float32).reshape(3, 3)
        if int(flags) & CV_WARP_INVERSE_MAP:
            return mat.astype(np.float32, copy=True)
        det = float(np.linalg.det(mat))
        if abs(det) < 1e-8:
            raise ValueError("homography is singular")
        return np.linalg.inv(mat).astype(np.float32, copy=False)

    def _create_buffer(self, size_bytes: int, flags: int):
        err = self.cl_int()
        buf = self.lib.clCreateBuffer(self.context, flags, self.size_t(size_bytes), None, ctypes.byref(err))
        if not buf or err.value != CL_SUCCESS:
            raise RuntimeError(f"clCreateBuffer rc={int(err.value)} size={int(size_bytes)}")
        return buf

    def _set_kernel_arg(self, index: int, value, *, kernel=None) -> None:
        target = kernel or self.kernel
        rc = self.lib.clSetKernelArg(target, self.cl_uint(index), self.size_t(ctypes.sizeof(value)), ctypes.byref(value))
        if rc != CL_SUCCESS:
            raise RuntimeError(f"clSetKernelArg[{index}] rc={int(rc)}")

    def _write_buffer(self, buffer, image, label: str) -> None:
        rc = self.lib.clEnqueueWriteBuffer(
            self.queue,
            buffer,
            self.cl_bool(1),
            0,
            self.size_t(image.nbytes),
            image.ctypes.data_as(ctypes.c_void_p),
            0,
            None,
            None,
        )
        if rc != CL_SUCCESS:
            raise RuntimeError(f"clEnqueueWriteBuffer({label}) rc={int(rc)}")

    def _read_buffer(self, buffer, image) -> None:
        rc = self.lib.clEnqueueReadBuffer(
            self.queue,
            buffer,
            self.cl_bool(1),
            0,
            self.size_t(image.nbytes),
            image.ctypes.data_as(ctypes.c_void_p),
            0,
            None,
            None,
        )
        if rc != CL_SUCCESS:
            raise RuntimeError(f"clEnqueueReadBuffer rc={int(rc)}")

    def linear_blend(self, base: Any, warped: Any, mask1: Any, mask2: Any):
        """Blend a BGR pair on the OpenCL device using the existing coverage masks."""
        if not self.available:
            raise RuntimeError(self.reason or "runtime unavailable")
        base = np.ascontiguousarray(np.asarray(base))
        warped = np.ascontiguousarray(np.asarray(warped))
        mask1 = np.ascontiguousarray(np.asarray(mask1))
        mask2 = np.ascontiguousarray(np.asarray(mask2))
        if base.dtype != np.uint8 or warped.dtype != np.uint8 or base.ndim != 3 or base.shape[2] != 3:
            raise ValueError("linear blend requires uint8 BGR images")
        if warped.shape != base.shape or mask1.shape != base.shape[:2] or mask2.shape != base.shape[:2]:
            raise ValueError("linear blend input shapes do not match")

        output = np.empty_like(base)
        buffers = [
            self._create_buffer(int(base.nbytes), CL_MEM_READ_ONLY),
            self._create_buffer(int(warped.nbytes), CL_MEM_READ_ONLY),
            self._create_buffer(int(mask1.nbytes), CL_MEM_READ_ONLY),
            self._create_buffer(int(mask2.nbytes), CL_MEM_READ_ONLY),
            self._create_buffer(int(output.nbytes), CL_MEM_WRITE_ONLY),
        ]
        try:
            for buffer, image, label in zip(buffers[:4], (base, warped, mask1, mask2), ("base", "warped", "mask1", "mask2")):
                self._write_buffer(buffer, image, label)
            kernel = self.kernels["linear_blend_bgr"]
            for index, buffer in enumerate(buffers):
                self._set_kernel_arg(index, self.cl_mem(buffer), kernel=kernel)
            pixels = int(mask1.size)
            self._set_kernel_arg(5, self.cl_int(pixels), kernel=kernel)
            global_size = (self.size_t * 1)(pixels)
            rc = self.lib.clEnqueueNDRangeKernel(self.queue, kernel, self.cl_uint(1), None, global_size, None, 0, None, None)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clEnqueueNDRangeKernel(linear_blend) rc={int(rc)}")
            if self.lib.clFinish(self.queue) != CL_SUCCESS:
                raise RuntimeError("clFinish(linear_blend) failed")
            self._read_buffer(buffers[4], output)
            return output
        finally:
            for buffer in buffers:
                if buffer:
                    self.lib.clReleaseMemObject(buffer)

    def unsharp(self, image: Any):
        """Apply the stitch postprocess sharpen kernel on the OpenCL device."""
        if not self.available:
            raise RuntimeError(self.reason or "runtime unavailable")
        src = np.ascontiguousarray(np.asarray(image))
        if src.dtype != np.uint8 or src.ndim != 3 or src.shape[2] != 3:
            raise ValueError("unsharp requires a uint8 BGR image")
        height, width = src.shape[:2]
        output = np.empty_like(src)
        buffers = [
            self._create_buffer(int(src.nbytes), CL_MEM_READ_ONLY),
            self._create_buffer(int(output.nbytes), CL_MEM_WRITE_ONLY),
        ]
        try:
            self._write_buffer(buffers[0], src, "unsharp")
            kernel = self.kernels["unsharp_bgr"]
            self._set_kernel_arg(0, self.cl_mem(buffers[0]), kernel=kernel)
            self._set_kernel_arg(1, self.cl_int(width), kernel=kernel)
            self._set_kernel_arg(2, self.cl_int(height), kernel=kernel)
            self._set_kernel_arg(3, self.cl_int(src.strides[0]), kernel=kernel)
            self._set_kernel_arg(4, self.cl_mem(buffers[1]), kernel=kernel)
            self._set_kernel_arg(5, self.cl_int(output.strides[0]), kernel=kernel)
            global_size = (self.size_t * 2)(width, height)
            rc = self.lib.clEnqueueNDRangeKernel(self.queue, kernel, self.cl_uint(2), None, global_size, None, 0, None, None)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clEnqueueNDRangeKernel(unsharp) rc={int(rc)}")
            if self.lib.clFinish(self.queue) != CL_SUCCESS:
                raise RuntimeError("clFinish(unsharp) failed")
            self._read_buffer(buffers[1], output)
            return output
        finally:
            for buffer in buffers:
                if buffer:
                    self.lib.clReleaseMemObject(buffer)

    def warp_perspective(self, image: Any, matrix: Any, dsize: Tuple[int, int], **kwargs: Any):
        if not self.available:
            raise RuntimeError(self.reason or "runtime unavailable")
        src = np.ascontiguousarray(np.asarray(image))
        if src.ndim != 3 or src.shape[2] != 3 or src.dtype != np.uint8:
            raise ValueError("only contiguous uint8 BGR images are supported")
        dst_w, dst_h = int(dsize[0]), int(dsize[1])
        if dst_w <= 0 or dst_h <= 0:
            raise ValueError(f"invalid dsize: {dsize}")

        flags = int(kwargs.get("flags", CV_INTER_LINEAR))
        border_mode = int(kwargs.get("borderMode", CV_BORDER_CONSTANT))
        border_value = kwargs.get("borderValue", 0)
        interpolation = self._require_supported(flags, border_mode)
        inv_matrix = np.ascontiguousarray(self._inverse_matrix(matrix, flags))
        border_bgr = self._normalize_border_value(border_value)

        src_h, src_w = src.shape[:2]
        src_stride = src.strides[0]
        dst = np.empty((dst_h, dst_w, 3), dtype=np.uint8)
        dst_stride = dst.strides[0]

        src_bytes = int(src.nbytes)
        dst_bytes = int(dst.nbytes)
        mat_bytes = int(inv_matrix.nbytes)
        buf_src = self._create_buffer(src_bytes, CL_MEM_READ_ONLY)
        buf_dst = self._create_buffer(dst_bytes, CL_MEM_WRITE_ONLY)
        buf_mat = self._create_buffer(mat_bytes, CL_MEM_READ_ONLY)

        try:
            rc = self.lib.clEnqueueWriteBuffer(self.queue, buf_src, self.cl_bool(1), 0, self.size_t(src_bytes), src.ctypes.data_as(ctypes.c_void_p), 0, None, None)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clEnqueueWriteBuffer(src) rc={int(rc)}")
            rc = self.lib.clEnqueueWriteBuffer(self.queue, buf_mat, self.cl_bool(1), 0, self.size_t(mat_bytes), inv_matrix.ctypes.data_as(ctypes.c_void_p), 0, None, None)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clEnqueueWriteBuffer(mat) rc={int(rc)}")

            buf_src_handle = self.cl_mem(buf_src)
            buf_dst_handle = self.cl_mem(buf_dst)
            buf_mat_handle = self.cl_mem(buf_mat)
            self._set_kernel_arg(0, buf_src_handle)
            self._set_kernel_arg(1, self.cl_int(src_w))
            self._set_kernel_arg(2, self.cl_int(src_h))
            self._set_kernel_arg(3, self.cl_int(src_stride))
            self._set_kernel_arg(4, buf_dst_handle)
            self._set_kernel_arg(5, self.cl_int(dst_w))
            self._set_kernel_arg(6, self.cl_int(dst_h))
            self._set_kernel_arg(7, self.cl_int(dst_stride))
            self._set_kernel_arg(8, buf_mat_handle)
            self._set_kernel_arg(9, self.cl_int(interpolation))
            self._set_kernel_arg(10, ctypes.c_ubyte(border_bgr[0]))
            self._set_kernel_arg(11, ctypes.c_ubyte(border_bgr[1]))
            self._set_kernel_arg(12, ctypes.c_ubyte(border_bgr[2]))

            global_size = (self.size_t * 2)(dst_w, dst_h)
            rc = self.lib.clEnqueueNDRangeKernel(self.queue, self.kernel, self.cl_uint(2), None, global_size, None, 0, None, None)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clEnqueueNDRangeKernel rc={int(rc)}")
            rc = self.lib.clFinish(self.queue)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clFinish rc={int(rc)}")
            rc = self.lib.clEnqueueReadBuffer(self.queue, buf_dst, self.cl_bool(1), 0, self.size_t(dst_bytes), dst.ctypes.data_as(ctypes.c_void_p), 0, None, None)
            if rc != CL_SUCCESS:
                raise RuntimeError(f"clEnqueueReadBuffer rc={int(rc)}")
            return dst
        finally:
            for buf in (buf_src, buf_dst, buf_mat):
                if buf:
                    try:
                        self.lib.clReleaseMemObject(buf)
                    except Exception:
                        pass

    def status(self) -> Dict[str, Any]:
        return {
            "available": bool(self.available),
            "reason": self.reason,
            "platform_name": self.platform_name,
            "platform_vendor": self.platform_vendor,
            "device_name": self.device_name,
            "lib_name": self.lib_name,
        }

    def close(self) -> None:
        for kernel in getattr(self, "kernels", {}).values():
            try:
                self.lib.clReleaseKernel(kernel)
            except Exception:
                pass
        self.kernels = {}
        for attr, release in (
            ("program", getattr(self.lib, "clReleaseProgram", None) if self.lib else None),
            ("queue", getattr(self.lib, "clReleaseCommandQueue", None) if self.lib else None),
            ("context", getattr(self.lib, "clReleaseContext", None) if self.lib else None),
        ):
            obj = getattr(self, attr, None)
            if obj and release is not None:
                try:
                    release(obj)
                except Exception:
                    pass
            setattr(self, attr, None)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
