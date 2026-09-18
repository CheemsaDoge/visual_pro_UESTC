# 07 下一步计划

最近更新：2026-09-18（按当前代码重新核对）

## 已经完成、不要重做

按当前代码核对，下面这些历史 TODO 已经完成，后续章节里同名条目属于时间线记录，不要再当成待办：

- 模块化重构与四类引擎边界（preprocess / geometry / selector / stitch）。
- `native/rga/libmyui_rga.so` 的交叉编译与 Python `ctypes` 接入；仓库内已有构建产物。
- 真实相机 raw NV12 采集：`gst_nv12_raw`、`v4l2ctl_nv12_raw`，以及 `auto_raw` 自动择优。
- `FramePacket` 的 stride/buffer 元数据，以及 `/api/camera/status` 中 preview/save 的分项耗时字段。
- `OpenCLGeometryEngine` 的 direct OpenCL `warpPerspective`（`ctypes -> libOpenCL.so`，不依赖 `cv2.ocl`）。
- `SequentialPanoEngine` 的顺序两两 ORB 拼接与 `OpenCVStitchEngine` fallback。
- `ScansStitchEngine`（OpenCV SCANS + 质量过滤 + `registration_resol=0.6`）。
- 相机节点动态化：`/dev/video-camera0` 别名 + `start_myui.sh` 出帧探测 + 多候选打开。
- `/etc/init.d/S51myui` 开机启动链路修复与验证。

## 当前最该做的事

1. **补 `OpenCLGeometryEngine.remap()` 的 direct OpenCL 实现。** 现在每次调用都只累加 `remap_fallback_calls` 并转给 CPU，是 GPU 覆盖面的最大缺口。
2. **扩大几何层的调用面。** 当前只有 `common.stitch_two_images_with_orb()` 直接用 `GeometryEngine`，也就是 `builtin` 的两图 fallback 和 `sequential` 的每一步。主 `cv2.Stitcher` 成功时完全绕过 GPU 路径，`ScansStitchEngine` 根本没接几何引擎。
3. **决定 1080p 90/270 旋转的归属。** 要让旋转留在 RGA，必须让下游接受 padded BGR stride（`1080` 活跃宽度 + `1088` stride），否则只能维持 RGA convert + CPU rotate。选型前不要动 `rga_engine.py` 的稳定路径。
4. **补齐测试可运行性。** 当前 12 条测试里 8 条依赖 `cv2`，缺 OpenCV 的环境直接导入失败。要么在 CI/开发机固定安装 `requirements.txt`，要么给这些测试加 skip 保护。
5. **对齐配置默认值。** 当前有三层默认值，容易让新会话读错：
   - `config.json`：`stitch.engine=sequential`、`accel.geometry=opencl`、`camera.preview_fps=30`
   - `app/config.py:DEFAULT_CONFIG`：`engine=builtin`、`geometry=cpu`、`preview_fps=30`
   - `safe_int` / `normalize_choice` 兜底：`preview_fps` 取 15，`preprocess`/`geometry` 取 `cpu`，`selector` 取 `off`，`engine` 取 `builtin`

   建议要么把 `DEFAULT_CONFIG` 与 `config.json` 对齐，要么在文档里统一声明“以 `config.json` / `/api/config/public` 为准”。

## 后续做什么

- GPU/OpenCL：先 `remap`，再让 `SequentialPanoEngine` 或自研拼接路径持续吃 `GeometryEngine`。
- NPU/RKNN：在有模型和 runtime 后替换 `RknnSelector` 的 `CpuSelector` 委托。
- 拼接算法：在 `sequential` 基础上做柱面投影、曝光/颜色一致性、增量融合，减少对黑盒 `cv2.Stitcher` 的依赖。
- 前端：`/api/stitch/output-clear` 后端已实现但三个页面都没调用；如需清理输出目录的入口可以补上。

## 哪些前提没满足前不要做

