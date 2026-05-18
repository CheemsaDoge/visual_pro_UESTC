# native/rga

最小 RK3588 RGA wrapper，用于让 Python `RgaPreprocessEngine` 通过 `ctypes` 调用真实 librga/im2d，而不是在 Python 里硬写复杂 RGA 结构。

## 当前接口

导出 C ABI：

```c
int myui_rga_available(void);
int myui_rga_nv12_to_bgr(
    const unsigned char *src_nv12,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
);
const char *myui_rga_last_error(void);
const char *myui_rga_version(void);
```

`rotate_code`：

- `0` = none
- `1` = ccw90
- `2` = cw90
- `3` = 180

第一版实现目标是 virtual-address 路径的 `NV12 -> BGR`，并在 im2d 支持时通过中间 BGR buffer 做 resize 或 rotate。当前没有做 DMA-BUF/零拷贝。

## 编译

在目标板或带 librga 开发头文件的 aarch64 toolchain 环境执行：

```bash
cd /userdata/myui/native/rga
make probe
make
ls -l libmyui_rga.so
make test-load
```

如果板端缺 `g++` 或 `im2d.h`，`make` 会明确失败，例如：

```text
error: C++ compiler 'g++' not found
error: im2d.h not found; install/copy Rockchip librga development headers
```

这不是 CPU 假实现；缺开发资源时 Python 会保持 `rga_fallback_cpu`。

### 交叉编译入口

`Makefile` 支持通过环境变量指定交叉编译资源：

```bash
make \
  CXX=aarch64-buildroot-linux-gnu-g++ \
  SYSROOT=/path/to/aarch64/sysroot \
  RGA_INCLUDE_DIR=/path/to/librga/include \
  RGA_LIB_DIR=/path/to/librga/lib
```

变量含义：

- `CXX`：aarch64 C++ 编译器，例如 Buildroot SDK 里的 `aarch64-buildroot-linux-gnu-g++`。
- `SYSROOT`：目标根文件系统或 SDK sysroot。为空时使用编译器默认 sysroot。
- `RGA_INCLUDE_DIR`：包含 `im2d.h` 及其依赖头文件的目录。若头文件已经在 sysroot 标准 include 路径中，可留空。
- `RGA_LIB_DIR`：包含目标板 ABI 版本 `librga.so` 的目录。若库已经在 sysroot 标准 lib 路径中，可留空。

最小编译前提：

- 能运行的 aarch64 GNU/Buildroot C++ 编译器。
- Rockchip librga development headers，至少需要 `im2d.h` 及其依赖头文件。
- 与目标板兼容的 aarch64 `librga.so` 或含该库的 sysroot。

常见失败原因：

- `error: C++ compiler '...' not found`：`CXX` 没指向可执行交叉编译器。
- `error: im2d.h not found`：`SYSROOT` 或 `RGA_INCLUDE_DIR` 没有 librga 开发头文件。
- 链接阶段 `cannot find -lrga`：`SYSROOT` 或 `RGA_LIB_DIR` 没有目标 ABI 的 `librga.so`。
- 产物不是 aarch64：误用了 PC 端 x86_64 编译器，需重新设置 `CXX`。

本轮查找和验证结果：

- 2026-05-08：本机普通目录未发现交叉编译资源。
- 2026-05-09：用户提供的 `..\01linux_sdk\atk-rk3588_linux_release_v1.2_20250104.tgz` 中确认存在：
  - `linux/linux-rga`，manifest 路径为 `external/linux-rga`。
  - RGA headers：`im2d_api/im2d.h`、`include/RgaApi.h`、`include/rga.h`、`include/RgaUtils.h`。
  - Rockchip prebuilt toolchain repo：`gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu`，包含 `bin/aarch64-none-linux-gnu-g++`。
- 该 gcc 工具链是 Linux x86_64 ELF，Windows 不能直接运行；本轮用 Windows clang 16 的 `--target=aarch64-linux-gnu` 生成了最小 AArch64 ELF shared object。
- 产物 `native/rga/libmyui_rga.so` 已同步到 `/userdata/myui/native/rga/`，md5 为 `353e928594515b524c8a21dc569f3496`。
- 板端 `make test-load` 通过：`myui_rga_available= 1`。
- 固定 320x240 NV12 样例通过：`ret=0`、`last_error=ok`。
- benchmark 已进入 `rga_active`：`rga_wrapper_available=True`、`rga_active_calls=2`、`rga_fallback_calls=0`。

本轮 Windows clang 构建命令：

