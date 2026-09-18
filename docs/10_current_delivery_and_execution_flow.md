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

以下值取自仓库内 `config.json`：

- 服务地址：`http://127.0.0.1:18080`（`system.port`）
- 拼接引擎：`sequential`，即顺序两两 ORB 拼接，整条序列失败时自动回退到 `builtin`（OpenCV Panorama Stitcher）
- 相机读取：`auto_raw`，优先读取 NV12 原始帧
- 相机节点：`/dev/video-camera0`（动态别名），分辨率 1920x1080、30fps、旋转 `ccw90`
- 预处理：`rga`
- 几何引擎：`opencl`（只有 `warpPerspective` 走 GPU，`remap` 仍是 CPU）
- 关键帧筛选：`off`；手动模式下由用户按“拍摄”保存图片
- 预览：`preview_fps=30`、`preview_max_dim=960`、`preview_jpeg_quality=70`
- 全景展示：单层水平 partial panorama（`haov=360`、`vaov=60`），不是完整球面全景

注意：`app/config.py:DEFAULT_CONFIG` 与 `config.json` 不完全一致（内置默认是 `engine=builtin`、`geometry=cpu`），只在配置文件缺字段时才生效；字段值非法时还有第三层 `normalize_choice`/`safe_int` 兜底。判断实际行为时以 `config.json` 为准，或直接读 `/api/config/public`。

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

- `S51myui`：开机服务入口，`MYUI_BASE` 默认 `/userdata/myui`，通过 `sh` 调用启动或停止脚本（不要求脚本保留可执行位）。
- `start_myui.sh`：先 `bootstrap_camera_alias()` 用 `v4l2-ctl` 单帧抓取逐个探测候选节点并改写 `/dev/video-camera0`，再启动 Python 后端，轮询最多 40 次等 `/api/status` 成功，然后按帧缓冲宽度算出 `--force-device-scale-factor`（目标逻辑宽度 480，取值范围 1~3）并拉起 Chromium kiosk；`MYUI_DISABLE_KIOSK=1` 时只起后端。
- `backend.py`：HTTP 服务入口；负责静态文件、JSON API 和相机预览流，不负责拼接算法本身。
- `app/config.py`：读取 `config.json`，归一化并导出后端常量；模块加载时会创建 `_stitch_work`、`stitch_output`、`stitch_input` 目录并 `os.chdir(BASE_DIR)`。

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

1. `stitch.html` 的 `runStitch()` 将选中的文件名作为 `server_files` 发给 `/api/stitch/image`。
2. `app/routes/stitch_routes.py` 的 `handle_post()` 调用 `app/services/stitch_service.py` 的 `run_image_stitch()`。
3. `run_image_stitch()` 先查 `get_stitch_backend_status()`；若 payload 带 `images`（base64）则走 `storage_service.decode_image_payload()` 落盘到 `_stitch_work/` 并在结束后删除，若带 `server_files` 则走 `resolve_stitch_input_files()`，只接受 `stitch_input` 目录内允许扩展名的图片。
4. 目前配置为 `sequential`，所以 `get_stitch_engine()` 创建 `app/stitch_engine/sequential_engine.py` 的 `SequentialPanoEngine`，并把 `OpenCVStitchEngine` 作为 fallback 一起装配。
5. `SequentialPanoEngine.stitch()` 先把输入按 1920 宽度上限缩放并做 `bilateralFilter`，再逐对调用 `common.stitch_two_images_with_orb()`（ORB 特征 → `findHomography` → `GeometryEngine.warp_perspective()` → 多带或均值融合）。任一步失败就整体回退到 `OpenCVStitchEngine`：OpenCV Panorama Stitcher 正序、反序各试一次，恰好两张图时再退到 ORB 路径。
6. 成功后统一做 USM 锐化 + `fastNlMeansDenoisingColored` 后处理，写入 `stitch_output/stitched_<时间戳>_<8位hex>.jpg`，后端返回 `result_url`、`engine`、`actual_engine`；前端将 `result_url` 交给 Pannellum。

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

- `stitch.html:startCam()`：POST `{mode: 'manual', capture_backend: 'auto_raw', require_rga: true}`。
- `app/routes/camera_routes.py:handle_post()`：把 start/capture/stop 请求转给相机服务，并按 `msg` 内容决定 400/409/500。
- `app/services/camera_service.py:start_camera_session()`：校验 `require_rga` 与 `accel.preprocess`，写入 `CAMERA_RUNTIME`，创建采集线程和预览编码线程，最多等 0.35 秒看首帧是否就绪。
- `camera_service._open_camera_capture()`：`auto_raw` 下先对每个候选节点试 `OpenCvGstRawNv12Capture`（无 `videoconvert` 的 raw NV12 appsink），失败再试 GI 版 `GstRawNv12Capture`，再试 `V4L2CtlNv12Capture(raw_packet=True)`，最后才退到 legacy OpenCV/GStreamer BGR 与 `v4l2-ctl` BGR。
- `camera_service._camera_capture_loop()`：循环读帧，保存最新 `FramePacket` 与 stride/buffer 元数据；`mode=auto` 时按 `auto_interval_sec` 触发预处理 + selector 判断。
- `camera_service._camera_preview_encode_loop()`：按 `preview_fps` 节流，调用 `process_for_preview()` 生成 `preview_jpeg` 写入运行时缓存。
- `camera_service._enforce_required_rga()`：记录 preview/save 的预处理指标；`require_rga=true` 且 `mode_tag != rga_active` 时抛错。
- `app/services/preprocess_service.py:get_preprocess_engine()`：当前返回 `RgaPreprocessEngine`（模块级单例）。
- `app/preprocess/rga_engine.py`：通过 ctypes 调用 `native/rga/libmyui_rga.so`，完成 NV12 到 BGR 的 RGA 转换；预览路径会让 RGA 顺带缩放（`convert_resize_only_cpu_rotate`），1920x1080 的 90° 旋转由 CPU 补做（`post_rotate_cpu=True`）。
- `camera_service.capture_camera_snapshot()`：复制当前帧 → `process_for_save()` → 写入 `stitch_input/camera_<session>_<序号>.jpg`。
- `camera_service.stop_camera_session()`：置停止事件并 join 两个线程；图片达到两张后复用 `stitch_service.run_image_stitch()`，因此相机和静态图片使用同一套拼接流程。

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

- 停止相机时，如果只拍了 0 或 1 张图片，相机会正常停止，但后端会返回“至少需要两张图片才能拼接”（`need at least two captured images before stitching`，HTTP 400）。这是防止空拼接的正常保护，不是相机错误。
- 相机预览与保存图片都经过 RGA；拼接的特征匹配、融合、后处理仍主要由 OpenCV 在 CPU 上完成，只有 ORB 路径里的 `warpPerspective` 可能走 direct OpenCL。
- `stitch.html` 优先用 `/api/camera/stream` 的 MJPEG；`<img>` 触发 `onerror` 时才降级成 `/api/camera/frame.jpg` 每 100ms 轮询。所以画面卡顿要先确认走的是哪条路径。
- 同一时间只允许一个相机会话，`CAMERA_RUNTIME` 是模块级单例；重复 `start` 返回 `camera session already running`（HTTP 409）。
- 拼接结果必须是水平环拍长图。`vaov=60` 只是当前初始估计，待有镜头参数或实测数据后再调整。
- 改 `config.json` 后必须重启后端，四个引擎工厂都只初始化一次。
