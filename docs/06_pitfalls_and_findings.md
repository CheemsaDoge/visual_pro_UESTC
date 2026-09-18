# 06 坑点与发现

本文按时间顺序累积，**同一主题后面的条目会推翻前面的条目**。阅读时先看下面的现行结论表，再按需回溯细节。

## 现行结论速查（2026-09-18 按代码核对）

| 主题 | 当前有效结论 | 已过期的旧条目 |
| --- | --- | --- |
| OpenCV OpenCL | 板端 `cv2.ocl.haveOpenCL()` 仍为 `False`，不要用它判断本项目 GPU 状态 | 仍然有效 |
| 项目 OpenCL 路径 | `ctypes -> libOpenCL.so` 的 direct 实现，`warpPerspective` 真实走 GPU | 2026-05-08/05-12 的「`OpenCLGeometryEngine` 是 placeholder」已过期，见 2026-05-13 条目 |
| `remap()` | 仍无 GPU 实现，每次调用累加 `remap_fallback_calls` 后转 CPU | — |
| 几何层覆盖面 | 只在 `common.stitch_two_images_with_orb()` 被直接调用 | — |
| RGA wrapper | 已交叉编译产出并在板端验证 `rga_active`；板端仍缺 headers/`g++`，不能就地重编 | 2026-05-08 的「未产出 `.so`、只能 fallback」已过期 |
| 1080p 90/270 旋转 | RGA 只做 `NV12 -> BGR`，旋转由 CPU 补做；根因是 BGR888 width stride 需 16 对齐 | — |
| 相机节点 | 动态别名 `/dev/video-camera0` + 多候选探测 | 所有硬编码 `/dev/video44` 的表述已过期，见 2026-05-12 条目 |
| 采集后端默认值 | `auto_raw`（raw NV12 优先） | `legacy_bgr`、`gst_nv12_raw` 作为默认值的表述已过期 |
| benchmark synthetic 尺寸 | 固定 320x240，不要改回 300x220 | — |
| 板端文件同步 | 网络可用时用 Wi-Fi + `scp`；串口只做 shell 恢复与 bootstrap | 「只能串口逐文件同步」已放宽，见 2026-05-18 条目 |

## [2026-05-08] OpenCV UMat/GPU 当前不可作为依赖前提

### 现象

已知环境中 Python OpenCV 可用，但 OpenCL 状态为不可用。

### 原因/判断

系统层存在 GPU/OpenCL 相关文件，不代表当前 OpenCV 构建已经启用或能通过 `UMat` 自动走 GPU。

### 已验证事实

- `cv2.ocl.haveOpenCL() == False`
- `cv2.ocl.useOpenCL() == False`
- 系统存在 `libOpenCL.so`
- 系统存在 `libmali.so`
- 系统存在 `/dev/mali0`
- 当前 OpenCV 不能直接通过 UMat 使用 GPU

### 当前结论

当前阶段不要把任何功能建立在 OpenCV UMat/GPU 已可用的前提上。`OpenCLGeometryEngine` 已保留接口，但默认 fallback CPU。

### 后续建议

后续若要启用 GPU/OpenCL，需要单独验证：OpenCV build flags、OpenCL ICD、Mali runtime、目标 kernel/driver、以及具体 `warpPerspective/remap` 的真实性能。

## [2026-05-12] 新镜像已能枚举原生 OpenCL 设备，但当前应用链路仍未真正启用

> 本节关于「`opencl_geometry.py` 是占位实现」的部分已被下一节（2026-05-13）推翻，仅保留作为时间线。系统层 OpenCL 可枚举、OpenCV `haveOpenCL=False` 这两条结论仍然有效。

### 现象

组员烧录的新镜像上，系统层 OpenCL 已不再只是“文件存在”；通过 `libOpenCL.so` 的原生 API 已能枚举到真实平台和设备。

### 已验证事实

- 板端存在 `/dev/mali0`、`/dev/dri/renderD128`、`/dev/dri/renderD129`。
- 板端存在 `libOpenCL.so` 与 `libmali.so`。
- 通过 Python `ctypes.CDLL("libOpenCL.so")` 调用原生 OpenCL API，已成功返回：
  - `platform_count = 1`
  - platform name = `ARM Platform`
  - platform vendor = `ARM`
  - device count = `1`
  - device name = `Mali-G610 r0p0`