```powershell
clang++.exe --target=aarch64-linux-gnu `
  --sysroot="D:\...\GUI\.tmp\toolchain_sysroot\aarch64-none-linux-gnu\libc" `
  -I"D:\...\GUI\.tmp\linux_rga_checkout\im2d_api" `
  -I"D:\...\GUI\.tmp\linux_rga_checkout\include" `
  -I"D:\...\GUI\.tmp\linux_rga_checkout\core\3rdparty\libdrm\include" `
  -O2 -Wall -Wextra -fPIC -c native\rga\myui_rga.cpp -o .tmp\myui_rga.o

clang++.exe --target=aarch64-linux-gnu -fuse-ld=lld `
  -nostdlib -shared .tmp\myui_rga.o `
  "-Wl,-soname,libmyui_rga.so" `
  "-Wl,--allow-shlib-undefined" `
  -o native\rga\libmyui_rga.so
```

这个产物依赖 Python 侧先用 `RTLD_GLOBAL` 加载板端真实 `librga.so`，再加载 `libmyui_rga.so`。

## Python 接入

`app/preprocess/rga_engine.py` 会按以下顺序寻找 wrapper：

1. 环境变量 `MYUI_RGA_LIB`
2. `native/rga/libmyui_rga.so`
3. `/userdata/myui/native/rga/libmyui_rga.so`
4. `/usr/local/lib/libmyui_rga.so`
5. `/usr/lib/libmyui_rga.so`
6. `/lib/libmyui_rga.so`

wrapper 加载成功且 `FramePacket(pixel_format="NV12")` 处理成功时，输出 metadata/status 为 `rga_active`。wrapper 不存在、不可用、输入不是 NV12 或单帧调用失败时自动回 CPU，输出 `rga_fallback_cpu` 和原因。

## 2026-05-09 rotate diagnostics

`myui_rga/1.2 rotate-diagnostics` adds native helpers used by `tests/smoke/test_rga_rotate_matrix_smoke.py`:

```c
int myui_rga_bgr_rotate(...);
int myui_rga_bgr_rotate_strided(...);
int myui_rga_bgrx_rotate_to_bgr(...);
```

Board result for the current RK3588 librga runtime:

```text
1920x1080 -> 1080x1920 compact BGR888 dst stride=1080:
  fails with IM_STATUS_NOT_SUPPORTED
  reason: bgr888 width stride should be 16 aligned

1920x1080 -> 1080x1920 padded BGR888 dst stride=1088:
  ok
```

This means 1920x1080 90/270-degree rotation can be performed by RGA only if the destination BGR888 buffer uses a 16-aligned padded stride. The current Python/OpenCV path expects compact BGR arrays, so production still uses RGA for `NV12 -> BGR` and CPU for post-rotate, explicitly marked as `rga_transform=convert_only_cpu_rotate`.

## 最小 Python 加载验证

```bash
python3 - <<'PY'
import ctypes
lib = ctypes.CDLL('/userdata/myui/native/rga/libmyui_rga.so')
lib.myui_rga_available.restype = ctypes.c_int
print('available=', lib.myui_rga_available())
PY
```

## Benchmark 验证

默认 smoke 测试允许 fallback，用于确认链路不会崩：

```bash
PYTHONPYCACHEPREFIX=/tmp/myui_pycache python3 tests/benchmark/run_benchmark.py \
  --preprocess rga \
  --selector off \
  --feed-format nv12 \
  --frames 2 \
  --skip-stitch \
  --output-json /tmp/benchmark_rga.json
```

wrapper 编译成功后，用 `--require-rga` 防止把 CPU fallback 误判成 RGA：

```bash
PYTHONPYCACHEPREFIX=/tmp/myui_pycache python3 tests/benchmark/run_benchmark.py \
  --preprocess rga \
  --selector off \
  --feed-format nv12 \
  --frames 2 \
  --skip-stitch \
  --require-rga \
  --output-json /tmp/benchmark_rga.json
```

如果 wrapper 放在非默认位置，可以加 `--rga-lib /path/to/libmyui_rga.so` 或设置 `MYUI_RGA_LIB`。

## 当前 RK3588 探测结果（2026-05-08）

通过 COM3 串口在 ATK-DLRK3588 上探测：

- `/dev/rga` 存在：`crw-rw---- root video 10,120 /dev/rga`
- `librga.so` 存在：`/lib/librga.so -> librga.so.2 -> librga.so.2.1.0`，`/usr/lib/librga.so` 同样存在
- `ctypes.CDLL('librga.so')` 可加载，且能看到 `c_RkRgaInit`、`c_RkRgaBlit`、`improcess`
- 未找到 `im2d.h` / `RgaApi.h` / `rga.h`
- 未找到 `cc` / `gcc` / `g++`

因此当前板端具备运行时 RGA 设备与库，但缺少本地编译 wrapper 所需的开发资源。下一步需要补齐 Rockchip librga development headers 和 aarch64 编译器，或在外部 Buildroot/aarch64 sysroot 中交叉编译后部署 `libmyui_rga.so`。