- 不要把 `cv2.ocl.haveOpenCL()` 当成 direct OpenCL 成败判断；当前项目的 GPU 路径走的是 `ctypes -> libOpenCL.so`，不是 OpenCV UMat。板端 OpenCV 4.5.4 至今仍是 `haveOpenCL=False`。
- 不要把 `rga_ready` 当成失败，也不要把 `rga_fallback_cpu` 报成成功；验收要看 `rga_active` 且 `rga_fallback_calls=0`。
- 不要把 `legacy_bgr` 路径的结果当成“真实 NV12 进入 RGA”的证据。
- 没有 RKNN 模型、输入规范、阈值验证前，不要接入真实 NPU 关键帧判断。
- 不要把 padded-stride RGA 旋转加 CPU 紧密化说成纯 RGA 输出。
- 改 `config.json` 后必须重启后端：四个引擎工厂都是模块级单例。

## native/rga 当前真实 C ABI

`native/rga/myui_rga.h` 现在导出的不止 2 个符号，下面这份才是当前完整清单（`rotate_code`：`0=none`、`1=ccw90`、`2=cw90`、`3=180`）：

```c
int myui_rga_available(void);
int myui_rga_nv12_to_bgr(const unsigned char *src_nv12, int src_w, int src_h,
                         unsigned char *dst_bgr, int dst_w, int dst_h, int rotate_code);
int myui_rga_bgr_rotate(const unsigned char *src_bgr, int src_w, int src_h,
                        unsigned char *dst_bgr, int dst_w, int dst_h, int rotate_code);
int myui_rga_bgr_rotate_strided(const unsigned char *src_bgr, int src_w, int src_h,
                                int src_wstride, int src_hstride,
                                unsigned char *dst_bgr, int dst_w, int dst_h,
                                int dst_wstride, int dst_hstride, int rotate_code);
int myui_rga_bgrx_rotate_to_bgr(const unsigned char *src_bgr, int src_w, int src_h,
                                unsigned char *dst_bgr, int dst_w, int dst_h, int rotate_code);
const char *myui_rga_last_error(void);
const char *myui_rga_version(void);
```

错误码：`MYUI_RGA_OK=0`、`ERR_BAD_ARGUMENT=-1`、`ERR_UNSUPPORTED=-2`、`ERR_NO_DEVICE=-3`、`ERR_ALLOC=-4`、`ERR_IM2D=-1000`。

若要实现 padded-stride 旋转路线，直接复用 `myui_rga_bgr_rotate_strided`，不需要再新增 native 接口。

## RGA 真实实现建议路线（历史记录，方案已落地）

下面几节是 2026-05-08/09 的历史推进记录。RGA wrapper 已经编译、部署并在板端验证 `rga_active`，这些“下一轮要做”的表述不再是当前待办，保留用于追溯选型理由。

推荐路线：**最小 C/C++ librga/im2d wrapper + Python ctypes + 保留 CPU fallback**。源码已落在 `native/rga/`。

下一轮优先顺序：

1. 在板端探测 RGA 资源：

   ```bash
   ls -l /dev/rga* /usr/lib*/librga.so* /lib*/librga.so* 2>/dev/null
   find /usr/include -iname '*rga*' -o -iname 'im2d.h' -o -iname 'RgaApi.h'
   ```

2. 若板端仍缺资源，补齐以下任一方案：

   - 安装/复制 Rockchip librga development headers：至少 `im2d.h` 及其依赖头。
   - 提供板端 `g++`。
   - 或使用外部 Buildroot/aarch64 sysroot 交叉编译 `libmyui_rga.so`，再复制到 `/userdata/myui/native/rga/`。

3. 在 `native/rga/` 编译最小 wrapper：

   ```text
   native/rga/myui_rga.cpp
   native/rga/myui_rga.h
   native/rga/Makefile
   ```

4. 最小 C ABI（当前完整清单见上文「native/rga 当前真实 C ABI」）。

