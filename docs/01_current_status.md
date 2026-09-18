# 01 当前状态

最近更新：2026-09-18（合并 `feature-parameter` 后按代码重新核对）

## 代码现状速查

| 项 | 真实值 |
| --- | --- |
| `backend.py` | 227 行，仅 HTTP transport / 静态文件 / MJPEG / 单帧 JPEG |
| 后端模块 | `app/` 下 45 个 Python 文件，合计 6081 行 |
| 最大模块 | `app/services/camera_service.py` 1114 行 |
| 前端页面 | `index.html` / `stitch.html` / `wifi.html` / `stitch_log.html` |
| 拼接引擎 | `builtin` / `sequential` / `scans` / `script` 四种 |
| `config.json` 生效引擎 | `stitch.engine=sequential`，`accel.preprocess=rga`，`accel.geometry=opencl`，`accel.selector=off` |
| 测试用例 | 12 条（unit 11 + integration 1）+ 4 个板端 smoke 脚本 + 1 个 benchmark |

## 已完成

- 2026-09-18 拼接性能更新：针对 RK3588 的两张 2560×1920 输入，先前诊断为 42.0 秒，主因是 CPU `fastNlMeansDenoisingColored`；现已改为超过 `postprocess_denoise_max_pixels` 时跳过该操作，并把线性融合与 USM 锐化优先交给 Mali-G610 的 direct OpenCL kernel。实测为 1.43 秒，诊断显示 `blend=linear_opencl`、`sharpen=opencl`。本次继续将 `preprocess_max_pixels=1500000` 以上的输入跳过 CPU 双边滤波，且将 ORB 匹配限制在 `orb_match_max_width=960` 的副本上；匹配坐标会还原到 1920 宽的工作图，因此不会降低输出几何分辨率。ORB/BFMatcher/RANSAC 仍为 CPU，因为板端 OpenCV 4.5.4 的 `haveOpenCL=False`，没有可用 GPU 特征匹配后端。

- `backend.py` 已变薄，只保留 HTTP transport、静态文件、MJPEG/单帧 JPEG 响应，路由通过 `GET_ROUTES`/`POST_ROUTES` 元组分发。
- 模块目录已建立：
  - `app/config.py`、`app/schemas.py`
  - `app/routes/`（camera / stitch / system / wifi）
  - `app/services/`（camera / stitch / storage / geometry / preprocess / keyframe / metrics / stitch_diagnostics）
  - `app/capture/`（gst_capture / gst_raw_nv12_capture / v4l2_capture）
  - `app/preprocess/`、`app/geometry/`、`app/selector/`、`app/stitch_engine/`、`app/utils/`
- 基础数据对象 `FramePacket`、`ProcessedFrame` 位于 `app/schemas.py`；`FramePacket` 含 `stride_w`、`stride_h`、`timestamp_ns`、`buffer_size`、`stride_inferred`，并在 `__post_init__` 中自动补齐。
- 已接入引擎抽象：
  - `CpuPreprocessEngine`（`mode_tag=cpu_base`）
  - `RgaPreprocessEngine`（`rga_ready` / `rga_active` / `rga_fallback_cpu`）
  - `CpuGeometryEngine`（`geometry_cpu`）
  - `OpenCLGeometryEngine`（runtime 可用时 `geometry_opencl_direct`，否则 `opencl_fallback_cpu`；`warpPerspective` 走 direct OpenCL，`remap` 明确 CPU fallback）
  - `OffSelector`（`selector_off`）
  - `CpuSelector`（`selector_cpu_basic`）
  - `RknnSelector`（`rknn_fallback_cpu_basic`，`available=false`）
  - `OpenCVStitchEngine`（`opencv_panorama_enhanced`，含正反序两次尝试与两图 ORB fallback）
  - `SequentialPanoEngine`（`sequential_pairwise_orb`，失败时回退 `OpenCVStitchEngine`）
  - `ScansStitchEngine`（`opencv_scans_enhanced`，含质量过滤与 `registration_resol=0.6`）
- 相机预览/保存统一走 `PreprocessEngine`；采集线程与预览编码线程分离，预览按 `preview_fps` 节流。
- 自动拍摄是“先 selector 判断是否保留，再保存”，丢弃帧计入 `dropped_count`。
- `config.json` 已有 `accel` 和 `selector.cpu_basic` 配置，另有 `stitch.viewer` 下发给 Pannellum。
- 已有 `tests/unit/`、`tests/integration/`、`tests/smoke/`、`tests/benchmark/run_benchmark.py`。
- 离线 Pannellum 2.5.7 位于 `vendor/pannellum/`，板端展示全景不需要联网。
- 拼接诊断日志（2026-09-18 合并 `feature-parameter`）：
  - 新增 `app/services/stitch_diagnostics.py`（143 行）与 `stitch_log.html`（58 行）。
  - `run_image_stitch()` 全程被 `StitchDiagnostics` 包裹，成功和失败都返回 `log_id` + `stitch_log`。
  - `StitchEngine` 基类新增 `_begin_run_detail()` / `_record_stage()` / `get_last_run_detail()`，三个 OpenCV 系引擎都记录了分阶段耗时与参数。
  - `stitch_two_images_with_orb()` 增加 `telemetry` 出参，回传 ORB 关键点数、good match 数、RANSAC 内点数、画布尺寸与耗时。
  - `metrics_service` 增加 `read_gpu()`，从 `/sys/class/devfreq/*` best-effort 采集 GPU 频率与负载，并纳入 `snapshot()`。
  - 报告存在进程内 `deque(maxlen=30)`，后端重启即清空，不落盘。
  - 前端：`index.html` 新增第 5 张导航卡片，`stitch.html` 结果区新增「展示全景图 / 展示拼接图像 / 本次日志」三个按钮，缩略图补了 `role`/`tabIndex`/键盘选择支持。