- 但板端 OpenCV 4.5.4 仍返回：
  - `cv2.ocl.haveOpenCL() == False`
  - `cv2.ocl.useOpenCL() == False`
  - `cv2.ocl.setUseOpenCL(True)` 后仍为 `False`
  - `cv2.getBuildInformation()` 中未见 OpenCL build line
- 板端 benchmark 运行
  `python3 tests/benchmark/run_benchmark.py --geometry opencl --preprocess cpu --skip-stitch --frames 2`
  后，结果仍为 `geometry_mode=opencl_fallback_cpu`。
- `app/geometry/opencl_geometry.py` 当前仍是占位实现：即使探测到 OpenCL，也会把 `actual_name` 固定成 `cpu`，`warp_perspective()` 和 `remap()` 直接委托给 `CpuGeometryEngine`。

### 当前结论

当前要区分两层结论：

- **系统层**：新镜像已经可以调用 OpenCL runtime，并能枚举到 Mali-G610 设备。
- **应用层**：当前这套 GUI 仓库还不能把几何变换真正跑到 OpenCL 上。

因此，现在不能再写成“板子完全不可调用 OpenCL”；但也同样不能写成“本项目已经启用 OpenCL 几何加速”。

### 后续建议

若要让本项目真的使用 OpenCL，至少还要完成下面两件事之一：

- 重新构建/替换板端 OpenCV，使 `cv2.ocl.haveOpenCL()` 与 `cv2.ocl.useOpenCL()` 真正可用。
- 不走 OpenCV UMat，直接在 `app/geometry/` 中实现真实的 OpenCL 几何路径，而不是当前 placeholder + CPU fallback。

## [2026-05-13] Direct OpenCL warpPerspective 已接入，但覆盖范围仍有限

### 现象

在 2026-05-12 确认系统层 OpenCL 可用后，本轮已把 `OpenCLGeometryEngine` 改为 direct OpenCL 实现，不再只是占位 fallback。

### 已验证事实

- 板端通过项目内 `OpenCLGeometryEngine` 实测返回：
  - `actual = opencl`
  - `mode_tag = geometry_opencl_direct`
  - `device_name = Mali-G610 r0p0`
  - `active_calls = 1`
  - `fallback_calls = 0`
- 板端对一个小尺寸平移 `warpPerspective` smoke，OpenCL 输出与 `cv2.warpPerspective` 对比结果为：
  - `max_abs_diff = 0`
  - `mean_abs_diff = 0.0`
- 本轮 direct OpenCL 使用的是 Python `ctypes -> libOpenCL.so`，不是 `cv2.ocl` / UMat。
- 当前实现只覆盖 `warp_perspective()`。
- `remap()` 仍明确走 `CpuGeometryEngine` fallback。
- 当前应用里，几何层只在 `OpenCVStitchEngine._stitch_with_orb()` 这条 ORB fallback 路径被直接调用。

### 当前结论

现在可以准确写成：

- **系统层 OpenCL 可用**
- **项目里已有一条真实的 direct OpenCL 几何路径**

但还不能写成：

- **整个拼接流程已经全面走 GPU**

因为当前覆盖范围仍局限在 `warpPerspective`，而且只在 ORB fallback 路径直接生效。

### 后续建议

- 若要扩大 GPU 覆盖面，先补 `remap()` 的 direct OpenCL 实现。
- 若要让更多真实拼接流程吃到 GPU，下一步应让 `SequentialPanoEngine` 或更明确的自研拼接路径持续使用 `GeometryEngine`，而不是继续主要依赖黑盒 `cv2.Stitcher`。

## [2026-05-08] RGA 接口已落位，Python 绑定已接入，但板端缺开发资源

### 现象

`RgaPreprocessEngine` 存在并可被配置请求；本轮已改为加载 `native/rga/libmyui_rga.so` 并通过 `ctypes` 调用最小 C ABI。但当前板端尚未能编译 wrapper，实际模式仍为 `rga_fallback_cpu`。