5. 修改 `app/preprocess/rga_engine.py`：
   - wrapper 加载成功并处理成功：`mode_tag = rga_active`
   - wrapper 不存在、加载失败、单帧处理失败：自动 fallback CPU，`mode_tag = rga_fallback_cpu`

6. benchmark 必须能区分（当前还多一个 `rga_ready`，表示 wrapper 已加载但未处理 NV12 帧）：
   - `cpu_base`
   - `rga_fallback_cpu`
   - `rga_active`
   - `rga_wrapper_available`
   - `rga_active_calls`
   - `rga_fallback_calls`

   PC 或板端轻量 smoke 可先用：

   ```bash
   python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --output-json /tmp/benchmark_rga.json
   ```

   生产验收时必须加：

   ```bash
   python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --require-rga --output-json /tmp/benchmark_rga_require.json
   ```

   当前没有 `libmyui_rga.so` 时该命令应返回退出码 `3`。

6. 稳定后再把 capture 边界前移：
   - 当前多为 `FramePacket(pixel_format="BGR")`
   - 后续目标是 `FramePacket(pixel_format="NV12", data=raw_nv12)`

暂时不要做：

- 不要把 RGA 只藏进 GStreamer pipeline 作为主架构。
- 不要每帧 fork 外部命令。
- 不要一开始做复杂 DMA-BUF/零拷贝；先 virtual address 路径跑通。

## 2026-05-08 本轮后的下一步

本轮未能产出 `libmyui_rga.so`，原因不是 wrapper 代码路径，而是当前开发机也没有交叉编译资源。

下一步优先级固定如下：

1. 从 ATK/Rockchip SDK、Buildroot output 或 BSP 中取得 aarch64 toolchain、sysroot、librga headers 和目标 ABI `librga.so`。
2. 在 PC 端执行 `native/rga/Makefile` 交叉编译入口，产出 `native/rga/libmyui_rga.so`。
3. 用 `file`/`readelf` 确认产物是 aarch64 ELF shared object，并输出 `NEEDED` 依赖。
4. 通过 `tools/serial/serial_send_file_b64.ps1` 逐文件同步到 `/userdata/myui/native/rga/`，核对 md5。
5. 板端依次执行：

```bash
cd /userdata/myui/native/rga
make probe
make test-load
cd /userdata/myui
python3 tests/benchmark/run_benchmark.py \
  --preprocess rga \
  --selector off \
  --feed-format nv12 \
  --skip-stitch \
  --output-json /tmp/benchmark_rga.json
python3 tests/benchmark/run_benchmark.py \
  --preprocess rga \
  --selector off \
  --feed-format nv12 \
  --skip-stitch \
  --require-rga \
  --output-json /tmp/benchmark_rga_require.json
```

成功标准仍是 `preprocess_mode=rga_active`、`rga_wrapper_available=True`、`rga_active_calls>0`。在满足这些条件前，项目状态只能写成“RGA fallback 路径已验证正确，但 `rga_active` 还未打通”。

## 2026-05-09 RGA 已打通后的下一步

本轮已经满足上一节成功标准：

- `libmyui_rga.so` 已产出并同步到 `/userdata/myui/native/rga/`。
- 板端 `make test-load` 通过。
- 固定 320x240 NV12 样例通过。
- 普通 benchmark 和 `--require-rga` benchmark 均显示 `rga_active`、`rga_wrapper_available=True`、`rga_active_calls=2`。

下一阶段继续保持 **RGA first -> GPU next -> NPU later**，但不要扩散到 GPU/NPU。优先级调整为：

1. 把相机采集边界从当前多为 BGR ndarray 前移到原始 NV12 `FramePacket(pixel_format="NV12")`。
2. 用 `/dev/video44` 的真实 `1920x1080` NV12 帧验证 `RgaPreprocessEngine`，重点记录 stride、buffer 长度、返回码和耗时。
3. 在 camera API smoke 中确认预览/保存路径显示 `rga_active`，而不是只在 benchmark synthetic 中生效。
4. 保留 CPU fallback 和 `--require-rga` 验收开关；生产验收时必须让 fallback 失败、真实 RGA 通过。