- `native/rga/` 已新增最小 wrapper 源码、头文件和 Makefile：
  - `native/rga/myui_rga.cpp`
  - `native/rga/myui_rga.h`
  - `native/rga/Makefile`
  - `native/rga/README.md`
- `RgaPreprocessEngine` 已从占位 fallback 改为 `ctypes` 加载 `libmyui_rga.so`；wrapper 可用且输入为 `FramePacket(pixel_format="NV12")` 时走真实 RGA，失败时自动 `rga_fallback_cpu`。
- `RgaPreprocessEngine` 当前会记录 wrapper 候选路径、`lib_version`、active/fallback 调用计数，并在 native 调用前校验 NV12 尺寸和数据长度。
- `OpenCLGeometryEngine` 已从占位实现改为 direct OpenCL 路径：通过 Python `ctypes` 直接调用 `libOpenCL.so`，在板端可真实执行 `warpPerspective` 的最小 BGR buffer kernel。
- benchmark 已增加 preprocess mode 明确输出，并增加 `--feed-format`、`--skip-stitch`、`--rga-lib` 与 `--require-rga`，便于单独验证 `rga_active/rga_fallback_cpu`，且防止把 CPU fallback 误判成 RGA。

## 当前可运行

常用命令：

```bash
python3 -m py_compile backend.py stitch_demo.py $(find app tests -name '*.py')
python3 backend.py
python3 -m unittest discover tests
python3 tests/benchmark/run_benchmark.py --preprocess cpu --selector off
```

2026-09-18 本地复核结果（Windows，Python 3.12.6，环境未装 `cv2`）：

- `python -m py_compile backend.py stitch_demo.py $(find app tests -name '*.py')`：全部通过，退出码 0（合并 `feature-parameter` 后重跑仍通过）。
- `python -m unittest discover tests`：`tests.unit.test_opencl_geometry` 4 条通过；其余 4 个模块在导入阶段报 `ModuleNotFoundError: No module named 'cv2'`。这属于环境缺 OpenCV，不是代码缺陷；需要完整跑测试时按 `requirements.txt` 安装 `numpy` 与 `opencv-python`。
- 新增的拼接诊断链路尚未跑过端到端验证（需要 `cv2` 才能真正执行一次拼接），因此 `stitch_log.html` 的实际渲染效果与 `resources` 各字段的真实取值仍待在装有 OpenCV 的环境或板端确认。
- 仓库当前没有 `reports/` 目录，benchmark 首次运行会自行创建。

2026-05-08 开发机已完成一次验证：

- `py_compile`：通过。
- `python3 -m unittest discover tests`：5 条测试通过。
- `tests/benchmark/run_benchmark.py --preprocess cpu --selector off`：可生成 JSON 报告，模式显示 `cpu_base+selector_off`。
- `tests/benchmark/run_benchmark.py --preprocess rga --selector cpu_basic`：可生成 JSON 报告，模式显示 `rga_fallback_cpu+selector_cpu_basic`。
- `tests/benchmark/run_benchmark.py --preprocess rga --selector off --skip-stitch --output-json /tmp/benchmark_rga_fallback_local.json`：PC 侧可输出 `preprocess_mode=rga_fallback_cpu`，`requested.feed_format=nv12`。
- `tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --require-rga`：在没有 wrapper 时返回退出码 `3`，用于生产验证时强制区分 `rga_active` 与 fallback。
- `MYUI_PORT=18180 python3 backend.py` 后烟测 `/api/status`、`/api/config/public`、`/api/stitch/status`、输入/输出列表和 `/`：可响应。

## 板端验证记录

2026-05-08 通过 Windows `COM3` 串口把当前模块化版本部署到 RK3588：

- 部署路径：`/userdata/myui`
- 旧版本备份：`/userdata/myui_backup_modular_20260508_165930`
- 部署日志：`/tmp/myui_deploy_20260508_165930.log`
- 板端 `python3 -m py_compile backend.py stitch_demo.py $(find app tests -name '*.py' | sort)`：通过。
- 板端 API smoke：
  - `/api/status`：200
  - `/api/config/public`：200，`preprocess_mode=cpu_base`，`selector_mode=selector_off`
  - `/api/stitch/status`：200，`engine=builtin`
- 板端 benchmark smoke：
  - 命令：`python3 tests/benchmark/run_benchmark.py --preprocess cpu --selector off --output-json /tmp/myui_benchmark_board.json`
  - 结果：`stitch_ok=True`，`preprocess_mode=cpu_base`，`selector_mode=selector_off`
- 板端相机 API smoke：
  - `/api/camera/start`：200，`camera starting`
  - 3 秒后 `/api/camera/status`：`active=True`，`last_frame_ready=True`
  - 打开源：`v4l2src device=/dev/video44 ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false`
  - `/api/camera/capture`：200，`captured`
  - `/api/camera/stop`：400，原因是只拍了 1 张，符合“至少 2 张才拼接”的预期保护。
- 启动项验证：
  - `/etc/init.d/S51myui restart` 后 `/etc/init.d/S51myui status` 返回 `myui python running`
  - restart 后 `/api/status` 返回成功
  - 进程中存在 `python3 /userdata/myui/backend.py`
  - 进程中存在 Chromium kiosk，URL 为 `http://127.0.0.1:18080/index.html`

### RGA 资源探测记录