### 原因/判断

目标板存在 `/dev/rga` 和 `librga.so`，但缺少 `im2d.h`/`RgaApi.h` 和本地 C/C++ 编译器。没有成功构建并部署 `libmyui_rga.so` 前，不能宣称 RGA 已真实生效。

### 已验证事实

- `app/preprocess/rga_engine.py` 会探测 `/dev/rga*`、`librga.so*`、headers 和 wrapper 候选路径。
- 已新增 `native/rga/myui_rga.cpp`、`myui_rga.h`、`Makefile`。
- C ABI 为 `myui_rga_available()` 和 `myui_rga_nv12_to_bgr(...)`。
- Python 只在 wrapper 可用且输入为 `FramePacket(pixel_format="NV12")` 时尝试真实 RGA。
- wrapper 不存在、输入不是 NV12、单帧调用失败时自动使用 `CpuPreprocessEngine`。
- Python 状态会记录 wrapper 候选路径、`lib_version`、active/fallback 调用次数。
- benchmark 会输出 `rga_wrapper_available`、`rga_active_calls`、`rga_fallback_calls`。
- PC 和板端轻量 benchmark 已验证可输出 `preprocess_mode=rga_fallback_cpu`。
- `--require-rga` 在当前没有 wrapper 时返回退出码 `3`，可用于生产 smoke 中防止误判。

### 当前结论

工程接入已推进到 “wrapper + ctypes + fallback” 形态，但由于板端缺开发资源，尚未验证 `rga_active`。当前只可宣称 fallback 路径正确，不能宣称 RGA 已生效。

### 后续建议

补齐 Rockchip librga development headers 和 aarch64 编译器，或使用外部 Buildroot/aarch64 sysroot 交叉编译 `libmyui_rga.so` 后部署到 `/userdata/myui/native/rga/`。之后优先用固定 NV12 样例验证输出 BGR，再把相机 capture 边界前移到 `FramePacket(pixel_format="NV12")`。

## [2026-05-08] 板端 RGA 运行时存在，但 development headers/compiler 缺失

### 现象

串口探测显示板端 RGA 运行资源存在，但不能直接在板端编译最小 wrapper。

### 已验证事实

- `/dev/rga` 存在。
- `/lib/librga.so`、`/usr/lib/librga.so`、`/lib64/librga.so`、`/usr/lib64/librga.so` 存在。
- Python `ctypes.CDLL('librga.so')` 可加载。
- `librga.so` 中可见 `c_RkRgaInit`、`c_RkRgaBlit`、`improcess` 等符号。
- `/usr/include`、`/usr/local/include`、`/opt`、`/userdata` 未找到 `im2d.h`、`RgaApi.h`、`rga.h`。
- 板端未找到 `cc`、`gcc`、`g++`。

### 当前结论

RGA runtime 已具备，development package 缺失。必须补 headers 和编译器/交叉编译环境，不能在缺依赖时写 CPU 假实现冒充 RGA。

### 后续建议

- 最短路径：把对应 BSP/SDK 中的 librga headers 和 aarch64 交叉编译产物部署到项目。
- 板端验证顺序：
  1. `cd /userdata/myui/native/rga && make probe`
  2. `make`
  3. `make test-load`
  4. 用固定 NV12 样例跑 `RgaPreprocessEngine`
  5. benchmark 确认 `rga_active`
  6. 生产验证时追加 `--require-rga`，确认 fallback 会失败、真实 RGA 才通过

## [2026-05-08] 串口大包同步不稳定，生产同步优先使用单文件 md5 helper

### 现象

通过 COM3 串口一次性灌入约 250KB 的 base64 here-doc 脚本时，板端 shell/串口回显容易被打断，曾出现进入 FIQ `debug>` 的情况，且大脚本中的续行可能被 CRLF 破坏。

### 原因/判断

生产板当前没有可用网络地址，主要依赖串口。串口适合小脚本和单文件分块同步，不适合一次性传输大包并同时执行复杂脚本。

### 已验证事实

