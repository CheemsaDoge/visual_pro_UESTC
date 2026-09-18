# 00 项目概览

## 背景

本项目是运行在正点原子 **ATK-DLRK3588** 开发板上的轻量级 Python/HTML 图像拼接工作台。当前形态是：单路 IMX415 摄像头通过 MIPI CSI + RKISP 采集，云台旋转拍摄多帧，然后离线/半离线拼接。

## 固定环境

- 开发板：正点原子 ATK-DLRK3588
- 系统：Buildroot 2021.11
- 内核：Linux 5.10.209 aarch64
- 相机链路：MIPI CSI + RKISP
- 传感器：IMX415
- 当前采集节点：配置默认是动态别名 `/dev/video-camera0`（`config.json` 的 `stitch.camera.source`）。`start_myui.sh` 会在启动前逐个探测 `rkisp_mainpath` 节点并把别名指向第一个能出帧的设备；`app/services/camera_service.py` 的 `CAMERA_DEVICE_HINTS` 备选顺序是 `/dev/video-camera0`、`/dev/video44`、`/dev/video22`、`/dev/video31`、`/dev/video62`。
- 历史说明：早期文档中的固定 `/dev/video44` 在当前板端镜像上已不存在，不要再把它当成硬编码节点。
- 当前格式：NV12（`stitch.camera.pixel_format`，代码只接受 `NV12`/`NV21`）
- 当前采集后端：`auto_raw`（先试 GStreamer raw NV12，再试 `v4l2-ctl` raw NV12，最后退到 legacy BGR/OpenCV 路径）
- OpenCV：Python `cv2` 可用，板端已知版本 `4.5.4`

## 总路线

当前和后续优化必须保持这条主线：

1. **RGA first**：先把 NV12→BGR、resize、rotate、preview 等预处理边界抽象出来，并优先接 RGA。
2. **GPU/OpenCL next**：再做 `warpPerspective`、`remap`、柱面投影等几何变换加速。
3. **NPU/RKNN later**：最后做关键帧筛选、模糊帧过滤、重复帧过滤。
4. 后续再重写/优化拼接算法本身，不继续只依赖 OpenCV Stitcher。

## 当前代码进度对照

| 主线阶段 | 代码实现 | 当前状态 |
| --- | --- | --- |
| RGA | `app/preprocess/rga_engine.py` + `native/rga/libmyui_rga.so` | 已通过 `ctypes` 真实调用；`mode_tag` 可为 `rga_ready` / `rga_active` / `rga_fallback_cpu` |
| GPU/OpenCL | `app/geometry/opencl_geometry.py` + `app/geometry/opencl_runtime.py` | `warp_perspective()` 走 direct OpenCL；`remap()` 明确 CPU fallback |
| NPU/RKNN | `app/selector/rknn_selector.py` | 仍是占位，`mode_tag = rknn_fallback_cpu_basic` |
| 拼接算法 | `app/stitch_engine/` | 已有 `builtin`(OpenCV PANORAMA)、`sequential`(两两 ORB)、`scans`(OpenCV SCANS)、`script`(外部脚本) 四种 |

## 当前阶段目标

本阶段交付重点不是重写前端或完整算法，而是：

- 把大一统 `backend.py` 拆成模块化后端（已完成，当前 `backend.py` 227 行，只做 HTTP/静态/预览流）。
- 建立可插拔引擎：`PreprocessEngine`、`GeometryEngine`、`KeyframeSelector`、`StitchEngine`（已完成）。
- 落位 RGA 接口和 fallback 机制（已完成并在板端验证过 `rga_active`）。
- 加入测试和 benchmark 初版（已完成：`tests/unit`、`tests/integration`、`tests/smoke`、`tests/benchmark/run_benchmark.py`）。
- 建立持续文档体系，方便新对话 5～10 分钟内接手。
