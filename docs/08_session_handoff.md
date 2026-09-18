# 08 新会话交接

> 头部四节（一页概括 / 当前架构 / 当前成果 / 当前问题）已于 2026-09-18 按代码重新核对（含 `feature-parameter` 合并后的拼接诊断功能）。下面带日期标题的章节是历史时间线，保留原样，不代表当前状态。

## 一页概括

这是 RK3588 图像拼接 GUI 项目。主线是 **RGA first → GPU next → NPU later**。`backend.py` 已经是薄 HTTP 入口（227 行），核心在 `app/`，预处理、几何、关键帧选择、拼接四类引擎都可插拔并带 fallback。

当前阶段位置：RGA 已真实生效，direct OpenCL 只覆盖 `warpPerspective`，NPU 仍是占位；最近新增了拼接诊断日志子系统，用于把耗时、参数、特征数据和资源占用呈现给用户。

## 当前架构

```text
backend.py                 227 行，HTTP + 静态 + MJPEG/单帧预览
app/config.py              471 行，config.json 加载与常量导出
app/schemas.py             FramePacket / ProcessedFrame
app/routes/                camera(49) / stitch(48) / system(212) / wifi(258)
app/services/              camera(1114) / stitch(211) / storage(141) / metrics(177)
                           + stitch_diagnostics(143) 拼接诊断报告
                           + geometry / preprocess / keyframe 三个单例工厂
app/capture/               gst_capture / gst_raw_nv12_capture(427) / v4l2_capture(151)
app/preprocess/            cpu_engine(162) / rga_engine(569)
app/geometry/              cpu_geometry / opencl_geometry(81) / opencl_runtime(505)
app/selector/              off / cpu_selector(148) / rknn_selector
app/stitch_engine/         base(48) / common(296) / opencv(129) / sequential(118) / scans(135)
native/rga/                myui_rga.cpp + .h + Makefile + 已构建的 libmyui_rga.so
tests/                     unit 11 条 + integration 1 条 + smoke 4 脚本 + benchmark
vendor/pannellum/          离线 Pannellum 2.5.7
前端                        index.html / stitch.html / wifi.html / stitch_log.html
```

## 当前成果

- API 路径兼容旧前端，完整清单见 `docs/04_api_compatibility.md`。
- 相机预览/保存统一走 `PreprocessEngine`；采集线程与预览编码线程分离，预览按 `preview_fps` 节流。
- 自动拍摄先 selector 判断再保存，丢弃帧计入 `dropped_count`。
- RGA：`native/rga/libmyui_rga.so` 已交叉编译产出并在板端验证 `rga_active`；`RgaPreprocessEngine` 记录 wrapper 候选路径、`lib_version`、active/fallback 计数、native 错误与分项耗时，并在 native 调用前校验 NV12 尺寸与数据长度。native 侧导出 7 个 C 符号（含 strided 旋转与 BGRX 诊断接口）。
- OpenCL：`app/geometry/opencl_runtime.py` 用 `ctypes -> libOpenCL.so` 直接建 context/queue/program/kernel，`warp_perspective()` 有真实 GPU 路径，板端对比 `cv2.warpPerspective` 的 `max_abs_diff=0`。
- 拼接：四种引擎均已实现（`builtin` / `sequential` / `scans` / `script`），`sequential` 是当前 `config.json` 的生效值。
- benchmark 输出 `preprocess_mode`、`preprocess_actual`、`preprocess_reason`、`rga_wrapper_available`、`rga_active_calls`、`rga_fallback_calls`、`geometry_mode`、`selector_mode`、`stitch_mode` 及 CPU/内存/温度快照，支持 `--feed-format`、`--skip-stitch`、`--rga-lib`、`--require-rga`。
- 相机节点动态化：`/dev/video-camera0` 别名 + `start_myui.sh` 出帧探测 + 多候选打开，不再硬编码 `/dev/video44`。
- 拼接可观测性（2026-09-18 合并 `feature-parameter`）：每次拼接生成一份诊断报告，含输入输出尺寸、引擎分阶段耗时、ORB 特征点/匹配/内点数、fallback 原因、CPU/内存/GPU/温度前后快照；通过 `GET /api/stitch/logs` 和 `stitch_log.html` 呈现，响应里也直接带 `log_id` + `stitch_log`。
- 启动链已验证：`/etc/init.d/S51myui -> /userdata/myui/start_myui.sh -> /userdata/myui/backend.py`，重启后 `myui python running`，Chromium kiosk 指向 `http://127.0.0.1:18080/index.html`。
- 2026-09-18 本地复核：合并后全量 `py_compile` 仍通过；`tests.unit.test_opencl_geometry` 4 条通过；其余 4 个测试模块因当前环境缺 `cv2` 而导入失败，拼接诊断链路尚未端到端跑通。

## 当前问题