- FIQ debugger 可通过输入 `console` 回到 Linux console，再 `Ctrl-C` 回 shell。
- `tools/serial/serial_push_and_run_slow.ps1` 使用更慢的 LF here-doc，可稳定执行小脚本。
- `tools/serial/serial_send_file_b64.ps1` 可逐文件 base64 传输，并打印远端 `md5sum` 与本地 MD5；本轮已用它同步 RGA 增量文件到 `/userdata/myui`。

### 当前结论

生产验证时，不要用大 tarball 通过串口一次性灌项目。优先逐个同步需要变更的文件，并核对 md5。

### 后续建议

若后续板端网络恢复，可改用 `rsync/scp`。在网络不可用前，使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "tools\serial\serial_send_file_b64.ps1" `
  -Port COM3 -Baud 1500000 `
  -LocalPath "本地文件路径" `
  -RemotePath "/userdata/myui/目标路径"
```

## [2026-05-08] 自动拍摄保存策略已变化

### 现象

自动模式不再固定间隔全存；若 selector 开启，可能出现丢帧计数。

### 原因/判断

为了后续 NPU/RKNN 接入，保存链路必须先经过 `KeyframeSelector`。

### 已验证事实

- 默认 `selector=off`，兼容旧行为。
- `selector=cpu_basic` 时会根据时间间隔、清晰度、差异度判断。
- `/api/camera/status` 返回 `last_selector_decision` 和 `dropped_count`。

### 当前结论

前端无需大改，但调试自动拍摄时要关注 selector 状态。

### 后续建议

后续在 UI 上可展示保留/丢弃原因，但本阶段不重写前端。

## [2026-05-08] 板端启动项已确认指向 `/userdata/myui`

### 现象

模块化版本部署到开发板后，需要确认不是只在串口手动启动，而是开机启动项也走正确入口。

### 原因/判断

Buildroot 板端使用 BusyBox init，`/etc/inittab` 调用 `/etc/init.d/rcS`，rcS 会执行 `/etc/init.d/S*` 脚本。当前项目启动项是 `/etc/init.d/S51myui`。

### 已验证事实

- `/etc/init.d/S51myui` 存在且可执行。
- `S51myui` 中配置：
  - `MYUI_BASE=/userdata/myui`
  - `START_SCRIPT="$MYUI_BASE/start_myui.sh"`
  - `STOP_SCRIPT="$MYUI_BASE/stop_myui.sh"`
  - `BACKEND_FILE="$MYUI_BASE/backend.py"`
- 执行 `/etc/init.d/S51myui restart` 后，`/etc/init.d/S51myui status` 返回 `myui python running`。
- restart 后 `/api/status` 可访问。
- 进程中存在 `python3 /userdata/myui/backend.py`。
- 进程中存在 Chromium kiosk，URL 为 `http://127.0.0.1:18080/index.html`。

### 当前结论

启动项路径正确，当前板端启动入口是 `/etc/init.d/S51myui -> /userdata/myui/start_myui.sh -> /userdata/myui/backend.py`。

### 后续建议

后续更换部署目录时，必须同步检查 `/etc/init.d/S51myui` 的 `MYUI_BASE`，否则会出现手动运行正常但开机仍启动旧版本的问题。

## [2026-05-08] RGA 真实接入方案选择记录

### 现象

当前 `RgaPreprocessEngine` 已有接口、探测和 fallback，但尚未真正调用 RGA。需要为下一轮会话明确 RGA 预处理实现路线，避免新会话重新讨论方案。

### 原因/判断

当前 Python 后端进入预处理边界时主要拿到的是 BGR ndarray；真实 RGA 加速要尽量更早拿到 NV12 原始帧，并通过稳定、可 benchmark 的接口完成 NV12→BGR、resize、rotate、preview。

### 已比较方案

1. **GStreamer RGA 插件替换 `videoconvert`**
   - 优点：改动可能较小。
   - 缺点：插件可用性/名称/能力不确定；RGA 被藏在 capture pipeline 中，不利于 `PreprocessEngine` 抽象和分项 benchmark。
   - 结论：可作为临时验证，不作为主架构。

2. **Python 直接 `ctypes` 调 `librga.so`/im2d**
   - 优点：能放进 `RgaPreprocessEngine`，符合现有架构。
   - 缺点：RGA 结构体、stride、format、cache、buffer 对齐都在 Python 里处理，容易踩坑。
   - 结论：可行，但不推荐纯 Python 直接硬写复杂结构。

