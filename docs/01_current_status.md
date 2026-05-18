# 01 当前状态

最近更新：2026-05-13

## 已完成

- `backend.py` 已变薄，只保留 HTTP transport、静态文件、MJPEG/单帧 JPEG 响应。
- 新增模块目录：
  - `app/config.py`
  - `app/routes/`
  - `app/services/`
  - `app/capture/`
  - `app/preprocess/`
  - `app/geometry/`
  - `app/selector/`
  - `app/stitch_engine/`
  - `app/utils/`
- 新增基础数据对象：`FramePacket`、`ProcessedFrame`，位于 `app/schemas.py`。
- 已接入引擎抽象：
  - `CpuPreprocessEngine`
  - `RgaPreprocessEngine`（当前 fallback 到 CPU）
  - `CpuGeometryEngine`
  - `OpenCLGeometryEngine`（当前 `warpPerspective` 可走 direct OpenCL，`remap` 仍 fallback 到 CPU）
  - `OffSelector`
  - `CpuSelector`
  - `RknnSelector`（当前 fallback 到 CPU basic）
  - `OpenCVStitchEngine`
  - `SequentialPanoEngine`（现为顺序两两 ORB 拼接，失败时回退到 OpenCV PANORAMA）
  - `ScansStitchEngine`（增强版 OpenCV SCANS 模式）
- 相机预览/保存已统一走 `PreprocessEngine`。
- 自动拍摄已改成“先 selector 判断是否保留，再保存”。
- `config.json` 已新增 `accel` 和 `selector.cpu_basic` 配置。
- 新增 `tests/unit/`、`tests/integration/`、`tests/benchmark/run_benchmark.py`。
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

保留主要 API：

- `/`
- `/api/config/public`
- `/api/status`
- `/api/camera/start`
- `/api/camera/capture`
- `/api/camera/stop`
- `/api/camera/status`
- `/api/camera/frame.jpg`
- `/api/camera/stream`
- `/api/stitch/status`
- `/api/stitch/image`
- `/api/stitch/input-list`
- `/api/stitch/output-list`
- `/api/stitch/output-clear`

## 当前限制

- `RgaPreprocessEngine` 已能通过 `ctypes` 调用 `libmyui_rga.so`，但当前板端尚未编译出 wrapper：缺 `im2d.h`/`RgaApi.h` 和 `g++`。
- 当前 Python 采集适配器进入预处理边界时仍主要是 BGR ndarray；即使 wrapper 编译成功，相机主链路仍需要把原始 NV12 buffer 更早封装为 `FramePacket(pixel_format="NV12")` 才能发挥 RGA 价值。
- 2026-05-12 板端已确认原生 `libOpenCL.so` 能枚举 `ARM Platform / Mali-G610 r0p0`，且 2026-05-13 已确认可以真实 `build program + launch kernel + read back`。
- 当前 `OpenCLGeometryEngine` 只把 `warpPerspective` 接到了 direct OpenCL；`remap` 仍明确回退到 CPU。
- 当前几何层只在 `OpenCVStitchEngine` 的 ORB fallback 路径直接调用；主 `cv2.Stitcher` 成功时不会自动经过这条 OpenCL 几何路径。
- `SequentialPanoEngine` 已实现顺序两两 ORB 拼接，但当前仍依赖特征匹配质量；复杂多图场景下仍可能回退到 `OpenCVStitchEngine`。
- `RknnSelector` 只是占位，未接真实 RKNN 推理。

## 当前默认主线

默认配置仍是安全 CPU baseline：

```json
"accel": {
  "preprocess": "cpu",
  "geometry": "cpu",
  "selector": "off"
}
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