- `OpenCLGeometryEngine.remap()` 没有 GPU 实现，每次调用只累加 `remap_fallback_calls` 并转给 CPU。
- 几何层只在 `common.stitch_two_images_with_orb()` 被直接调用（`builtin` 两图 fallback + `sequential` 每一步）。主 `cv2.Stitcher` 成功时绕过 GPU；`ScansStitchEngine` 完全不接几何引擎。
- 板端 OpenCV 4.5.4 仍 `haveOpenCL=False` / `useOpenCL=False`，所以不要用 `cv2.ocl` 判断本项目的 GPU 状态。
- 1920x1080 的 90/270 旋转仍由 CPU 补做，原因是 librga 要求 BGR888 width stride 16 对齐（`1080` 不合法，`1088` 可以）。状态里以 `rga_transform=convert_only_cpu_rotate` / `convert_resize_only_cpu_rotate` + `post_rotate_cpu=True` 显式标记。
- 板端缺 `im2d.h`/`RgaApi.h` 和 `g++`，不能在板上重编 wrapper，只能同步 PC 侧构建产物。
- `RknnSelector` 仍是占位，直接委托 `CpuSelector`。
- `config.json` 与 `app/config.py:DEFAULT_CONFIG` 在 `stitch.engine`、`accel.geometry`、`camera.preview_fps` 上不一致，读默认值时容易出错。
- 12 条测试里 8 条硬依赖 `cv2`，没有 skip 保护，缺 OpenCV 的环境会直接报导入错误；新增的 `stitch_diagnostics` 与引擎分阶段记录目前没有任何测试覆盖。
- 拼接诊断报告只存进程内存（`deque(maxlen=30)`），重启即丢；`StitchEngine.last_run_detail` 是单例实例属性，并发拼接会互相覆盖且未加锁。
- 诊断为取尺寸会对每张输入图和输出图各做一次 `cv2.imread()`，属于纯观测开销，大图多图时会拉长单次拼接耗时。
- `/dev/video31`（第二路 sensor / `rkisp1`）仍不可用，属于板级 DTS/供电/复位/连接问题，不是本仓库能修的范围。
- `/api/stitch/output-clear` 后端已实现，但四个前端页面都没有调用入口。


## RGA 下一轮实现路线

RGA 当前工程接入已经推进到 wrapper/ctypes 形态。下一轮不要再重新纠结方案，直接沿当前路径继续：

```text
最小 C/C++ librga/im2d wrapper
  -> 编译 native/rga/libmyui_rga.so
  -> Python app/preprocess/rga_engine.py 用 ctypes 调用
  -> 成功显示 rga_active，失败自动 rga_fallback_cpu
```

第一版只做 NV12 → BGR + resize + rotate。先用 virtual address 路径跑通，不要一开始做复杂 DMA-BUF/零拷贝。稳定后再把 capture 边界从当前 BGR ndarray 前移到 `FramePacket(pixel_format="NV12", data=raw_nv12)`。

当前已知板端缺口：

```text
有：/dev/rga
有：/lib/librga.so、/usr/lib/librga.so
有：ctypes 可加载 librga.so
缺：im2d.h / RgaApi.h / rga.h
缺：cc / gcc / g++
```

所以下一步是：补 headers + 编译器，或交叉编译 `native/rga/libmyui_rga.so` 并复制到 `/userdata/myui/native/rga/`。

板端优先探测命令：

```bash
ls -l /dev/rga* /usr/lib*/librga.so* /lib*/librga.so* 2>/dev/null
find /usr/include -iname '*rga*' -o -iname 'im2d.h' -o -iname 'RgaApi.h'
```

## 下一个最合理动作

若在本地继续（Windows 或开发机）：

```bash
python3 -m py_compile backend.py stitch_demo.py $(find app tests -name '*.py')
python3 -m pip install -r requirements.txt          # 缺 cv2 时必须先装，否则 8 条测试导入失败
python3 -m unittest discover tests                  # 目标是 12 条全绿
python3 backend.py                                  # 然后浏览器打开 http://127.0.0.1:18080
```

本地能覆盖：三个页面、全部 JSON 接口、静态图片拼接、Pannellum 展示。本地不能覆盖：相机、RGA、OpenCL、Wi-Fi，这些会自动降级成 fallback，不要当成缺陷。

若在板端继续：

```bash
cd /userdata/myui
make py-check
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga --captures 2
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --require-rga --output-json /tmp/benchmark_rga_require.json
/etc/init.d/S51myui restart
```

验收标准：`last_frame_format=NV12`、`preview.preprocess_mode=rga_active`、`save.preprocess_mode=rga_active`、`rga_fallback_calls=0`，以及 `require-rga` benchmark 退出码 `0`。

按代码现状，最有价值的下一步是补 `OpenCLGeometryEngine.remap()` 的 direct OpenCL 实现，并扩大 `GeometryEngine` 在真实拼接路径中的调用面。详见 `docs/07_next_steps.md` 的「当前最该做的事」。

## 板端文件同步

网络可用时优先 Wi-Fi + `scp`（见 `AGENTS.md` 中的 devboard skill 包与 `docs/06_pitfalls_and_findings.md` 的 2026-05-18 记录）。网络不可用时回退串口，工具在 `tools/serial/` 下。

## 串口同步要求

板端当前主要通过 Windows `COM3` 串口访问。生产同步不要再用大 tarball 一次性灌入；本轮验证过大 here-doc 可能触发 `debug>` 或破坏续行。优先使用：