3. **最小 C/C++ wrapper + Python `ctypes` 调 wrapper**
   - 优点：Python 接口干净；RGA/im2d 细节留在 C 层；后续可扩展 DMA-BUF/virtual address；失败时可明确 fallback CPU。
   - 缺点：需要在板端或交叉环境编译 `libmyui_rga.so`。
   - 结论：推荐主线。

4. **每帧调用外部命令行工具**
   - 优点：最容易临时试通。
   - 缺点：fork/exec 成本高，不适合 preview/自动拍摄，benchmark 会被进程启动开销污染。
   - 结论：不作为正式实现，只可用于一次性能力探测。

### 当前结论

推荐下一轮采用：

```text
native/rga/libmyui_rga.so
  C/C++ 最小 wrapper 封装 librga/im2d
app/preprocess/rga_engine.py
  Python ctypes 加载 wrapper
  wrapper 可用：mode_tag = rga_active
  wrapper 不可用/失败：mode_tag = rga_fallback_cpu
```

优先导出最小 C ABI，例如：

```c
int myui_rga_available(void);

int myui_rga_nv12_to_bgr_resize_rotate(
    const unsigned char *src_nv12,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate
);
```

### 后续建议

下一轮先在板端探测资源：

```bash
ls -l /dev/rga* /usr/lib*/librga.so* /lib*/librga.so* 2>/dev/null
find /usr/include -iname '*rga*' -o -iname 'im2d.h' -o -iname 'RgaApi.h'
```

然后新增：

```text
native/rga/myui_rga.c 或 native/rga/myui_rga.cpp
native/rga/myui_rga.h
native/rga/Makefile
```

第一版只实现 NV12 → BGR + resize + rotate 的最小路径，不要一开始做 DMA-BUF 和复杂零拷贝。稳定后再把 capture 边界从 BGR ndarray 前移到 `FramePacket(pixel_format="NV12", data=raw_nv12)`。

## [2026-05-08] 本机也缺 RGA 交叉编译资源

### 现象

按本轮任务书优先走交叉编译，但在当前开发机未找到可用资源，无法产出 `native/rga/libmyui_rga.so`。

### 已查找路径和结果

- PATH：未找到 `aarch64-linux-gnu-g++`、`aarch64-none-linux-gnu-g++`、`aarch64-buildroot-linux-gnu-g++` 或对应 `gcc`。
- 项目目录及上级常见工程目录：未找到 `im2d.h`、`RgaApi.h`、`rga.h`、`librga.so` 或 aarch64 工具链。
- `D:\dev`、`D:\ywjhn\desktop`、`C:\Users\ywjhn\Desktop`、`C:\Users\ywjhn\Downloads`、`C:\Users\ywjhn\Documents`：未找到上述关键文件。
- Windows WSL：没有可用 Linux 发行版，不能作为交叉编译环境。

### 当前结论

本机和板端目前都缺开发资源。板端有 `/dev/rga` 和 `librga.so`，但缺编译器和 headers；本机缺 aarch64 toolchain、librga headers、目标 ABI `librga.so` 或 sysroot。因此不能继续编译、同步、加载 `libmyui_rga.so`，也不能宣称 `rga_active`。

### 后续建议

需要从 ATK/Rockchip SDK、Buildroot output 或板卡 BSP 中补齐至少以下内容：

- aarch64 GNU/Buildroot C++ 编译器。
- 目标 sysroot，或至少与板端 ABI 匹配的 `librga.so`。
- Rockchip librga development headers，至少包含 `im2d.h` 及其依赖头文件。

拿到后使用：

```bash
cd native/rga
make CXX=aarch64-buildroot-linux-gnu-g++ \
  SYSROOT=/path/to/sysroot \
  RGA_INCLUDE_DIR=/path/to/librga/include \
  RGA_LIB_DIR=/path/to/librga/lib
```

当前必须继续保持 `rga_fallback_cpu` 正常，不要用 CPU 假实现冒充 RGA。