暂时不要做：

- 不改 GPU/OpenCL。
- 不改 NPU/RKNN。
- 不重写拼接算法。
- 不把 RGA 隐藏进 GStreamer pipeline 作为主架构。

## 2026-05-09 raw NV12 相机链路下一步

代码侧已加入 `v4l2ctl_nv12_raw` 与 `gst_nv12_raw` 两个 capture backend。下一步优先级保持在相机 raw NV12 -> RGA，不扩散到 GPU/NPU/拼接算法：

1. 在板端先运行 `make py-check`，确认部署后的 Python 文件可导入。
2. 运行 `make smoke-camera-rga` 或 `python3 tests/smoke/test_v4l2_nv12_rga_smoke.py --frames 1 --require-rga`，先只验证真实 `/dev/video44` raw NV12 单帧进入 `RgaPreprocessEngine`。
3. 使用 `accel.preprocess=rga` 的配置启动 backend，再运行 `python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga`，验证手动保存路径。通过标准是 `last_frame_format=NV12` 且 `last_save_preprocess.preprocess_mode=rga_active`。
4. 若板端 Python GI 可用，再运行 `python3 tests/smoke/test_gst_nv12_rga_smoke.py --frames 1 --require-rga` 和 `python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga`，推进更实时的 preview/save 路线。
5. 如果预览因为 raw appsink 或帧率问题暂时不稳定，允许先报告“保存路径已 raw NV12/RGA，预览仍需继续下沉到 raw appsink 或优化 capture loop”，不要写成假成功。

验收命令示例：

```bash
cd /userdata/myui
make py-check
make smoke-camera-rga
make smoke-camera-api-rga
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga
```

需要记录的日志字段：

```text
last_frame_format
last_frame_buffer_size
last_frame_stride_w
last_frame_stride_h
last_preview_preprocess
last_save_preprocess
preprocess.mode_tag
rga_active_calls
rga_fallback_calls
```

## 2026-05-09 验证后下一步

已通过的阶段性验收：

- `v4l2ctl_nv12_raw` 能拿到真实 `/dev/video44` 的 1920x1080 NV12。
- preprocess-only smoke 已进入 `rga_active`。
- camera API preview 和 save 路径均显示 `rga_active`，`rga_fallback_calls=0`。
- HTML 已重新传到板端，服务重启后 `/api/status` 与 `index.html` 可访问。

后续优先级：

1. 若要把预览做成真正连续实时 raw appsink，先解决板端 `No module named 'gi'`，或实现不依赖 Python GI 的 raw GStreamer/V4L2 capture。
2. 调查 native RGA 对 `1920x1080 -> 1080x1920` 旋转返回 `im2d_status=-1` 的原因。当前可用状态是 RGA 做 `NV12 -> BGR`，CPU 做后旋转。
3. 如需生产默认走 raw NV12/RGA，可再决定是否把持久 `config.json` 的 `accel.preprocess` 改为 `rga`、`capture_backend` 改为 `v4l2ctl_nv12_raw` 或后续更实时 backend。
4. 再做一次手动连续拍 2 张以上并停止拼接的业务 smoke，确认新前端和保存图像业务流。

## 2026-05-09 next steps after 1080p rotate diagnosis

Current boundary is clear:
- 1920x1080 `NV12 -> BGR` through RGA is working.
- 1920x1080 180-degree BGR rotate through RGA is working.
- 1920x1080 90/270-degree compact BGR888 output fails because rotated width stride becomes `1080`, and librga requires BGR888 width stride to be 16-aligned.
- 1920x1080 90/270-degree RGA rotate works when destination BGR888 stride is padded to `1088`.