- `tools/serial/serial_probe_prompt.ps1`：确认 root shell。
- `tools/serial/serial_push_and_run_slow.ps1`：执行小脚本。
- `tools/serial/serial_send_file_b64.ps1`：逐文件同步并核对 md5。

如果串口进入 FIQ `debug>`，输入 `console` 回 Linux console，再 `Ctrl-C` 回 root shell。

## 可复制给新对话的说明模板

```text
请接手 RK3588 图像拼接 GUI 项目。当前目录是 GUI/。
backend.py 是薄 HTTP 入口（227 行），核心在 app/，四类引擎可插拔且都有 fallback。
主线必须保持 RGA first → GPU next → NPU later。

当前真实状态：
- RGA 已生效：native/rga/libmyui_rga.so 已构建，板端验证过 rga_active。
  1920x1080 的 90/270 旋转仍由 CPU 补做（librga 要求 BGR888 stride 16 对齐）。
- OpenCL 只覆盖 warpPerspective（ctypes -> libOpenCL.so，不是 cv2.ocl）；remap 仍是 CPU。
  几何层只在 ORB 路径被调用，cv2.Stitcher 成功时会绕过它。
- RknnSelector 仍是占位，直接委托 CpuSelector。
- 拼接诊断日志已接入：每次拼接返回 log_id + stitch_log，页面在 stitch_log.html。
  报告只存内存（最近 30 条），后端重启即清空；该子系统暂无测试覆盖。
- config.json 生效值：stitch.engine=sequential、accel.preprocess=rga、accel.geometry=opencl、accel.selector=off。
  注意 app/config.py 的 DEFAULT_CONFIG 与之不同（builtin / cpu），只在配置缺字段时生效。
- 相机节点用动态别名 /dev/video-camera0，不要假设 /dev/video44 存在。

请先阅读 docs/00_project_overview.md、01_current_status.md、02_architecture.md、
03_config_and_run.md、04_api_compatibility.md、07_next_steps.md、08_session_handoff.md。
docs 里带日期标题的章节是历史时间线，不代表当前状态。

部署路径是 RK3588 /userdata/myui，启动链是
/etc/init.d/S51myui -> /userdata/myui/start_myui.sh -> /userdata/myui/backend.py。
下一步优先补 OpenCLGeometryEngine.remap() 并扩大 GeometryEngine 的调用面。
```

## 2026-05-08 RGA 交叉编译交接更新

本轮目标是优先交叉编译 `native/rga/libmyui_rga.so` 并同步到板端打通 `rga_active`。实际结果：未成功产出 `.so`，阻塞点是当前开发机也没有交叉编译资源。

已确认：

- `native/rga/Makefile` 已补充交叉编译变量：`CXX`、`SYSROOT`、`RGA_INCLUDE_DIR`、`RGA_LIB_DIR`。
- `native/rga/README.md` 已补充交叉编译命令、前提和常见失败原因。
- 本机 PATH、项目目录、`D:\dev`、`D:\ywjhn\desktop`、桌面、下载、文档目录未找到 aarch64 toolchain、`im2d.h`、`RgaApi.h`、`rga.h`、可用于交叉链接的 `librga.so`。
- Windows WSL 没有可用发行版。
- 因为没有 `libmyui_rga.so`，本轮未执行板端同步和 `rga_active` 验证。

下个会话不要重新争论 RGA/GPU/NPU 顺序。主线仍是 RGA first，下一步只需补齐 SDK/BSP/Buildroot 资源后继续：

```bash
cd native/rga
make CXX=aarch64-buildroot-linux-gnu-g++ \
  SYSROOT=/path/to/sysroot \
  RGA_INCLUDE_DIR=/path/to/librga/include \
  RGA_LIB_DIR=/path/to/librga/lib
```

拿到产物后再同步到 `/userdata/myui/native/rga/` 并跑 `make probe`、`make test-load`、固定 NV12 benchmark、`--require-rga` benchmark。这是 2026-05-08 的旧状态：当时只能宣称 RGA fallback 路径已验证正确，但 `rga_active` 还未打通。2026-05-09 的后续结果见下一节。

## 2026-05-09 RGA 打通交接更新

用户已把官方 Linux SDK 放到 `..\01linux_sdk`，本轮从 `atk-rk3588_linux_release_v1.2_20250104.tgz` 中确认：

- `linux/linux-rga` 项目存在，manifest path 为 `external/linux-rga`。
- RGA headers 已找到：`im2d_api/im2d.h`、`include/RgaApi.h`、`include/rga.h`、`include/RgaUtils.h`。
- Rockchip aarch64 toolchain repo 存在，但包内 `aarch64-none-linux-gnu-g++` 是 Linux x86_64 ELF，Windows 不能直接运行。

本轮实际做法：

