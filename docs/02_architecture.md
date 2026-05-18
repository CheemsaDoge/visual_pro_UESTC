# 02 架构说明

## 简版关系图

![当前代码关系图](assets/gui-runtime-architecture.svg)

位图导出：`docs/assets/gui-runtime-architecture.png`

## 只记这几个关键关系

- `camera_routes.py` 进入 `camera_service.py`，`FramePacket` 也在这条链路里产生，不在 routes。
- `/api/camera/stream` 和 `/api/camera/frame.jpg` 由 `backend.py` 直接处理，预览数据来自 `camera_service.py` 的运行时缓存。
- `stitch_routes.py` 进入 `stitch_service.py`，拼接时会带上 `storage_service.py`、`StitchEngine` 和 `GeometryEngine`。
- `system_routes.py` 和 `wifi_routes.py` 现在都还保留 route-local logic，不是纯粹转发到 service。
- `camera_service.stop_camera_session()` 在自动拼接时会直接调用 `run_image_stitch()`。

## 当前代码分层

```text
backend.py                 # HTTP / static / 预览流
app/routes/                # camera / stitch / system / wifi
app/services/              # camera / stitch / storage / geometry / preprocess / keyframe
app/capture/               # capture adapters
app/stitch_engine/         # OpenCV / Sequential / Scans
```
