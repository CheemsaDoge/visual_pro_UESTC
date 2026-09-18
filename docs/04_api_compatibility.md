# 04 API 兼容性

## 当前真实路由清单

以下清单来自 `backend.py` 和 `app/routes/*.py` 的实际分发逻辑。

### GET

| API | 处理位置 | 说明 |
| --- | --- | --- |
| `/` | `backend.py:do_GET()` | 重写为 `/index.html` |
| `/api/config/public` | `system_routes.get_public_config()` | 返回 `ui`、`accel`（requested + 三个引擎实时 status）、`stitch`（engine/dirs/viewer/camera） |
| `/api/status` | `system_routes.handle_get()` | 返回 `hostname`、`kernel`、`uptime`、`ip`、`ip_list`、`wifi`、`backend` |
| `/api/wifi/list` | `wifi_routes.handle_get()` | `{"ok": true, "services": [...]}` |
| `/api/stitch/status` | `stitch_service.get_stitch_backend_status()` | 含 `engine`、`engine_status`、`actual_engine`、`stitch_mode`、`geometry`、`numpy`、相机参数镜像 |
| `/api/stitch/input-list` | `storage_service.list_stitch_input_images()` | 正序列出 `stitch_input/` 内允许扩展名的图片 |
| `/api/stitch/output-list` | `storage_service.list_stitch_output_images()` | 倒序列出 `stitch_output/` |
| `/api/camera/status` | `camera_service.get_camera_session_status()` | 会话 + 帧元数据 + preview/save 预处理结果 |
| `/api/camera/frame.jpg` | `backend.py:send_camera_frame_jpeg()` | 支持 `session_id`、`after`；响应带 `X-Frame-Seq` |
| `/api/camera/stream` | `backend.py:send_camera_stream()` | `multipart/x-mixed-replace; boundary=frame` MJPEG |
| `/stitch_input/<name>` | `backend.py:send_file_from_prefix()` | 前缀来自 `stitch.input_url_prefix` |
| `/stitch_output/<name>` | `backend.py:send_file_from_prefix()` | 前缀来自 `stitch.output_url_prefix` |

### POST

| API | 处理位置 | 说明 |
| --- | --- | --- |
| `/api/start-systemui` | `system_routes.handle_post()` | `subprocess.Popen(["/bin/sh", config.SWITCH_SCRIPT])` |
| `/api/wifi/scan` | `wifi_routes.scan_wifi()` | 先 `connmanctl enable wifi` 再 `scan wifi` |
| `/api/wifi/connect` | `wifi_routes.connect_wifi()` | 通过 `pty` 驱动 `connmanctl` 交互输入密码 |
| `/api/wifi/disconnect` | `wifi_routes.disconnect_wifi()` | 先关 autoconnect 再 disconnect |
| `/api/camera/start` | `camera_service.start_camera_session()` | payload: `mode`、`capture_backend`、`require_rga` |
| `/api/camera/capture` | `camera_service.capture_camera_snapshot()` | 仅 `mode=manual` 可用 |
| `/api/camera/stop` | `camera_service.stop_camera_session()` | payload: `auto_crop`；≥2 张时自动拼接 |
| `/api/stitch/image` | `stitch_service.run_image_stitch()` | payload: `images`(base64) 或 `server_files`(文件名) + `auto_crop` |
| `/api/stitch/output-clear` | `storage_service.clear_stitch_output_images()` | 只删允许扩展名的文件 |

未匹配任何 POST 路由时，`backend.py` 直接返回 404 空响应。

## 状态码映射

状态码不是统一的，由各 route 按 `msg` 内容判断。真实规则如下。

`camera_routes.handle_post()`：

| 条件 | 状态码 |
| --- | --- |
| `ok=true` | 200 |
| `msg` 含 `mode must` | 400 |
| `msg` 含 `already running` | 409 |
| `msg` 含 `manual mode` | 400 |
| `msg` 含 `not running` | 409 |
| `msg` 含 `not started` | 409 |
| `msg` 含 `need at least two captured images` | 400 |
| 其余失败 | 500 |

`stitch_routes.handle_post()`（`/api/stitch/image`）：

| 条件 | 状态码 |
| --- | --- |
| `ok=true` | 200 |
| `msg` 为 `need at least two images` 或 `invalid image payload` | 400 |
| `msg` 含 `image ` | 400 |
| `msg` 含 `selected server image` | 400 |
| 其余失败 | 500 |

`wifi_routes.handle_post()`：`service` 为空返回 400，失败返回 500，`/api/wifi/scan` 恒定 200。

## 行为要点

- 自动拍摄不是无条件保存每个间隔帧，而是：
  1. `PreprocessEngine.process_for_save()`；
  2. `KeyframeSelector.decision()`；
  3. `keep=true` 才写入 `stitch_input/`，否则 `dropped_count += 1`。
- `config.json` 当前默认 `accel.selector=off`，`OffSelector.decision()` 恒返回 `keep=true`，因此默认行为等价于“到间隔就保存”。
- 相机预览和保存统一走预处理引擎，旋转/缩放/JPEG 编码集中在 `app/preprocess/`。
- `/api/camera/start` 带 `require_rga=true` 时，若 `accel.preprocess != "rga"` 会直接失败并返回 `require_rga needs accel.preprocess=rga`；运行中若某帧未达 `rga_active`，`_enforce_required_rga()` 会把错误写进会话 `error` 字段。
- `/api/camera/stop` 在拍摄不足 2 张时返回 `ok=false` + `need at least two captured images before stitching`，这是防空拼接的正常保护，不是相机故障。
- Windows 上 `wifi_routes` 因为没有 `pty` 会降级：`get_wifi_status()` 返回 `Windows local mode (board Wi-Fi unavailable)`，scan/connect/disconnect 返回 `Wi-Fi management is only available on the Linux development board`。

## 前端调用现状

前端页面 `index.html`、`stitch.html`、`wifi.html` 仍是无框架 vanilla JS，实际调用：

- `index.html`：`/api/status`、`/api/stitch/status`、`/api/stitch/input-list`、`/api/stitch/output-list`、`/api/start-systemui`。
- `stitch.html`：`/api/stitch/input-list`、`/api/stitch/image`、`/api/camera/start`（`mode=manual`、`capture_backend=auto_raw`、`require_rga=true`）、`/api/camera/capture`、`/api/camera/stop`（`auto_crop=true`）、`/api/camera/stream`，MJPEG 失败时回退到 `/api/camera/frame.jpg` 轮询，另外用 `/api/config/public` 取 Pannellum 参数。
- `wifi.html`：`/api/status`、`/api/wifi/scan`、`/api/wifi/list`、`/api/wifi/connect`、`/api/wifi/disconnect`。

`/api/stitch/output-clear` 目前后端已实现，但三个页面都没有调用它。