- 用 Windows clang 16 `--target=aarch64-linux-gnu`、SDK libc headers、linux-rga headers 生成最小 `native/rga/libmyui_rga.so`。
- wrapper 改为调用 im2d C ABI：`wrapbuffer_virtualaddr_t`、`imcvtcolor_t`、`imresize_t`、`imrotate_t`。
- Python `RgaPreprocessEngine` 加载 wrapper 前先 `RTLD_GLOBAL` 加载板端真实 `librga.so`。
- benchmark synthetic 尺寸从 `300x220` 改为 `320x240`，避免 RGA virtual-address 路径在非友好尺寸上返回 `im2d_status=-1`。
- `make test-load` 改为只验证已部署的 `libmyui_rga.so`，不再因板端缺 `g++` 尝试重编。

板端验证证据：

```text
/userdata/myui/native/rga/libmyui_rga.so md5:
353e928594515b524c8a21dc569f3496

make test-load:
myui_rga_available= 1

fixed 320x240 NV12:
ret 0
last_error ok

benchmark normal:
preprocess_mode rga_active
preprocess_actual rga
rga_wrapper_available True
rga_active_calls 2
rga_fallback_calls 0

benchmark --require-rga:
require_rc=0
preprocess_mode rga_active
rga_active_calls 2
rga_fallback_calls 0
```

当前可宣称：`libmyui_rga.so` 已交叉产出并在板端加载，固定 NV12 和 benchmark 已进入 `rga_active`。下一步是接相机实时 NV12 链路，不要扩散到 GPU/NPU。

## 2026-05-09 raw NV12 相机链路交接

本轮目标收敛为：真实 `/dev/video44` NV12 尽量原样进入 `FramePacket(pixel_format="NV12")`，再进入 `RgaPreprocessEngine`，优先验证保存路径，再验证预览路径。

已完成代码改动：

- `app/schemas.py`：`FramePacket` 增加 `stride_w/stride_h/timestamp_ns/buffer_size/stride_inferred`，旧 BGR 调用保持兼容。
- `app/capture/v4l2_capture.py`：`V4L2CtlNv12Capture(raw_packet=True)` 可返回 raw NV12 `FramePacket`，不再强制 decode 成 BGR。
- `app/capture/gst_capture.py`、`app/capture/gst_raw_nv12_capture.py`：新增无 `videoconvert` 的 raw NV12 appsink pipeline。
- `app/preprocess/cpu_engine.py`、`app/preprocess/rga_engine.py`：NV12 输入支持 stride 元数据；RGA 调用前会把 strided NV12 紧密化，真实处理仍由 wrapper 做 NV12 -> BGR/rotate。
- `app/services/camera_service.py`：新增 `capture_backend` 开关，支持 `legacy_bgr`、`v4l2ctl_nv12_raw`、`gst_nv12_raw`；状态中新增 last frame 元数据和 preview/save preprocess 结果。
- `tests/smoke/`：新增 raw NV12 -> RGA 和 camera API preview/save smoke。
- `Makefile`：新增 `py-check`、`test-camera-nv12`、`smoke-camera-rga`、`smoke-camera-api-rga`。

本地验证：

```text
python -m py_compile ... 通过
python -m unittest tests.unit.test_preprocess tests.integration.test_preprocess_selector_stitch
Ran 3 tests, OK
```

板端待验证：

```bash
cd /userdata/myui
make py-check
python3 tests/smoke/test_v4l2_nv12_rga_smoke.py --frames 1 --require-rga
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga
python3 tests/smoke/test_gst_nv12_rga_smoke.py --frames 1 --require-rga
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga
```

报告时必须区分：

- `legacy_bgr`：进入 Python 已是 BGR，只能作兼容路径。
- `v4l2ctl_nv12_raw`：最适合先证明保存路径真实 NV12 -> RGA。
- `gst_nv12_raw`：更适合继续证明预览实时 raw NV12 -> RGA。

未在板端看到以下字段前，不要宣称真实相机链路已完成验收：

```text
last_frame_format=NV12
last_save_preprocess.preprocess_mode=rga_active
last_save_preprocess.rga_fallback_calls=0
last_preview_preprocess.preprocess_mode=rga_active
```

## 2026-05-09 板端验证交接更新

已同步到 `/userdata/myui/`：

- 本轮后端 raw NV12/RGA 代码
- smoke 脚本
- Makefile
- docs
- 用户重写的 `index.html`、`stitch.html`、`wifi.html`

传输方式为 `serial_send_file_b64.ps1` 逐文件传输，全部 remote/local md5 一致。

验证结果：

```text
make py-check -> py_check_rc=0

test_v4l2_nv12_rga_smoke:
pixel_format=NV12
width=1920
height=1080
stride_w=1920
stride_h=1080
buffer_size=3110400
preprocess_mode=rga_active
rga_wrapper_available=True
rga_active_calls=1
rga_fallback_calls=0
last_error=ok
smoke_v4l2_rc=0

test_camera_api_rga_smoke --capture-backend v4l2ctl_nv12_raw --require-rga:
last_frame_format=NV12
last_frame_buffer_size=3110400
preview.preprocess_mode=rga_active
save.preprocess_mode=rga_active
rga_fallback_calls=0
smoke_camera_api_v4l2_rc=0
```

重要限制：

```text
rga_transform=convert_only_cpu_rotate
post_rotate_cpu=True
native_transform_error=imrotate failed: im2d_status=-1 src=1920x1080 dst=1080x1920
```