2026-05-08 通过 Windows `COM3` 串口在 ATK-DLRK3588 上探测 RGA 资源：

- 系统：`Linux 5.10.209 ... aarch64`
- RGA 设备存在：`/dev/rga`，权限 `crw-rw---- root video 10,120`
- RGA 运行库存在：
  - `/lib/librga.so -> librga.so.2 -> librga.so.2.1.0`
  - `/usr/lib/librga.so -> librga.so.2 -> librga.so.2.1.0`
  - `/lib64`、`/usr/lib64` 下也有对应 symlink
- `ctypes.CDLL('librga.so')` 可加载，并能看到 `c_RkRgaInit`、`c_RkRgaBlit`、`improcess`
- 未找到开发头文件：`im2d.h` / `RgaApi.h` / `rga.h`
- 未找到本地编译器：`cc` / `gcc` / `g++`

结论：当前板端具备 RGA 运行时设备和库，但缺少编译 `native/rga/libmyui_rga.so` 所需开发资源。因此本轮 PC 侧已完成 wrapper 与 Python 接入代码，板端暂按资源不足路径保持 `rga_fallback_cpu`；等补齐 headers/compiler 或交叉编译出 `libmyui_rga.so` 后再验证 `rga_active`。

### 2026-05-08 RGA 增量验证记录

通过 COM3 串口把 RGA 增量文件同步到 `/userdata/myui`，逐文件 `md5sum` 与本地一致。同步内容包括：

- `native/rga/myui_rga.cpp`
- `native/rga/README.md`
- `app/preprocess/rga_engine.py`
- `app/services/metrics_service.py`
- `tests/benchmark/run_benchmark.py`
- `tests/unit/test_preprocess.py`

板端验证结果：

- `PYTHONPYCACHEPREFIX=/tmp/myui_pycache python3 -m py_compile app/preprocess/rga_engine.py app/services/metrics_service.py tests/benchmark/run_benchmark.py tests/unit/test_preprocess.py`：通过。
- `PYTHONPYCACHEPREFIX=/tmp/myui_pycache python3 -m unittest tests.unit.test_preprocess`：2 条 preprocess 单测通过，其中包括 NV12 + 缺 wrapper 自动 fallback。
- 普通 RGA smoke：
  ```bash
  PYTHONPYCACHEPREFIX=/tmp/myui_pycache python3 tests/benchmark/run_benchmark.py \
    --preprocess rga \
    --selector off \
    --feed-format nv12 \
    --frames 2 \
    --skip-stitch \
    --output-json /tmp/benchmark_rga.json
  ```
  输出：`preprocess_mode=rga_fallback_cpu`、`preprocess_actual=cpu`、`rga_wrapper_available=False`、`rga_active_calls=0`、`rga_fallback_calls=2`。
- 强制 RGA smoke：
  ```bash
  PYTHONPYCACHEPREFIX=/tmp/myui_pycache python3 tests/benchmark/run_benchmark.py \
    --preprocess rga \
    --selector off \
    --feed-format nv12 \
    --frames 2 \
    --skip-stitch \
    --require-rga \
    --output-json /tmp/benchmark_rga_require.json
  ```
  在当前缺 `libmyui_rga.so` 的情况下返回退出码 `3`，符合预期。
- `cd /userdata/myui/native/rga && make probe`：能看到 `/dev/rga` 和 `librga.so`，headers 为空，compiler 为空。
- `cd /userdata/myui/native/rga && make`：失败在 `error: C++ compiler 'g++' not found`。

当前完整 API 清单（详见 `docs/04_api_compatibility.md`）：

GET：

- `/`
- `/api/config/public`
- `/api/status`
- `/api/wifi/list`
- `/api/stitch/status`
- `/api/stitch/input-list`
- `/api/stitch/output-list`
- `/api/stitch/logs`
- `/api/camera/status`
- `/api/camera/frame.jpg`
- `/api/camera/stream`
- `/stitch_input/<name>`、`/stitch_output/<name>`（前缀可配）

POST：

- `/api/start-systemui`
- `/api/wifi/scan`、`/api/wifi/connect`、`/api/wifi/disconnect`
- `/api/camera/start`、`/api/camera/capture`、`/api/camera/stop`
- `/api/stitch/image`、`/api/stitch/output-clear`

## 当前限制

