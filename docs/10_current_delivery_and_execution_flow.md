# 本次交付与当前执行链

本文只说明当前已经部署到开发板的内容，以及用户从打开页面到看到全景图时，程序实际经过了哪些文件和函数。

## 这次做了什么

1. 接入离线 Pannellum 2.5.7。资源在 `vendor/pannellum/`，开发板展示全景时不需要联网。
2. 修改 `stitch.html`：静态图片拼接成功、或相机停止且拼接成功后，直接打开可拖动的全景查看器，不再只显示一张普通图片。
3. 在 `config.json` 增加 `stitch.viewer`。当前默认值是水平 `360°`、垂直 `60°`，上下俯仰限制为 `-25°` 到 `25°`。之后只改配置即可校准，不必改前端代码。
4. 将前端、后端配置、Pannellum 资源和启动脚本部署到开发板；文件传输均做了 MD5 校验。
5. 清理了开发板可再生的 Python `__pycache__` 和 Chromium 临时 profile；没有删除用户拍摄的输入图片和已有拼接结果。
6. 相机故障排查后重启了开发板，并重启 MyUI 服务。当前验证：`/dev/video-camera0` 指向可用的 RKISP 主节点（本次启动时为 `video22`）、相机可连续出帧、RGA 预览可用、预览 JPEG 可正常读取。

相机节点号可能随启动变化，因此程序使用 `/dev/video-camera0` 这个动态别名，而不是把 `video22` 写死。

## 当前配置

- 服务地址：`http://127.0.0.1:18080`
- 拼接引擎：`builtin`，即 OpenCV Panorama Stitcher
- 相机读取：`auto_raw`，优先读取 NV12 原始帧
- 预处理：RGA
- 关键帧筛选：关闭；手动模式下由用户按“拍摄”保存图片
- 全景展示：单层水平 partial panorama，不是完整球面全景

这些默认值都来自 `config.json`。

## 启动链

```text
开发板开机
  -> /etc/init.d/S51myui
  -> /userdata/myui/start_myui.sh
  -> 选择能出帧的摄像头，更新 /dev/video-camera0
  -> python3 /userdata/myui/backend.py
  -> HTTP 服务监听 18080
  -> Chromium kiosk 打开 index.html
```

文件职责：

- `S51myui`：开机服务入口，调用启动或停止脚本。
- `start_myui.sh`：检查相机别名、启动 Python 后端、等待 `/api/status` 成功，然后启动 Chromium kiosk。
- `backend.py`：HTTP 服务入口；负责静态文件、JSON API 和相机预览流，不负责拼接算法本身。
- `app/config.py`：读取 `config.json`，把配置转换成后端可使用的常量。

## 静态图片拼接链

```text
index.html
  -> stitch.html?mode=image
  -> 用户选择 stitch_input 中至少两张图片
  -> stitch.html 的 runStitch()
  -> POST /api/stitch/image
  -> stitch_routes.handle_post()
  -> stitch_service.run_image_stitch()
  -> OpenCVStitchEngine.stitch()
  -> 写入 stitch_output/stitched_*.jpg
  -> 返回 result_url
  -> stitch.html 的 showPanorama()
  -> 本地 pannellum.js 显示全景图
```

更具体地说：

1. `stitch.html` 的 `runStitch()` 将选中的文件名发给 `/api/stitch/image`。
2. `app/routes/stitch_routes.py` 的 `handle_post()` 调用 `app/services/stitch_service.py` 的 `run_image_stitch()`。
3. `run_image_stitch()` 调用 `storage_service.resolve_stitch_input_files()`，只接受 `stitch_input` 目录内允许的图片；再调用当前拼接引擎。
4. 目前配置为 `builtin`，所以 `get_stitch_engine()` 创建 `app/stitch_engine/opencv_engine.py` 的 `OpenCVStitchEngine`。
5. `OpenCVStitchEngine.stitch()` 先调用 OpenCV Panorama Stitcher。仅两张图时，若该 Stitcher 失败，会调用 `common.stitch_two_images_with_orb()` 做 ORB 特征匹配、单应变换和融合兜底。
6. 结果写入 `stitch_output` 后，后端返回 `result_url`；前端将其交给 Pannellum。

## 相机采集与拼接链

```text
stitch.html?mode=camera
  -> startCam()
  -> POST /api/camera/start
  -> camera_routes.handle_post()
  -> camera_service.start_camera_session()
       -> 采集线程：读取 NV12 原始帧
       -> 预览线程：RGA 转 BGR、缩放、旋转、编码 JPEG
  -> 浏览器显示 /api/camera/stream

用户点“拍摄”
  -> capture_camera_snapshot()
  -> RGA 处理当前帧
  -> 写入 stitch_input/camera_*.jpg

用户点“停止”
  -> stop_camera_session()
  -> 至少两张已拍图片时，调用 run_image_stitch()
  -> 得到 result_url
  -> showPanorama()
```

关键文件与调用：

- `stitch.html:startCam()`：请求手动相机模式，要求 `auto_raw` 和 RGA。
- `app/routes/camera_routes.py:handle_post()`：把 start/capture/stop 请求转给相机服务。
- `app/services/camera_service.py:start_camera_session()`：创建采集线程和预览编码线程。
- `camera_service._open_camera_capture()`：依次尝试可用相机节点及 GStreamer/V4L2 原始采集实现。
- `camera_service._camera_capture_loop()`：循环读帧，保存最新 NV12 `FramePacket`。
- `camera_service._camera_preview_encode_loop()`：调用预处理引擎，把最新帧变成页面能显示的 JPEG。
- `app/services/preprocess_service.py:get_preprocess_engine()`：当前返回 `RgaPreprocessEngine`。
- `app/preprocess/rga_engine.py`：通过 ctypes 调用 `native/rga/libmyui_rga.so`，完成 NV12 到 BGR 的 RGA 转换和预览缩放；90° 旋转在当前稳定路径中仍可能由 CPU 补做。
- `camera_service.capture_camera_snapshot()`：把当前帧保存成拼接输入图。
- `camera_service.stop_camera_session()`：停止线程；图片达到两张后复用 `stitch_service.run_image_stitch()`，因此相机和静态图片使用同一套拼接流程。

## 全景展示链

```text
runStitch() / stopCam()
  -> result_url
  -> showPanorama(result_url)
  -> GET /api/config/public
  -> system_routes.get_public_config()
  -> window.pannellum.viewer(...)
```

- `app/routes/system_routes.py:get_public_config()` 将 `config.json` 中的 `stitch.viewer` 下发给页面。
- `stitch.html:getSafePanoramaUrl()` 只允许加载本站 `/stitch_output/` 下的结果图。
- `stitch.html:showPanorama()` 调用本地 `vendor/pannellum/pannellum.js`。
- Pannellum 参数为 `type=equirectangular`、`haov=360`、`vaov=60`；它只提供横向一圈查看和有限的上下查看。

## 需要知道的行为

- 停止相机时，如果只拍了 0 或 1 张图片，相机会正常停止，但后端会返回“至少需要两张图片才能拼接”。这是防止空拼接的正常保护，不是相机错误。
- 相机预览与保存图片都经过 RGA；拼接本身目前主要由 OpenCV 在 CPU 上完成。
- 拼接结果必须是水平环拍长图。`vaov=60` 只是当前初始估计，待有镜头参数或实测数据后再调整。