Recommended next work, only if production needs to reduce CPU post-processing:
1. Decide whether downstream preview/save/stitch code can accept a padded BGR image with active width `1080` and stride `1088`.
2. If yes, add a `ProcessedFrame` representation that can carry active dimensions plus stride, then use `myui_rga_bgr_rotate_strided` or an equivalent native padded-output path.
3. If downstream must remain compact `numpy` BGR, keep the current stable strategy: RGA convert plus CPU post-rotate. A padded RGA rotate would still need CPU compaction before current OpenCV/JPEG paths.
4. Do not label padded-output plus CPU compaction as pure RGA compact output.

Validation commands to rerun:
```bash
cd /userdata/myui
python3 tests/smoke/test_rga_rotate_matrix_smoke.py --sizes 1920x1080 --skip-preprocess
MYUI_CONFIG=/tmp/myui_config_rga.json python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend v4l2ctl_nv12_raw --require-rga --captures 2
```

## 2026-05-09 next steps after preview RGA/default-stream update

Immediate board validation:
```bash
cd /userdata/myui
make py-check
python3 tests/smoke/test_gst_nv12_rga_smoke.py --frames 3 --require-rga
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga --captures 2
/etc/init.d/S51myui restart
```

Then open `http://127.0.0.1:18080/stitch.html?mode=camera`, start preview, and verify `/api/camera/status` shows:
```text
capture_backend=gst_nv12_raw
last_frame_format=NV12
last_preview_preprocess.preprocess_mode=rga_active
last_preview_preprocess.rga_fallback_calls=0
last_preview_preprocess.rga_transform=convert_only_cpu_rotate
```

If preview still feels choppy after this change, use the new timing fields to decide the next small step:
1. High `cpu_rotate_ms`: consider a padded-stride downstream representation so 1080p 90/270 rotate can stay in RGA.
2. High `preview_jpeg_encode_ms`: lower `preview_max_dim` or JPEG quality, or add a more efficient stream format later.
3. Low backend timings but browser still choppy: inspect MJPEG rendering and Chromium/kiosk load.

Validation result for this step:
```text
gst_nv12_rga_rc=0
camera_api_gst_rga_rc=0
HTTP /api/camera/start -> gst_nv12_raw require_rga=true ok
HTTP /api/camera/status -> last_frame_format=NV12, preview.preprocess_mode=rga_active
HTTP /api/camera/frame.jpg -> 200, bytes=52044
```

Next optimization should be chosen from measured timing, not guessed. The first sample showed `preview_total_ms` around 103 ms, with significant time in CPU post-rotate and preview resize. The most direct RGA-side improvement would require downstream support for padded rotated BGR stride.

## 2026-05-18 operational next step: use the global dev-board skill pack for routine board access and artifact exchange

The host now has a reusable skill pack for board workflows:
- `C:\Users\ywjhn\.agents\skills\devboard-toolkit`
- `C:\Users\ywjhn\.agents\skills\devboard-serial`
- `C:\Users\ywjhn\.agents\skills\devboard-scp`

Default operational assumptions captured in those skills:
- serial `COM3` at `1500000`
- Wi-Fi SSID hint `zizek`
- Wi-Fi password `12345678`
- SSH user `root`

For future board sessions, prefer:
1. serial only for shell recovery and bootstrap
2. hotspot Wi-Fi plus `scp` for moving images, logs, and build outputs
3. dated snapshots under `reports/` for pulled board artifacts

Most recent fetched stitching snapshot:
- `reports/board-fetch-20260518-213920/in`
- `reports/board-fetch-20260518-213920/stitchout`

If a future session needs to inspect raw inputs and stitched outputs again, pull from:
- `/userdata/myui/stitch_input`
- `/userdata/myui/stitch_output`

Do not use the repo runtime directories `stitch_input/` and `stitch_output/` as the default landing zone for fetched board artifacts. Keep fetched copies isolated in `reports/board-fetch-*`.