- `RgaPreprocessEngine` 通过 `ctypes` 调用 `libmyui_rga.so`，仓库内已有交叉编译出的 `native/rga/libmyui_rga.so`；板端仍缺 `im2d.h`/`RgaApi.h` 和 `g++`，所以不能在板上重新编译，只能同步已构建产物。
- 1920x1080 且旋转为 90/270 时，RGA 只完成 `NV12 -> BGR`（预览路径附带缩放），旋转由 CPU 补做，状态标记为 `rga_transform=convert_only_cpu_rotate` 或 `convert_resize_only_cpu_rotate`，`post_rotate_cpu=True`。原因是 librga 要求 BGR888 width stride 16 对齐，紧密目标 stride `1080` 不满足，`1088` 才可以。
- `legacy_bgr` 采集路径进入 Python 时已是 BGR ndarray，不能作为“真实 NV12 进入 RGA”的证据；只有 `gst_nv12_raw` / `v4l2ctl_nv12_raw`（或 `auto_raw` 命中它们）才能。
- 2026-05-12 板端已确认原生 `libOpenCL.so` 能枚举 `ARM Platform / Mali-G610 r0p0`，且 2026-05-13 已确认可以真实 `build program + launch kernel + read back`；但板端 OpenCV 4.5.4 仍 `haveOpenCL=False`。
- `OpenCLGeometryEngine` 只把 `warpPerspective` 接到 direct OpenCL；`remap()` 每次调用都累加 `remap_fallback_calls` 并转给 CPU。
- 几何层只在 `common.stitch_two_images_with_orb()` 这条路径被直接调用，即 `builtin` 的两图 fallback 与 `sequential` 的每一步；主 `cv2.Stitcher` 成功时不经过它，`ScansStitchEngine` 完全不接几何引擎。
- `SequentialPanoEngine` 依赖 ORB 特征匹配质量，任一相邻对失败就整条序列失败并回退 `OpenCVStitchEngine`。
- `RknnSelector` 只是占位，直接委托 `CpuSelector`，未接真实 RKNN 推理。
- 四个引擎工厂都是模块级单例，改 `config.json` 后必须重启后端才生效。
- 拼接诊断日志只存在进程内存（`deque(maxlen=30)`），后端重启即清空，也不写文件；需要长期留存必须自己导出 `stitch_log` 字段。
- `StitchEngine.last_run_detail` 是引擎实例属性，而引擎是单例，所以只保留最近一次运行的数据；并发拼接会互相覆盖，当前没有加锁。
- `StitchDiagnostics.image_file_details()` 与 `finish()` 会对每张输入图和输出图各做一次 `cv2.imread()` 以取尺寸，这是纯诊断开销，大图多图时会明显增加单次拼接的额外耗时。
- `resources.backend_process_cpu_capacity_percent_approx` 用 `process_time` 增量除以墙钟，多线程下可能超过 100%，不要当成单核占用率读。
- GPU 数据是 best-effort 的 devfreq/sysfs 采样，内核未暴露计数器时返回 `{"devices": [], "available": false}`，不要当成“GPU 未被使用”的证据。
- `wifi_routes` 依赖 `pty`，Windows 上自动降级为“仅 Linux 开发板可用”。

## 当前默认主线

仓库内 `config.json` 当前生效的是加速配置，不是 CPU baseline：

```json
"accel": {
  "preprocess": "rga",
  "geometry": "opencl",
  "selector": "off"
}
```

`app/config.py` 的 `DEFAULT_CONFIG` 里 `accel.geometry` 仍是 `cpu`，只有 `config.json` 缺该字段时才会用到。若要强制回到安全 baseline，显式写入：

```json
"accel": { "preprocess": "cpu", "geometry": "cpu", "selector": "off" }
```

## 当前风险

- 设备侧 GStreamer/OpenCV/V4L2 行为可能和开发机不同，相机 API 需要在 RK3588 真机上烟测。
- OpenCV Stitcher/ORB fallback 对输入纹理、重叠率敏感，当前测试只覆盖基本正例。
- benchmark 初版用于结构化记录，不代表最终性能结论。

## 2026-05-08 RGA 交叉编译资源查找结果

本轮按任务书在本机查找可用交叉编译资源，结果如下：

- 未找到 aarch64 GNU/Buildroot 交叉编译器：PATH、项目目录、`D:\dev`、`D:\ywjhn\desktop`、`C:\Users\ywjhn\Desktop`、`Downloads`、`Documents` 均未发现 `aarch64-linux-gnu-g++`、`aarch64-none-linux-gnu-g++`、`aarch64-buildroot-linux-gnu-g++` 或对应 `gcc`。
- 未找到 Rockchip librga 开发头文件：上述路径未发现 `im2d.h`、`RgaApi.h`、`rga.h`。
- 未找到可用于交叉链接的本机/sysroot `librga.so`。
- Windows WSL 当前没有可用发行版，不能借用 WSL 内交叉编译环境。

是否足够编译 `native/rga/myui_rga.cpp`：否。缺少可运行的 aarch64 C++ 编译器、`im2d.h` 及其依赖头文件、目标 ABI 的 `librga.so` 或 sysroot。

本轮已完成的代码侧准备：

- `native/rga/Makefile` 已支持 `CXX`、`SYSROOT`、`RGA_INCLUDE_DIR`、`RGA_LIB_DIR`，后续拿到 SDK 后可直接复用。
- `native/rga/README.md` 已补充交叉编译前提、命令和常见失败原因。

当时真实状态保持不变：RGA fallback 路径已验证正确，但 `rga_active` 还未打通。2026-05-09 的后续验证见下一节。

## 2026-05-09 RGA wrapper 已部署并进入 rga_active

用户将官方 `01、linux_sdk.zip` 内容放到上级目录 `..\01linux_sdk` 后，本轮继续推进：

- SDK 包：`..\01linux_sdk\atk-rk3588_linux_release_v1.2_20250104.tgz`。
- manifest 确认 `linux/linux-rga` 项目路径为 `external/linux-rga`。
- `linux-rga` repo 中找到所需 headers：
  - `im2d_api/im2d.h`
  - `include/RgaApi.h`
  - `include/rga.h`
  - `include/RgaUtils.h`
- SDK 中找到 Rockchip prebuilt aarch64 toolchain repo：`gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu`，包含 `bin/aarch64-none-linux-gnu-g++`，但该工具链是 Linux x86_64 ELF，Windows 不能直接运行。
- 本轮使用 Windows clang 16 + SDK sysroot headers + RGA headers 交叉生成 `native/rga/libmyui_rga.so`。
- 产物确认是 AArch64 ELF shared object，已同步到 `/userdata/myui/native/rga/libmyui_rga.so`，md5：`353e928594515b524c8a21dc569f3496`。
- 同步了 `app/preprocess/rga_engine.py`，在加载 wrapper 前先以 `RTLD_GLOBAL` 加载板端真实 `librga.so`。
- 板端 `make probe` 可见 `/dev/rga` 和 `/lib`、`/usr/lib` 下的 `librga.so`。
- 板端 `make test-load` 通过：`myui_rga_available= 1`。
- 固定 320x240 NV12 样例通过：`ret=0`、`last_error=ok`。