## [2026-05-09] RGA wrapper 已加载成功，benchmark 尺寸需要 RGA 友好对齐

### 现象

`libmyui_rga.so` 部署后，板端可以加载 wrapper，`myui_rga_available=1`。但旧 benchmark synthetic 默认尺寸 `300x220` 会在 `imcvtcolor` 返回 `im2d_status=-1`，导致 `rga_fallback_cpu`。

### 原因/判断

RGA 对 virtual-address 图像尺寸/stride 更敏感。`300x220` 虽然是偶数，但不是 RGA 更稳妥的对齐尺寸；固定 `320x240` NV12 样例可以正常 `NV12 -> BGR`。

### 已验证事实

- 固定 `320x240` NV12 direct wrapper 调用：
  - `available 1`
  - `ret 0`
  - `last_error ok`
- benchmark synthetic 调整为 `320x240` 后：
  - `preprocess_mode rga_active`
  - `preprocess_actual rga`
  - `rga_wrapper_available True`
  - `rga_active_calls 2`
  - `rga_fallback_calls 0`
- `--require-rga` benchmark 返回 `require_rc=0`。

### 当前结论

`rga_active` 已在固定 NV12/benchmark 路径打通。后续接相机实时链路时，不要只检查 NV12 是否偶数宽高，还要关注 RGA 对 stride/对齐/尺寸的限制；相机真实 `1920x1080` NV12 理论上比 `300x220` synthetic 更符合硬件路径。

### 后续建议

下一步再把 capture 边界前移到 `FramePacket(pixel_format="NV12")` 时，保留尺寸、stride、buffer 长度、RGA 返回码和 `myui_rga_last_error()` 的日志。遇到 fallback 时先判断是否是尺寸/stride 限制，而不是退回重写架构。

## 2026-05-09 raw NV12 相机链路注意事项

本轮明确了三条采集边界：

- GStreamer legacy 路线通过 `videoconvert` 输出 BGR appsink，进入 Python 时已经不是原始 NV12。该路径只能作为兼容 fallback，不能作为真实 NV12 -> RGA 的验收证据。
- `v4l2ctl_nv12_raw` 路线从 `v4l2-ctl --stream-to` 读取 raw bytes，适合先验证手动保存路径。缺点是每帧调用外部命令，不适合作为最终高帧率预览路线。
- `gst_nv12_raw` 路线使用 raw NV12 appsink，适合继续推进预览/实时链路，但依赖板端 Python GI/GStreamer introspection 可用；如果板端缺 `gi.repository.Gst`，先用 `v4l2ctl_nv12_raw` 完成保存路径验收。

判断真实相机是否进入 RGA 时，不要只看 API 成功或 JPEG 是否生成，必须同时看：

```text
last_frame_format=NV12
last_frame_buffer_size=...
last_frame_stride_w=...
last_frame_stride_h=...
last_save_preprocess.preprocess_mode=rga_active
last_save_preprocess.rga_fallback_calls=0
```

预览路径如果仍显示 `source_pixel_format=BGR` 或 `preprocess_mode=cpu_base/rga_fallback_cpu`，不能写成预览已进入真实 RGA。保存路径和预览路径分别记录 `last_save_preprocess` 与 `last_preview_preprocess`，报告时必须分开说明。

RGA wrapper 当前 C ABI 仍接收紧密 NV12 virtual address。Python 侧对带 stride 的 NV12 会在调用 wrapper 前紧密化为连续 NV12 数组，这是本阶段允许的一次内存拷贝；这不是 DMABUF/零拷贝实现。

## 2026-05-09 板端 raw NV12 验证新增发现

真实 `/dev/video44` 经 `v4l2-ctl --stream-to` 抓到的是紧密 NV12：

```text
pixel_format=NV12
width=1920
height=1080
stride_w=1920
stride_h=1080
buffer_size=3110400
stride_inferred=False
```

失败点曾出现在 native RGA 旋转，而不是 capture 边界：

```text
myui_rga_nv12_to_bgr ret=-1001
imrotate failed: im2d_status=-1 src=1920x1080 dst=1080x1920
```