当前准确表述：真实相机 NV12 已进入 RGA，RGA 完成 `NV12 -> BGR`，1920x1080 的 90 度旋转暂由 CPU 后处理。不要写成 native RGA 已完成大分辨率旋转。

`gst_nv12_raw` 未通过：

```text
GStreamer raw NV12 open failed: No module named 'gi'
smoke_gst_rc=10
```

正常服务已重启：

```text
python3 /userdata/myui/backend.py
chromium kiosk http://127.0.0.1:18080/index.html
/api/status -> backend ok
index.html -> HTTP 可读取
```

补跑两张保存后 stop 拼接：

```text
test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga --captures 2
capture_count=2
save.preprocess_mode=rga_active
save.rga_active_calls=3
save.rga_fallback_calls=0
stop.ok=True
stop.msg=stitched
result_name=stitched_20260509_095857_620120ac.jpg
actual_engine=opencv
two_capture_smoke_rc=0
```

## 2026-05-09 handoff: RGA 1080p rotate diagnosis

Scope completed in this round:
- Rebuilt `native/rga/libmyui_rga.so` as `myui_rga/1.2 rotate-diagnostics`.
- Added native diagnostics for BGR rotate, strided BGR rotate, and BGRX rotate-to-BGR.
- Added `tests/smoke/test_rga_rotate_matrix_smoke.py`.
- Synced updated `.so`, native sources, Python engine, smoke script, Makefile, and temporary RGA config to the board with md5 verification.

Important board evidence:
```text
/userdata/myui/native/rga/libmyui_rga.so md5:
75ad1c007997c635b2ba35f0b4dedfb5

rga_version=myui_rga/1.2 rotate-diagnostics
rga_api version 1.10.1_[1]

matrix op=nv12_to_bgr src=1920x1080 dst=1080x1920 rotate=ccw90 ok=False
last_error=...dst unsupport width stride 1080, bgr888 width stride should be 16 aligned...

matrix op=bgr_rotate_strided src=1920x1080 dst=1080x1920 dst_stride=1088x1920 rotate=ccw90 ok=True
matrix op=bgr_rotate_strided src=1920x1080 dst=1080x1920 dst_stride=1088x1920 rotate=cw90 ok=True
```

Conclusion:
- The 1080p 90/270 failure is a destination BGR888 stride alignment limit.
- Compact rotated destination stride `1080` is rejected by librga/imcheck.
- Padded destination stride `1088` is accepted.
- Current production-safe path is unchanged: real camera NV12 enters RGA for conversion, then CPU performs post-rotate for 1920x1080 90/270. This is intentionally marked as `rga_transform=convert_only_cpu_rotate`, `post_rotate_cpu=True`.

Regression smoke after the diagnostic change:
```text
MYUI_CONFIG=/tmp/myui_config_rga.json python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga --captures 2
status_before_capture.last_frame_format=NV12
status_before_capture.preview.preprocess_mode=rga_active
status_before_capture.preview.rga_transform=convert_only_cpu_rotate
status_after_capture.save.preprocess_mode=rga_active
status_after_capture.save.rga_transform=convert_only_cpu_rotate
status_after_capture.rga_fallback_calls=0
stop.ok=True
stop.msg=stitched
result_name=stitched_20260509_103513_8452f007.jpg
```

Do not report this as pure RGA 90-degree compact output. A future pure-ish RGA rotate path requires accepting padded BGR stride downstream, or it will still need CPU compaction.

## 2026-05-09 handoff: preview RGA/default-stream update

User asked whether the preview/video path also needs RGA optimization. The answer is yes: the default UI path was still `legacy_bgr` plus CPU preprocess and `/api/camera/frame.jpg` polling.

Implemented locally:
- Added `OpenCvGstRawNv12Capture` in `app/capture/gst_raw_nv12_capture.py`.
- `gst_nv12_raw` in `app/services/camera_service.py` now tries OpenCV GStreamer raw NV12 first, then GI GStreamer as fallback.
- Default config is now `accel.preprocess=rga` and `stitch.camera.capture_backend=gst_nv12_raw`.
- `stitch.html` starts camera with `capture_backend=gst_nv12_raw` and `require_rga=true`.
- `stitch.html` displays preview through `/api/camera/stream` MJPEG instead of 100 ms JPEG polling.
- `RgaPreprocessEngine` records timing fields: `rga_convert_ms`, `cpu_rotate_ms`, `preview_resize_ms`, `preview_jpeg_encode_ms`, `preview_total_ms`, and `save_total_ms`.

Expected board validation:
```bash
cd /userdata/myui
make py-check
python3 tests/smoke/test_gst_nv12_rga_smoke.py --frames 3 --require-rga
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga --captures 2
/etc/init.d/S51myui restart
```

Expected status after starting preview from the page:
```text
capture_backend=gst_nv12_raw
last_frame_format=NV12
last_preview_preprocess.preprocess_mode=rga_active
last_preview_preprocess.rga_fallback_calls=0
last_preview_preprocess.rga_transform=convert_only_cpu_rotate
```

