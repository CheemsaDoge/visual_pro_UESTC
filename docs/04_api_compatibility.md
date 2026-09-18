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
| `/api/stitch/logs` | `stitch_diagnostics.list_reports()` / `get_report()` | 不带 `id` 返回 `{"ok":true,"reports":[...]}`；带 `id` 返回 `{"ok":true,"report":{...}}`，找不到返回 404 `stitch log not found` |
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
| `/api/camera/stop` | `camera_service.stop_camera_session()` | payload: `auto_crop`；≥2 张时自动拼接（内部以 `source="camera"` 调用） |
| `/api/stitch/image` | `stitch_service.run_image_stitch()` | payload: `images`(base64) 或 `server_files`(文件名) + `auto_crop` + 可选 `source` |
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

## 拼接诊断日志（`/api/stitch/logs`）

`/api/stitch/image` 与相机 stop 触发的拼接都会生成一份诊断报告，成功和失败的响应里都会带上：

- `log_id`：报告 ID，等于拼接的 `request_id`（格式 `%Y%m%d_%H%M%S_<8位hex>`）
- `stitch_log`：报告全文（与 `/api/stitch/logs?id=<log_id>` 返回的 `report` 一致）

存储特性由 `app/services/stitch_diagnostics.py` 决定：

- 进程内内存存储，`deque(maxlen=30)`，**后端重启即清空**，不落盘。
- `list_reports(limit)` 最新的排在最前，`limit` 会被夹到 `1..30`。
- 读写都加 `threading.Lock`，对外返回 `deepcopy`，调用方改不到内部状态。

报告结构：

```text
id                 请求 ID
started_at/ended_at 本地时间 ISO 字符串（%Y-%m-%dT%H:%M:%S）
source             "image"（默认）或 "camera"
status             running / success / failed
message            引擎返回的 msg
input.count        输入张数
input.files[]      index / name / bytes / width / height / channels（读图失败时带 inspect_error）
config             requested_engine / auto_crop / geometry / preprocess / backend 四个状态快照
stages[]           service 层阶段，当前只有 engine_dispatch，含 name / parameters / elapsed_ms
engine_detail      引擎层明细，见下
output             name / bytes / width / height（仅成功时填充）
total_elapsed_ms   墙钟总耗时
resources          见下
```

`engine_detail` 由 `StitchEngine._begin_run_detail()` / `_record_stage()` 累积，各引擎记录的阶段名：

| 引擎 | 阶段 |
| --- | --- |
| `OpenCVStitchEngine` | `load_and_preprocess`、`opencv_panorama_attempt`（每次尝试一条，带 `attempt`/`order`/`status`）、`orb_fallback`、`postprocess_and_save` |
| `SequentialPanoEngine` | `load_and_preprocess`、`pairwise_orb`（每对一条）、`pairwise_sequence_total`、`save_result`、`opencv_fallback`（嵌套 fallback 引擎的 detail） |
| `ScansStitchEngine` | `parallel_load_preprocess_quality_filter`（含 `workers`/`valid_images`/`rejected_images`）、`opencv_scans_stitch`、`postprocess_and_save` |
| `script` | 不产生 `engine_detail.stages`，只有 `engine="script"` 与 `parameters.script_path`/`timeout_sec` |

走 ORB 的阶段（`orb_fallback`、`pairwise_orb`）通过 `stitch_two_images_with_orb(telemetry=...)` 额外带回：

```text
algorithm            "ORB + BFMatcher(Hamming) + Lowe ratio + RANSAC homography"
parameters           orb_features=2000 / match_ratio=0.9 / min_good_matches=10 / ransac_reproj_threshold=5.0
feature_points       left / right 两图的关键点数
matches              raw_knn_pairs / good_ratio_matches
homography.inliers   RANSAC 内点数
canvas               成功时的输出画布宽高
elapsed_ms           该次 ORB 配准耗时
```

`resources` 是前后两次 `metrics_service.snapshot()` 的对比：

```text
system_cpu_percent_approx                    /proc/stat 区间均值，非 Linux 为 null
backend_process_cpu_capacity_percent_approx  process_time 增量 / 墙钟，可超过 100%（多线程）
backend_process_cpu_time_ms                  本次拼接消耗的进程 CPU 时间
memory_before / memory_after                 /proc/meminfo 摘要
backend_memory_before / backend_memory_after /proc/<pid>/status 的 VmRSS/VmHWM/VmSize/Threads
gpu_before / gpu_after                       devfreq sysfs 采样，见下
thermal_after                                thermal zone 温度
note                                         说明 GPU 为 best-effort 数据
```

GPU 数据由 `metrics_service.read_gpu()` 采集，是 best-effort 的：扫描 `/sys/class/devfreq/*`，按目录名或 `device/uevent` 含 `gpu`/`mali` 过滤，逐个读 `cur_freq`、`max_freq`、`min_freq`、`load`、`busy_time`、`total_time`，读不到就不填。内核没暴露对应计数器时返回 `{"devices": [], "available": false}`，不会伪造占用率。

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

前端页面 `index.html`、`stitch.html`、`wifi.html`、`stitch_log.html` 仍是无框架 vanilla JS，实际调用：

- `index.html`：`/api/status`、`/api/stitch/status`、`/api/stitch/input-list`、`/api/stitch/output-list`、`/api/start-systemui`；导航卡片新增第 5 张「拼接日志」，跳转 `stitch_log.html`。
- `stitch.html`：`/api/stitch/input-list`、`/api/stitch/image`、`/api/camera/start`（`mode=manual`、`capture_backend=auto_raw`、`require_rga=true`）、`/api/camera/capture`、`/api/camera/stop`（`auto_crop=true`）、`/api/camera/stream`，MJPEG 失败时回退到 `/api/camera/frame.jpg` 轮询，另外用 `/api/config/public` 取 Pannellum 参数。拼接成功后把 `result_url` 与 `log_id` 存进 `state`，结果操作栏提供「展示全景图 / 展示拼接图像 / 本次日志 / 返回 / 重新拍摄」五个按钮。
- `stitch_log.html`：只调用 `/api/stitch/logs`；URL 带 `?id=` 时请求单条并默认展开，否则列出最近 30 条且默认展开第一条。
- `wifi.html`：`/api/status`、`/api/wifi/scan`、`/api/wifi/list`、`/api/wifi/connect`、`/api/wifi/disconnect`。

`/api/stitch/output-clear` 目前后端已实现，但四个页面都没有调用它。
