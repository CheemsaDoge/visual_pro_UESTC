# 07 下一步计划

最近更新：2026-05-13

## 当前正在做什么

已完成模块化重构初版和引擎边界落位。开发机基础验证已通过；2026-05-08 已在 RK3588 真机完成部署、API、benchmark、相机手动采集、启动项 smoke。本轮已新增 RGA 最小 wrapper 源码和 Python `ctypes` 接入，但板端缺 `im2d.h`/`RgaApi.h` 与编译器，暂未验证 `rga_active`。当前应优先继续：

1. 补齐或交叉编译 `native/rga/libmyui_rga.so` 所需开发资源。
2. 在板端编译并加载 wrapper，先用固定 NV12 样例验证 `NV12 -> BGR`。
3. 跑 `--preprocess rga --feed-format nv12 --skip-stitch` 的板端 benchmark，确认 `rga_active` 或准确 fallback 原因；生产验收时追加 `--require-rga`。
4. 在真机 UI 上人工确认三个页面的按钮流程。
5. 用手动模式连续拍 2 张以上，验证停止后真实相机图片拼接结果。

## 下一步做什么

1. 在 RK3588 上补充/复测 benchmark：
   - `--preprocess cpu --selector off`
   - `--preprocess rga --selector off --skip-stitch`，确认 `rga_active` 或 `rga_fallback_cpu`
   - `--preprocess rga --selector off --feed-format nv12 --skip-stitch --require-rga`，确认没有真实 RGA 时会失败、真实 RGA 时才通过
   - `--preprocess cpu --selector cpu_basic`
2. 接 RGA 最小真实链路：先 `NV12 -> BGR`，再扩展 resize/rotate。
3. 把 V4L2/GStreamer 捕获中的原始 NV12 buffer 更早传入 `FramePacket`，减少 Python 侧重复转换。
4. 给 `/api/camera/status` 或日志增加更细的预处理耗时统计。

## 后续做什么

- GPU/OpenCL：`warpPerspective` 的 direct OpenCL 已落位，下一步优先补 `remap`，再把更多真实拼接路径接到 `GeometryEngine`，避免只在 ORB fallback 中生效。
- NPU/RKNN：在有模型和 runtime 后替换 `RknnSelector` fallback。
- 拼接算法：实现 `SequentialPanoEngine`，做顺序配准、柱面投影、增量融合。

## 哪些前提没满足前不要做

- 不要把 `cv2.ocl.haveOpenCL()` 当成 direct OpenCL 成败判断；当前项目的 GPU 路径走的是 `ctypes -> libOpenCL.so`，不是 OpenCV UMat。
- 没有可调用 RGA binding 前，不要宣称 `rga_active`。
- 没有 RKNN 模型、输入规范、阈值验证前，不要接入真实 NPU 关键帧判断。
- 前端 API 兼容未验证前，不要大规模重写页面。

## RGA 真实实现建议路线（给下一轮）

推荐路线：**最小 C/C++ librga/im2d wrapper + Python ctypes + 保留 CPU fallback**。源码已落在 `native/rga/`，下一步重点不是再设计接口，而是补齐板端开发资源并编译部署 `libmyui_rga.so`。

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

4. 当前已导出最小 C ABI：

   ```c
   int myui_rga_available(void);
   int myui_rga_nv12_to_bgr(
       const unsigned char *src_nv12,
       int src_w,
       int src_h,
       unsigned char *dst_bgr,
       int dst_w,
       int dst_h,
       int rotate
   );
   ```

4. 修改 `app/preprocess/rga_engine.py`：
   - wrapper 加载成功并处理成功：`mode_tag = rga_active`
   - wrapper 不存在、加载失败、单帧处理失败：自动 fallback CPU，`mode_tag = rga_fallback_cpu`

5. benchmark 必须能区分：
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