Do not claim full pure RGA 90-degree preview. At 1920x1080 ccw90/cw90, current stable path is still RGA convert plus CPU post-rotate, and this should be visible in status.

Board validation completed:
```text
py_compile_rc=0
gst_nv12_rga_rc=0
camera_api_gst_rga_rc=0
```

Key evidence:
```text
capture_impl=opencv-gstreamer opened=True
source=gst-opencv-nv12:/dev/video44
pixel_format=NV12
buffer_size=3110400
preprocess_mode=rga_active
rga_active_calls=3
rga_fallback_calls=0

status_before_capture.last_frame_format=NV12
status_before_capture.preview.preprocess_mode=rga_active
status_after_capture.save.preprocess_mode=rga_active
stop.ok=True
stop.msg=stitched
```

HTTP server path also passed the important preview checks:
```text
POST /api/camera/start with capture_backend=gst_nv12_raw require_rga=true
http_status.last_frame_format=NV12
http_status.preview.preprocess_mode=rga_active
http_status.preview.rga_fallback_calls=0
http_frame.status=200
http_frame.bytes=52044
```

Timing sample:
```text
preview_total_ms=103.237
rga_convert_ms=9.876
cpu_rotate_ms=36.817
preview_resize_ms=35.846
preview_jpeg_encode_ms=8.443
```

Current conclusion for the user's "video feels choppy" question:
- It used to be legacy BGR/CPU plus repeated JPEG polling.
- It is now raw NV12/RGA plus MJPEG stream.
- Remaining stutter sources are CPU post-rotate, preview resize, JPEG encode, and browser display load. RGA conversion itself is working and relatively small in the measured sample.

## 2026-05-09 handoff: 30fps preview experiment

User asked to raise preview to 30fps. Local code changes:
- `config.json` and `app/config.py`: `preview_fps=30`.
- `RgaPreprocessEngine.process_for_preview()` now uses a preview-only pre-scaled path for 90-degree rotation:
  ```text
  RGA NV12 1920x1080 -> BGR 960x540
  CPU rotate 960x540 -> 540x960
  JPEG encode
  ```
- Status now exposes:
  ```text
  rga_transform=convert_resize_only_cpu_rotate
  preview_pre_scaled=True
  preview_pre_rotate_width=960
  preview_pre_rotate_height=540
  ```

Validation still needed after board sync:
```bash
cd /userdata/myui
python3 -m py_compile app/preprocess/rga_engine.py app/services/camera_service.py app/config.py
/etc/init.d/S51myui restart
```
Then start preview and inspect `/api/camera/status` for `preview_total_ms` and the pre-scaled markers.

Board validation result:
```text
py_compile_rc=0
start.ok=True preview_fps=30
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
preview_30fps_check_rc=0
```

The script's stop call returned HTTP 400 because it did not capture two images before stopping, which is the normal "need at least two captured images before stitching" guard. It does not affect the preview fps result.

## 2026-05-12 handoff: camera-node drift and Wi-Fi status fix

Board findings from the earlier 2026-05-12 serial inspection:
- `/dev/video44` was missing on the active board image.
- `v4l2-ctl --list-devices` showed `rkisp_mainpath` on `/dev/video22` and `/dev/video31`.
- `/dev/video-camera0` resolved to `/dev/video31`.
- `connmanctl services`, `/api/wifi/list`, and `iw dev wlan0 scan` all returned AP data, so hotspot discovery was not fully broken.
- `/api/status` could still say `wifi: powered off` because the old parser matched the P2P technology block instead of the Wi-Fi block.

Code changes made in this round:
- Default camera config changed to `capture_backend=auto_raw`.
- Default camera source changed to `/dev/video-camera0`.
- Raw camera startup now probes multiple device candidates for `gst_nv12_raw` and `v4l2ctl_nv12_raw` instead of trusting one fixed `/dev/video44`.
- `stitch.html` camera start now requests `capture_backend=auto_raw`.
- Wi-Fi status parsing now inspects only the Wi-Fi section of `connmanctl technologies`.

Important limitation:
- These software fixes remove the stale fixed-node assumption, but they do not repair a board whose ISP/sensor path is already down.
- On the inspected board, probing `/dev/video22` and `/dev/video31` still produced zero-byte NV12 frames with `check rkisp_mainpath link or isp input`, so further board-side camera bring-up is still required if preview/capture remains unavailable after sync.

Later same-day retest after the serial link was restored changed the camera conclusion:
- `/dev/video-camera0` had moved to `/dev/video22`, not `/dev/video31`.
- Boot `dmesg` showed a split sensor state:
  - `imx415 3-001a` probed successfully (`Detected imx415 id 0000e0`).
  - `imx415 7-001a` still failed at boot with `Unexpected sensor id(000000), ret(-5)`.