benchmark 验证结果：

```text
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --frames 2 --skip-stitch --output-json /tmp/benchmark_rga.json
preprocess_mode rga_active
preprocess_actual rga
preprocess_reason ok: save 320x240->240x320
rga_wrapper_available True
rga_active_calls 2
rga_fallback_calls 0

python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --frames 2 --skip-stitch --require-rga --output-json /tmp/benchmark_rga_require.json
require_rc=0
preprocess_mode rga_active
preprocess_actual rga
preprocess_reason ok: save 320x240->240x320
rga_wrapper_available True
rga_active_calls 2
rga_fallback_calls 0
```

当前真实状态可更新为：`libmyui_rga.so` 已交叉产出并在板端加载，固定 NV12 和 benchmark 已进入 `rga_active`。实时相机链路尚未前移到原始 NV12 buffer。

## 2026-05-09 真实相机 raw NV12 接入实现状态

本轮按“真实 `/dev/video44` NV12 -> `FramePacket(pixel_format="NV12")` -> `RgaPreprocessEngine`”推进。代码侧已新增 raw capture backend；本段记录实现状态，不等同于板端已跑通证据。

当前相机采集路径区分如下：

- `legacy_bgr`：默认兼容路径，`/dev/video44 -> NV12 -> videoconvert -> BGR -> appsink`，进入 Python 时已经是 BGR ndarray，不能证明真实 NV12 进入 RGA。
- `v4l2ctl_nv12_raw`：复用现有 `v4l2-ctl --stream-to` 单帧抓取能力，读取 raw bytes 后直接构造 `FramePacket(pixel_format="NV12")`，保留 `buffer_size/stride_w/stride_h/stride_inferred/source`。这是保存路径优先验证真实 NV12 + RGA 的保守路线。
- `gst_nv12_raw`：新增 GStreamer raw appsink 路线，不含 `videoconvert`，pipeline 为 `v4l2src device=/dev/video44 ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 ! queue leaky=downstream max-size-buffers=1 ! appsink name=sink drop=true max-buffers=1 sync=false`。

`FramePacket` 已扩展 `stride_w`、`stride_h`、`timestamp_ns`、`buffer_size`、`stride_inferred`。旧 BGR 路径默认 `stride_w=width`、`stride_h=height`，保持兼容。

Camera API 已增加 `capture_backend` 开关，可在 `/api/camera/start` payload 中传：

```json
{
  "mode": "manual",
  "capture_backend": "v4l2ctl_nv12_raw",
  "require_rga": true
}
```

`/api/camera/status` 现在可查看 `capture_backend`、`last_frame_format`、`last_frame_buffer_size`、`last_frame_stride_w`、`last_frame_stride_h`、`last_frame_stride_inferred`、`last_preview_preprocess`、`last_save_preprocess`。

本地开发机已完成 `py_compile` 和现有 preprocess/integration 单测，3 条测试通过。尚未完成板端验收：本轮还没有在 RK3588 上实际运行 raw NV12 smoke，因此不能写成“真实相机保存/预览已实际进入 `rga_active`”。板端验收必须看到 `last_frame_format=NV12`、`save.preprocess_mode=rga_active`，预览成功时还应看到 `preview.preprocess_mode=rga_active`。

## 2026-05-09 板端 raw NV12 -> RGA 验证结果

本轮已重新同步后端、smoke、docs、Makefile，以及重写后的 `index.html`、`stitch.html`、`wifi.html` 到 `/userdata/myui/`，逐文件 md5 校验一致。

板端验证命令使用临时配置 `/tmp/myui_config_rga.json`，只在验证进程内设置 `accel.preprocess=rga` 和 `capture_backend=v4l2ctl_nv12_raw`，未改写持久 `config.json`。

结果：

```text
make py-check
py_check_rc=0

python3 tests/smoke/test_v4l2_nv12_rga_smoke.py --frames 1 --require-rga
pixel_format=NV12
width=1920
height=1080
stride_w=1920
stride_h=1080
buffer_size=3110400
source=v4l2-ctl:/dev/video44
stride_inferred=False
preprocess_mode=rga_active
rga_wrapper_available=True
rga_active_calls=1
rga_fallback_calls=0
last_error=ok
smoke_v4l2_rc=0
```

Camera API preview/save 验证：

```text
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga
status_before_capture.last_frame_format=NV12
status_before_capture.last_frame_width=1920
status_before_capture.last_frame_height=1080
status_before_capture.last_frame_buffer_size=3110400
status_before_capture.last_frame_stride_w=1920
status_before_capture.last_frame_stride_h=1080
status_before_capture.preview.preprocess_mode=rga_active
status_before_capture.preview.rga_fallback_calls=0
capture ok=True
status_after_capture.save.preprocess_mode=rga_active
status_after_capture.save.rga_active_calls=2
status_after_capture.save.rga_fallback_calls=0
status_after_capture.preprocess_mode=rga_active
smoke_camera_api_v4l2_rc=0
```

注意：1920x1080 native RGA rotate 当前返回 `imrotate failed: im2d_status=-1 src=1920x1080 dst=1080x1920`。代码已改为 RGA 先完成真实 `NV12 -> BGR`，再 CPU 后旋转，并在状态中标记：

```text
rga_transform=convert_only_cpu_rotate
post_rotate_cpu=True
native_transform_error=...imrotate failed...
```