修正策略是：RGA 仍负责真实相机 `NV12 -> BGR`，当 1920x1080 的 native rotate 失败时，旋转在 RGA 输出 BGR 后由 CPU 完成。状态里必须保留：

```text
rga_transform=convert_only_cpu_rotate
post_rotate_cpu=True
native_transform_error=...imrotate failed...
```

因此报告时应写成“真实 NV12 已进入 RGA，当前 90 度旋转为 CPU 后处理”，不要写成“完整 NV12 转换和旋转都由 RGA 完成”。

`gst_nv12_raw` 没有进入验证阶段，当前阻塞为板端缺 Python GI：

```text
GStreamer raw NV12 open failed: No module named 'gi'
```

这不影响 `v4l2ctl_nv12_raw` 对保存/预览路径的阶段性验收，但后续要做真正实时 appsink，需要补齐 GI 或改用不依赖 Python GI 的 raw capture 实现。

## 2026-05-09 finding: 1920x1080 90-degree compact BGR888 RGA rotate fails because dst stride is not 16-aligned

The failing native step is now explicit:

```text
NV12 -> BGR888 temporary: ok
BGR888 temporary 1920x1080 -> compact BGR888 dst 1080x1920: fails
im2d_status=-1(NOT_SUPPORTED)
im2d_error=Unsupported function: dst unsupport width stride 1080, bgr888 width stride should be 16 aligned!
src=1920x1080 stride=1920x1080 fmt=BGR888 bytes=6220800
dst=1080x1920 stride=1080x1920 fmt=BGR888 bytes=6220800
```

Matrix boundary:
```text
320x240 90/270/180: ok
640x480 90/270/180: ok
1280x720 90/270/180: ok
1920x1080 convert only: ok
1920x1080 180: ok
1920x1080 90/270 compact dst stride=1080: not supported
1920x1080 90/270 padded dst stride=1088: ok
```

Important interpretation:
- `im2d_status=-1` maps to `IM_STATUS_NOT_SUPPORTED`.
- This is a BGR888 output stride limitation after 90-degree rotation, not a `/dev/video44` capture issue.
- BGRX staging can rotate, but converting the rotated BGRX result back into compact BGR888 still fails for the same destination stride `1080`.
- A compact `numpy` BGR image of shape `(1920, 1080, 3)` has width stride `1080`, so the current API cannot make that final compact BGR output purely through RGA for 90/270 degrees.
- RGA can rotate to padded BGR888 stride `1088`; using that in production would require the rest of the pipeline to accept padded stride, or an explicit CPU compaction step. That is not the same as pure RGA compact output.

Current stable strategy remains:
```text
raw NV12 camera frame
-> RGA NV12 -> BGR
-> CPU post-rotate for 1920x1080 90/270
```

The status fields must keep showing the partial path:
```text
rga_transform=convert_only_cpu_rotate
post_rotate_cpu=True
native_transform_error=...bgr888 width stride should be 16 aligned...
```

## 2026-05-09 finding: preview stutter was mainly legacy BGR + JPEG polling, not camera read failure

The browser "video" on `stitch.html` was not a video stream. It repeatedly loaded `/api/camera/frame.jpg`, waited for `img.onload`, then delayed another 100 ms. That caps smoothness around 10 fps before backend preprocess, JPEG encode, browser decode, and HTTP overhead are counted.

The default camera payload also did not request the raw NV12/RGA backend. With persistent defaults at `capture_backend=legacy_bgr` and `accel.preprocess=cpu`, preview used:
```text
NV12 camera -> videoconvert -> BGR ndarray -> CPU preprocess -> JPEG polling
```

New production default is:
```text
NV12 camera -> OpenCV GStreamer raw NV12 appsink -> FramePacket(NV12) -> RGA preprocess -> MJPEG stream
```

Remaining sources of latency:
- RGA still performs the real `NV12 -> BGR` conversion.
- 1920x1080 90/270 post-rotate remains CPU because compact BGR888 destination stride `1080` is rejected by librga; status marks this as `rga_transform=convert_only_cpu_rotate`.
- Preview JPEG encoding is still CPU/OpenCV and now has `preview_jpeg_encode_ms` timing in status.