- Direct one-frame `v4l2-ctl` capture from `/dev/video-camera0` and `/dev/video22` succeeded and wrote full `12441600`-byte NV12 files.
- Direct capture from `/dev/video31` still failed with `VIDIOC_STREAMON returned -1 (Operation not permitted)` and `check rkisp_mainpath link or isp input`.
- The `myui` backend was not running at first, so `/api/status` and `/api/camera/start` initially returned connection refused.
- Manual backend start with `MYUI_DISABLE_KIOSK=1 sh /userdata/myui/start_myui.sh` fixed that part immediately.
- After the manual start, `/api/camera/start` succeeded with:
  - `capture_backend=auto_raw`
  - `open_source=gst-opencv-nv12-raw:/dev/video-camera0`
  - `preprocess_mode=rga_active`
  - `rga_active_calls=32`
  - `fallback_calls=0`
- Current practical conclusion:
  - primary camera path on `/dev/video22` is working again
  - RGA is active on real preview frames
  - the broken path is the second sensor / `rkisp1` / `/dev/video31`
  - startup automation is still unfinished, so backend availability after boot is not yet guaranteed

Later same-day boot-chain check changed the startup conclusion too:
- The active board image had no `/etc/init.d/S51myui` at all, so BusyBox `/etc/init.d/rcS` never had a `myui` autostart entry.
- `start_myui.sh` itself was still valid; the missing piece was the init wrapper.
- A repo-tracked `S51myui` script was restored to `/etc/init.d/S51myui`, chmodded to `755`, and verified with:
  - `sh -n /etc/init.d/S51myui`
  - `/etc/init.d/S51myui status`
  - `/etc/init.d/S51myui restart`
- `restart` started both:
  - `python3 /userdata/myui/backend.py`
  - Chromium kiosk on `http://127.0.0.1:18080/index.html`
- Full reboot verification on 2026-05-12 then confirmed the real boot path:
  - BusyBox booted through `rcS`
  - `/etc/init.d/S51myui` existed and was executable
  - `/etc/init.d/S51myui status` returned `myui python running`
  - `ps -ef` showed backend, weston, and Chromium all running after boot
  - `wget http://127.0.0.1:18080/api/status` returned backend `ok`
- Current startup conclusion:
  - the missing init entry was the real reason manual start worked while boot start failed
  - that boot-entry problem is now fixed on the inspected board
  - future deployments should keep syncing `S51myui` together with `/userdata/myui` content, not just HTML and Python files

Later same-day camera hardening added a durable single-camera mitigation:
- `start_myui.sh` now probes candidate `rkisp_mainpath` devices before backend startup and re-points `/dev/video-camera0` to the first one that returns a non-empty frame.
- `camera_service.py` hint order was also adjusted to prefer `/dev/video22` before `/dev/video31` when the alias is absent or stale.
- The mitigation was board-verified by:
  - forcing `/dev/video-camera0 -> video31`
  - running `/etc/init.d/S51myui restart`
  - confirming that restart rewrote the alias back to `/dev/video22`
  - confirming `/api/camera/start` then succeeded again with `open_source=gst-opencv-nv12-raw:/dev/video-camera0` and `preprocess_mode=rga_active`
- `S51myui` no longer insists that `start_myui.sh` or `stop_myui.sh` keep their executable bits; it now runs them via `sh` whenever the files exist. This matters because serial file sync can overwrite mode bits.

Later same-day board-level sensor tests also tightened the limit of what software can fix:
- Both IMX415 nodes exist in the live device tree:
  - `/proc/device-tree/i2c@feab0000/imx415@1a`
  - `/proc/device-tree/i2c@fec90000/imx415@1a`
- The working node uses GPIO1_B7 power and GPIO1_C1 reset in practice.
- The failing node is configured on different GPIOs (`gpio34` power, `gpio58` reset) but still reports `Unexpected sensor id(000000), ret(-5)`.
- Manual user-space attempts to revive the second path did not recover it:
  - forcing those GPIOs high
  - pulsing reset
  - creating a fresh `imx415` I2C client on bus 7
  - retrying `/dev/video31` capture
- `/dev/video31` still produced zero-byte output with `check rkisp_mainpath link or isp input`.
- Current practical conclusion:
  - the repo-level fix is complete for the single-camera product path
  - the remaining broken `rkisp1` / `/dev/video31` path now looks like board DTS / power / reset / sensor-module / connection work outside this GUI repo

## 2026-05-12 handoff: OpenCL recheck on the new board image

> The "placeholder" statement in this section was superseded by the 2026-05-13 section below. Kept as a timeline record only.

User asked to re-test whether the teammate's newly flashed image can finally use OpenCL.

Board-side evidence from serial probing:
- `/dev/mali0`, `/dev/dri/renderD128`, `/dev/dri/renderD129` all exist.
- `libOpenCL.so` and `libmali.so` are present.
- A direct Python `ctypes` probe against `libOpenCL.so` succeeded:
  - `platform_count=1`
  - platform=`ARM Platform`
  - vendor=`ARM`
  - device=`Mali-G610 r0p0`

Important limitation:
- OpenCV 4.5.4 still reports:
  - `cv2.ocl.haveOpenCL() == False`
  - `cv2.ocl.useOpenCL() == False`
  - `cv2.ocl.setUseOpenCL(True)` still leaves it `False`
- `cv2.getBuildInformation()` did not show OpenCL build flags on the board.
- Running
  `python3 tests/benchmark/run_benchmark.py --geometry opencl --preprocess cpu --skip-stitch --frames 2`
  still returned `geometry_mode=opencl_fallback_cpu`.