这表示真实相机 NV12 已进入 RGA；但 90 度旋转不是由当前 native wrapper 在 1920x1080 上完成。

`gst_nv12_raw` 当前未通过，原因是板端 Python 缺 `gi`：

```text
open_camera_failed=GStreamer raw NV12 open failed: No module named 'gi'
smoke_gst_rc=10
```

正常 myui 服务已重启，`/api/status` 返回 `backend: ok`，Chromium kiosk 指向 `http://127.0.0.1:18080/index.html`，`index.html` 可由 HTTP 服务读取。

补充业务 smoke：使用 `test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga --captures 2` 连续保存两张后 stop 拼接通过：

```text
capture_count=2
status_after_capture.save.preprocess_mode=rga_active
status_after_capture.save.rga_active_calls=3
status_after_capture.save.rga_fallback_calls=0
stop.ok=True
stop.msg=stitched
result_name=stitched_20260509_095857_620120ac.jpg
actual_engine=opencv
two_capture_smoke_rc=0
```

## 2026-05-09 RGA 1080p 90-degree rotate diagnosis

This round focused only on why 1920x1080 90-degree rotation cannot be completed as a compact BGR888 native RGA output.

Implemented diagnostics:
- `native/rga/libmyui_rga.so` rebuilt as `myui_rga/1.2 rotate-diagnostics`.
- Added native C ABI diagnostics:
  - `myui_rga_bgr_rotate`
  - `myui_rga_bgr_rotate_strided`
  - `myui_rga_bgrx_rotate_to_bgr`
- Added `tests/smoke/test_rga_rotate_matrix_smoke.py`.
- `RgaPreprocessEngine` now records `native_success_detail` / `native_last_message` when available.

Board matrix result:
```text
rga_version=myui_rga/1.2 rotate-diagnostics
rga_api version 1.10.1_[1]

320x240: convert, 90, 270, 180 all ok
640x480: convert, 90, 270, 180 all ok
1280x720: convert, 90, 270, 180 all ok

1920x1080 convert only: ok
1920x1080 180: ok
1920x1080 90/270 compact BGR888 dst=1080x1920 stride=1080: fails
error=Unsupported function: dst unsupport width stride 1080, bgr888 width stride should be 16 aligned!

1920x1080 90/270 BGR888 dst=1080x1920 stride=1088: ok
```

Current conclusion:
- The failure is not raw NV12 capture and not NV12 -> BGR conversion.
- The failure occurs at BGR888 rotate/output when the rotated compact destination width stride is `1080`.
- librga/im2d requires BGR888 width stride to be 16-aligned. `1080` is not 16-aligned; `1088` works.
- Current preview/save remain working through `rga_transform=convert_only_cpu_rotate`, with `rga_fallback_calls=0`.
- Do not report 1920x1080 90-degree compact output as pure RGA. The stable production path remains RGA `NV12 -> BGR` plus CPU post-rotate until the image pipeline can accept padded BGR stride or a 4-byte/padded output format.

Camera regression after diagnostics:
```text
status_before_capture.last_frame_format=NV12
status_before_capture.preview.preprocess_mode=rga_active
status_before_capture.preview.rga_transform=convert_only_cpu_rotate
status_before_capture.preview.post_rotate_cpu=True
status_after_capture.save.preprocess_mode=rga_active
status_after_capture.save.rga_transform=convert_only_cpu_rotate
status_after_capture.save.post_rotate_cpu=True
status_after_capture.rga_fallback_calls=0
stop.ok=True
stop.msg=stitched
result_name=stitched_20260509_103513_8452f007.jpg
```

## 2026-05-09 preview smoothness update: default preview now requests raw NV12 + RGA

The previous frontend camera button sent only:
```json
{"mode": "manual"}
```

With the persistent `config.json` still set to `capture_backend=legacy_bgr` and `accel.preprocess=cpu`, the preview path was:
```text
/dev/video44 NV12
-> GStreamer videoconvert
-> BGR ndarray in Python
-> CPU rotate/resize/JPEG
-> /api/camera/frame.jpg polling from stitch.html
```

That path was expected to feel choppy because the browser requested one JPEG, waited for it to load, then slept 100 ms before requesting the next frame. It also skipped the raw NV12/RGA boundary.

Current code changes:
- `config.json` and `app/config.py` default to `accel.preprocess=rga` and `stitch.camera.capture_backend=gst_nv12_raw`.
- `app/capture/gst_raw_nv12_capture.py` now has `OpenCvGstRawNv12Capture`, which uses OpenCV `VideoCapture(..., CAP_GSTREAMER)` on the raw NV12 appsink pipeline. This avoids the board's missing Python GI dependency.
- `app/services/camera_service.py` tries OpenCV GStreamer raw NV12 first for `gst_nv12_raw`, then falls back to the existing GI implementation.
- `stitch.html` starts camera with `capture_backend=gst_nv12_raw` and `require_rga=true`.
- `stitch.html` uses `/api/camera/stream` MJPEG instead of repeated `/api/camera/frame.jpg` polling.
- `RgaPreprocessEngine` now records timing metadata such as `rga_convert_ms`, `cpu_rotate_ms`, `preview_jpeg_encode_ms`, and `preview_total_ms` in `last_preview_preprocess`.

Expected production path after deployment:
```text
/dev/video44 NV12
-> OpenCV GStreamer raw NV12 appsink
-> FramePacket(pixel_format=NV12)
-> RgaPreprocessEngine
-> RGA NV12 -> BGR
-> CPU post-rotate for 1920x1080 90/270 until padded-stride output is adopted
-> preview JPEG
-> MJPEG stream in browser
```

