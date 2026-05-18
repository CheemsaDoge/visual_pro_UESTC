# 00 项目概览

## 背景

本项目是运行在正点原子 **ATK-DLRK3588** 开发板上的轻量级 Python/HTML 图像拼接工作台。当前形态是：单路 IMX415 摄像头通过 MIPI CSI + RKISP 采集，云台旋转拍摄多帧，然后离线/半离线拼接。

## 固定环境

- 开发板：正点原子 ATK-DLRK3588
- 系统：Buildroot 2021.11
- 内核：Linux 5.10.209 aarch64
- 相机链路：MIPI CSI + RKISP
- 传感器：IMX415
- 当前采集节点：`/dev/video44`
- 当前格式：NV12
- OpenCV：Python `cv2` 可用，已知版本 `4.5.4`

## 总路线

当前和后续优化必须保持这条主线：

1. **RGA first**：先把 NV12→BGR、resize、rotate、preview 等预处理边界抽象出来，并优先接 RGA。
2. **GPU/OpenCL next**：再做 `warpPerspective`、`remap`、柱面投影等几何变换加速。
3. **NPU/RKNN later**：最后做关键帧筛选、模糊帧过滤、重复帧过滤。
4. 后续再重写/优化拼接算法本身，不继续只依赖 OpenCV Stitcher。

## 当前阶段目标

本阶段交付重点不是重写前端或完整算法，而是：

- 把大一统 `backend.py` 拆成模块化后端。
- 建立可插拔引擎：`PreprocessEngine`、`GeometryEngine`、`KeyframeSelector`、`StitchEngine`。
- 落位 RGA 接口和 fallback 机制。
- 加入测试和 benchmark 初版。
- 建立持续文档体系，方便新对话 5～10 分钟内接手。