When evaluating choppiness, inspect `/api/camera/status`:
```text
last_frame_format=NV12
last_preview_preprocess.preprocess_mode=rga_active
last_preview_preprocess.rga_transform=convert_only_cpu_rotate
last_preview_preprocess.rga_convert_ms=...
last_preview_preprocess.cpu_rotate_ms=...
last_preview_preprocess.preview_jpeg_encode_ms=...
last_preview_preprocess.preview_total_ms=...
```

Board-side fixes from validation:
- OpenCV GStreamer could not open the GI-oriented pipeline because it used `appsink name=sink`; OpenCV reported `cannot find appsink in manual pipeline`. The OpenCV capture class now uses an unnamed `appsink`, while the GI class keeps `name=sink`.
- Camera service initially treated `gst-opencv-nv12-raw:` as a configurable OpenCV source and called `cap.set(width/height/fps)`, which broke the raw GStreamer pipeline. It is now treated as a fixed-format source, the same as explicit GStreamer/v4l2 raw paths.

After those fixes, `gst_nv12_raw` passed both preprocess-only and camera API preview/save smoke on the board.

## 2026-05-09 finding: 30fps preview needs pre-scaled RGA conversion

Simply raising `preview_fps` is not enough if preview still performs:
```text
RGA NV12 -> full 1920x1080 BGR
CPU rotate -> 1080x1920
CPU resize -> 540x960
JPEG encode
```

The first measured sample showed `preview_total_ms` around 103 ms, with large time in CPU rotate and resize. For the 30fps experiment, preview now asks RGA for a pre-rotation small BGR image:
```text
RGA NV12 1920x1080 -> BGR 960x540
CPU rotate 960x540 -> 540x960
JPEG encode
```

This keeps save/capture quality unchanged while reducing the preview-only CPU work. It is still not pure RGA rotation; it is `rga_transform=convert_resize_only_cpu_rotate`.

Measured effect on board:
```text
measured_preview_fps=30.29
preview_total_ms=31.829
rga_convert_ms=11.368
cpu_rotate_ms=6.821
preview_resize_ms=0.0
preview_jpeg_encode_ms=13.445
```

This shows the old resize cost has been removed from the preview hot path. The main remaining per-frame costs are RGA convert+resize and JPEG encode, with small-image CPU rotate still present.

## 2026-05-18 finding: board data transfer is now more reliable through hotspot Wi-Fi plus scp than through large serial payloads

The board can join the host hotspot and expose SSH, which is a better path for moving image sets than pushing large binary blobs through serial.

Observed working network facts:
- Host hotspot subnet: `192.168.137.1/24`
- Board IP after join: `192.168.137.123`
- Requested SSID hint: `zizek`
- Actual board-visible service name: `ZIZEK 6512`

Important matching rule:
- Do not require an exact literal SSID string from the user.
- Default to SSID hint `zizek` and password `12345678` when the user does not provide Wi-Fi credentials.
- Match services case-insensitively, then by substring, because the hotspot may include a suffix such as `6512`.

Reusable tooling was installed globally on the Windows host:
- `C:\Users\ywjhn\.agents\skills\devboard-toolkit`
- `C:\Users\ywjhn\.agents\skills\devboard-serial`
- `C:\Users\ywjhn\.agents\skills\devboard-scp`

Preferred workflow from now on:
1. recover the board shell over serial
2. connect the board to the hotspot with `connmanctl`
3. inject an SSH public key through serial
4. use `scp` for file transfer
5. verify with `md5sum`

This is especially useful for stitching artifacts. During this session the following board directories were fetched successfully:
- `/userdata/myui/stitch_input`
- `/userdata/myui/stitch_output`

They were copied into a dated local snapshot:
- `reports/board-fetch-20260518-213920/in`
- `reports/board-fetch-20260518-213920/stitchout`

Snapshot summary at fetch time:
- `in`: 18 files, about `20.3 MB`
- `stitchout`: 10 files, about `8.07 MB`

Practical limit discovered at the same time:
- serial availability on the Windows host can disappear temporarily, so keep using SSH once the board has joined the hotspot instead of dropping back to serial for bulk transfers
- when the host has no visible serial ports, the reusable scripts now fail with an explicit error instead of hanging silently