The remaining known CPU work is the 90-degree post-rotate and JPEG encode. This is not a fallback from RGA; status should still show `preprocess_mode=rga_active`, `rga_fallback_calls=0`, and `rga_transform=convert_only_cpu_rotate`.

Board validation after this update:
```text
py_compile_rc=0

test_gst_nv12_rga_smoke.py --frames 3 --require-rga:
capture_impl=opencv-gstreamer opened=True
pixel_format=NV12
width=1920
height=1080
stride_w=1920
stride_h=1080
buffer_size=3110400
source=gst-opencv-nv12:/dev/video44
stride_source=opencv-gstreamer-tight
preprocess_mode=rga_active
rga_wrapper_available=True
rga_active_calls=3
rga_fallback_calls=0
last_error=ok

test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga --captures 2:
status_before_capture.last_frame_format=NV12
status_before_capture.preview.preprocess_mode=rga_active
status_before_capture.preview.rga_transform=convert_only_cpu_rotate
status_before_capture.preview.rga_fallback_calls=0
status_after_capture.save.preprocess_mode=rga_active
status_after_capture.save.rga_transform=convert_only_cpu_rotate
status_after_capture.rga_fallback_calls=0
stop.ok=True
stop.msg=stitched
camera_api_gst_rga_rc=0
```

HTTP server path validation:
```text
POST /api/camera/start {"mode":"manual","capture_backend":"gst_nv12_raw","require_rga":true}
http_status.capture_backend=gst_nv12_raw
http_status.last_frame_format=NV12
http_status.preview.preprocess_mode=rga_active
http_status.preview.rga_fallback_calls=0
http_status.preview.rga_transform=convert_only_cpu_rotate
http_frame.status=200
http_frame.bytes=52044
```

Measured preview timing example from `/api/camera/status`:
```text
rga_convert_ms=9.876
cpu_rotate_ms=36.817
preview_resize_ms=35.846
preview_jpeg_encode_ms=8.443
preview_total_ms=103.237
```

Interpretation: the current visible stutter is no longer because the backend is using the old BGR/CPU path. The measured hot spots are CPU post-rotate, preview resize, and JPEG encode. RGA is active for real camera NV12 conversion.

## 2026-05-09 preview 30fps experiment

To test smoother preview, the persistent preview target was raised:
```text
preview_fps=30
```

Preview-specific RGA path was also changed so 90-degree preview no longer converts and rotates the full 1080x1920 BGR frame before resizing. For preview only:
```text
1920x1080 NV12
-> RGA convert+resize to 960x540 BGR
-> CPU rotate small BGR to 540x960
-> JPEG
```

Expected status marker:
```text
last_preview_preprocess.rga_transform=convert_resize_only_cpu_rotate
last_preview_preprocess.preview_pre_scaled=True
last_preview_preprocess.preview_pre_rotate_width=960
last_preview_preprocess.preview_pre_rotate_height=540
```

Save/capture path remains full-resolution and still reports `convert_only_cpu_rotate` for 1920x1080 90/270.

Board validation result:
```text
start.ok=True session_id=20260509_114141_7a45a470 preview_fps=30
status.capture_backend=gst_nv12_raw
status.last_frame_format=NV12
status.latest_frame_seq=173
status.preview_frame_seq=172
measured_preview_fps=30.29
preview.preprocess_mode=rga_active
preview.rga_transform=convert_resize_only_cpu_rotate
preview.preview_pre_scaled=True
preview.rga_convert_ms=11.368
preview.cpu_rotate_ms=6.821
preview.preview_resize_ms=0.0
preview.preview_jpeg_encode_ms=13.445
preview.preview_total_ms=31.829
```

This confirms the 30fps preview target is reachable in the sampled backend path. Remaining display smoothness should be judged in Chromium/kiosk, but backend preview production is now around the 33.3 ms frame budget.

## 2026-05-12 board drift update

- The currently inspected board no longer exposes `/dev/video44`.
- Visible `rkisp_mainpath` nodes were `/dev/video22` and `/dev/video31`. Earlier on 2026-05-12, `/dev/video-camera0` pointed to `/dev/video31`; a later serial retest on the same board showed `/dev/video-camera0 -> /dev/video22`.
- Backend defaults were updated to prefer `capture_backend=auto_raw` and `source=/dev/video-camera0` instead of hard-coding `gst_nv12_raw + /dev/video44`.
- Raw camera open now probes multiple device candidates before failing, so a stale fixed video node no longer blocks startup by itself.
- Later same-day board evidence narrowed the fault to one broken sensor path instead of the whole camera chain:
  - Boot `dmesg` showed `imx415 3-001a: Detected imx415 id 0000e0`.
  - The second sensor path still failed at boot with `imx415 7-001a: Unexpected sensor id(000000), ret(-5)`.
  - Direct `v4l2-ctl` capture from `/dev/video-camera0` and `/dev/video22` produced full `3840x2160` NV12 frames (`12441600` bytes), while `/dev/video31` still failed with `check rkisp_mainpath link or isp input`.
  - After manually starting the backend with `MYUI_DISABLE_KIOSK=1 sh /userdata/myui/start_myui.sh`, `/api/camera/start` succeeded on `/dev/video-camera0`, reported `open_source=gst-opencv-nv12-raw:/dev/video-camera0`, and reached `preprocess_mode=rga_active` with `rga_active_calls=32` and `fallback_calls=0`.
  - The remaining board-side problems are the broken second sensor path (`rkisp1` / `/dev/video31`) and the unfinished startup automation, not the primary `/dev/video22` capture path.