- `app/geometry/opencl_geometry.py` is still intentionally a CPU-delegating placeholder:
  - `actual_name = "cpu"`
  - `mode_tag = "opencl_fallback_cpu"`
  - `warp_perspective()` / `remap()` forward to `CpuGeometryEngine`

Current practical conclusion:
- The new image **does** have callable system-level OpenCL.
- The current repo **does not yet** use that capability for geometry acceleration.
- If future work should really enable OpenCL in this repo, the next branch point is:
  - either rebuild/replace OpenCV with working OpenCL support
  - or implement a direct non-OpenCV OpenCL geometry path in `app/geometry/`

## 2026-05-13 handoff: direct OpenCL warp path is now real

The user explicitly chose route `2`: do not depend on OpenCV UMat; implement a direct OpenCL path in the repo.

What was verified first on the board:
- System-level OpenCL was already enumerable on 2026-05-12.
- This round additionally verified true execution, not just enumeration:
  - `clCreateContext`: ok
  - `clCreateCommandQueue`: ok
  - `clBuildProgram`: ok
  - `clEnqueueNDRangeKernel`: ok
  - vector-add output matched expected values exactly

What was implemented locally and synced to `/userdata/myui`:
- `app/geometry/opencl_runtime.py`
  - direct `ctypes` binding to `libOpenCL.so`
  - runtime init: platform/device/context/queue/program/kernel
  - minimal BGR `warpPerspective` kernel on raw buffers
- `app/geometry/opencl_geometry.py`
  - `warp_perspective()` now tries direct OpenCL first
  - `remap()` still explicitly falls back to CPU
  - status now records `actual`, `mode_tag`, `active_calls`, `fallback_calls`, `device_name`, and last error
- Local tests:
  - new `tests/unit/test_opencl_geometry.py`
  - `tests/unit/test_stitch_engine.py` now forces ORB fallback once to confirm geometry-layer use

Board validation after sync:
```text
status_before.actual = opencl
status_before.mode_tag = geometry_opencl_direct
device_name = Mali-G610 r0p0

status_after.active_calls = 1
status_after.fallback_calls = 0
max_abs_diff = 0
mean_abs_diff = 0.0
ok = true
```

Important scope limit:
- This does **not** mean the whole stitching pipeline now runs on GPU.
- Today it means:
  - `OpenCLGeometryEngine.warp_perspective()` has a real GPU path.
  - `remap()` still falls back to CPU.
  - current app integration only hits `GeometryEngine` directly in `OpenCVStitchEngine._stitch_with_orb()`.
  - if `cv2.Stitcher` succeeds directly, it bypasses this geometry layer.

Most rational next steps from here:
1. Add direct OpenCL `remap()` so geometry coverage is no longer partial.
2. Push more real stitching flow onto `GeometryEngine` through `SequentialPanoEngine` or a less black-box path than `cv2.Stitcher`.
3. Only after that, decide whether an OpenCV-with-OpenCL rebuild is still worth doing.

## 2026-05-18 handoff: board access workflow is now split cleanly between serial bootstrap and hotspot scp

What changed operationally:
- A reusable Windows-host skill pack was installed under:
  - `C:\Users\ywjhn\.agents\skills\devboard-toolkit`
  - `C:\Users\ywjhn\.agents\skills\devboard-serial`
  - `C:\Users\ywjhn\.agents\skills\devboard-scp`
- The skill pack bundles working scripts for:
  - serial shell recovery from `debug>`
  - line-by-line board script execution over serial
  - Wi-Fi join through `connmanctl`
  - SSH key bootstrap through serial
  - `scp` push with MD5 verification

Defaults now encoded in the skill scripts:
- serial port `COM3`
- baud `1500000`
- SSID hint `zizek`
- password `12345678`
- SSH user `root`

Board-side Wi-Fi evidence from this session:
- board-visible hotspot name was `ZIZEK 6512`
- the default SSID hint `zizek` still matched correctly
- board IP after join was `192.168.137.123`
- host hotspot interface stayed on `192.168.137.1/24`

Practical workflow conclusion:
- use serial to recover the shell and bootstrap access
- once Wi-Fi plus SSH works, prefer `scp` over serial for any non-trivial file transfer
- keep integrity checks in the flow with `md5sum`

Board artifact retrieval completed in this session:
- source dirs on board:
  - `/userdata/myui/stitch_input`
  - `/userdata/myui/stitch_output`
- local snapshot created:
  - `reports/board-fetch-20260518-213920/in`
  - `reports/board-fetch-20260518-213920/stitchout`
- snapshot contents at fetch time:
  - `in`: 18 files, about `20.3 MB`
  - `stitchout`: 10 files, about `8.07 MB`

Important limit discovered during validation:
- later in the same session the host stopped enumerating any serial ports at all
- the reusable scripts were updated so they now fail fast with a clear "port not found" error instead of hanging
- this makes the recommended order even clearer: serial first, SSH plus scp afterwards, and keep using SSH as long as the board remains on the hotspot