- Startup drift was also confirmed and fixed on the same board:
  - During serial inspection, `/etc/init.d/S51myui` was completely missing, so BusyBox `rcS` had no `myui` boot entry even though `/userdata/myui/start_myui.sh` itself still worked.
  - A repo-tracked `S51myui` init script was restored to `/etc/init.d/S51myui`, marked executable, and tested with `status` / `restart`.
  - After a full board reboot on 2026-05-12, `ps -ef` showed `python3 /userdata/myui/backend.py` and Chromium kiosk both started automatically, and `/etc/init.d/S51myui status` returned `myui python running`.
- Single-camera self-heal was added after the second sensor path proved unrecoverable from user space:
  - `start_myui.sh` now probes available `rkisp_mainpath` devices with one-frame `v4l2-ctl` capture before backend startup.
  - It rewrites `/dev/video-camera0` to the first device that actually returns a non-empty frame, so a stale alias no longer traps `myui` on the dead `video31` path.
  - This was verified by force-setting `/dev/video-camera0 -> video31`, then running `/etc/init.d/S51myui restart`; the service corrected the alias back to `video22`, came up normally, and `/api/camera/start` again reached `preprocess_mode=rga_active`.
  - `S51myui` was also hardened to invoke `start_myui.sh` / `stop_myui.sh` through `sh` as long as the files exist, so serial file sync no longer breaks startup just because execute bits were dropped.
- The broken second sensor path still appears to be below the application layer:
  - Both IMX415 nodes exist in live device tree (`i2c-3` and `i2c-7`), but only `3-001a` binds into the media graph.
  - The `i2c-7` path still reports `Unexpected sensor id(000000), ret(-5)` at boot.
  - Manually asserting its configured GPIOs (`gpio34` power, `gpio58` reset), then re-adding an `imx415` client on bus 7, still did not produce a usable `/dev/video31` frame.
  - The practical conclusion is that `/dev/video31` remains a board-level sensor/power/reset/connection problem; the software fix in this repo is to route the product reliably onto the working `/dev/video22` chain.
- Wi-Fi scan/list remained functional, but `/api/status` had a parsing bug: it could report `wifi: powered off` by matching the P2P block in `connmanctl technologies`. The status logic now scopes itself to the Wi-Fi block only.

## 2026-09-18 按代码复核：历史记录与当前代码的差异

本节只记录“历史章节写法”与“当前代码事实”不一致的地方，历史章节本身作为时间线保留，不再回改。

1. **采集节点**：历史多处写 `/dev/video44`。当前 `config.json` 的 `stitch.camera.source` 是 `/dev/video-camera0`，`camera_service.CAMERA_DEVICE_HINTS` 顺序为 `/dev/video-camera0`、`/dev/video44`、`/dev/video22`、`/dev/video31`、`/dev/video62`，并会先用 `v4l2-ctl --list-devices` 发现 `rkisp_mainpath` 节点。读旧章节时把 `/dev/video44` 当历史值。
2. **采集后端默认值**：历史有 `legacy_bgr`、`gst_nv12_raw` 两种说法。当前默认是 `auto_raw`：先尝试 GStreamer raw NV12（OpenCV 实现优先，GI 实现兜底），再尝试 `v4l2-ctl` raw NV12，最后才走 legacy OpenCV/GStreamer 与 `v4l2ctl` BGR 路径。前端 `stitch.html` 也发送 `capture_backend: 'auto_raw'`。
3. **拼接引擎默认值**：历史章节多次出现 `engine=builtin`。当前 `config.json` 是 `sequential`；`app/config.py:DEFAULT_CONFIG` 才是 `builtin`。
4. **几何引擎默认值**：`config.json` 是 `opencl`，`DEFAULT_CONFIG` 是 `cpu`。历史“默认仍是安全 CPU baseline”的说法对当前仓库配置已不成立。
5. **`OpenCLGeometryEngine` 不再是占位**：2026-05-12 章节写的 `actual_name` 固定为 `cpu` 已过期。当前实现会按 `DirectOpenCLRuntime.status()` 决定 `actual`/`mode_tag`，runtime 可用时是 `opencl` / `geometry_opencl_direct`。
6. **`SequentialPanoEngine` 不再是占位**：07 文档旧条目仍写“实现 SequentialPanoEngine”，实际它已完成顺序两两 ORB 拼接并带 `OpenCVStitchEngine` fallback。
7. **`RgaPreprocessEngine` 多了 `rga_ready`**：历史只提 `rga_active` / `rga_fallback_cpu`。当前 wrapper 加载成功但尚未处理 NV12 帧时是 `rga_ready`，不要把它当成失败。
8. **`preview_fps` 有三层默认值**：`config.json` 是 30，`DEFAULT_CONFIG` 也是 30，但 `safe_int(CAMERA_CONFIG.get("preview_fps", 15), 15, ...)` 的兜底是 15（取值范围 1~30）。同理 `normalize_choice` 对 `accel.*` 与 `stitch.engine` 也有独立兜底值，与 `DEFAULT_CONFIG` 不同。
9. **测试数量**：历史写过“4 条 / 5 条测试”。当前是 12 条（`test_opencl_geometry` 4、`test_preprocess` 2、`test_selector` 1、`test_stitch_engine` 4、integration 1）。
10. **`reports/` 目录**：历史章节引用 `reports/board-fetch-20260518-213920/...`，当前仓库工作区内没有 `reports/` 目录（`.gitignore` 忽略 `reports/*`），只有一个空的 `report/` 目录。需要复现快照时要重新拉取。
