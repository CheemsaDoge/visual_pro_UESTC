# 03 配置与运行

## 启动

```bash
python3 backend.py
```

默认访问：`http://127.0.0.1:18080`

环境变量覆盖（`app/config.py` 读取）：

```bash
MYUI_CONFIG=/path/to/config.json python3 backend.py   # 换配置文件
MYUI_BASE_DIR=/userdata/myui python3 backend.py       # 换部署根目录
MYUI_PORT=18180 python3 backend.py                    # 换端口
MYUI_RGA_LIB=/path/libmyui_rga.so python3 backend.py  # 指定 RGA wrapper
```

`BASE_DIR` 的默认推导规则：存在 `/userdata/myui` 时用它，否则用仓库目录。`app/config.py` 末尾会 `os.chdir(BASE_DIR)`，所以静态文件相对路径从部署目录解析。

## 快速检查

```bash
python3 -m py_compile backend.py stitch_demo.py $(find app tests -name '*.py')
python3 -m unittest discover tests
curl http://127.0.0.1:18080/api/status
curl http://127.0.0.1:18080/api/config/public
curl http://127.0.0.1:18080/api/stitch/logs
```

`make py-check` 只编译相机/预处理相关子集，不等于全仓库检查，需要全量时用上面的 `py_compile` 命令。

当前 `tests/` 共 12 个测试用例：`tests/unit/test_opencl_geometry.py` 4 条、`tests/unit/test_preprocess.py` 2 条、`tests/unit/test_selector.py` 1 条、`tests/unit/test_stitch_engine.py` 4 条、`tests/integration/test_preprocess_selector_stitch.py` 1 条。除 `test_opencl_geometry.py` 外都需要 `cv2`，没装 OpenCV 的环境会在导入阶段报 `ModuleNotFoundError: No module named 'cv2'`，不是代码缺陷。`app/services/stitch_diagnostics.py` 与引擎分阶段记录目前没有测试覆盖。

## 拼接诊断日志

无需配置，默认开启。每次 `/api/stitch/image` 或相机 stop 触发的拼接都会生成一份报告：

```bash
curl http://127.0.0.1:18080/api/stitch/logs             # 最近 30 条
curl 'http://127.0.0.1:18080/api/stitch/logs?limit=5'   # 限制条数（夹在 1..30）
curl 'http://127.0.0.1:18080/api/stitch/logs?id=<log_id>'  # 单条，未命中返回 404
```

浏览器入口是 `stitch_log.html`（首页第 5 张卡片、`stitch.html` 顶栏「日志」、结果区「本次日志」都能进）。

关键特性与限制：

- 报告存在进程内 `deque(maxlen=30)`，**不落盘，后端重启即清空**。要留档就自己保存响应里的 `stitch_log`。
- 报告里的 `resources` 依赖 Linux `/proc` 与 `/sys`；Windows 上 CPU 百分比为 `null`，内存/温度/GPU 为空。
- GPU 字段来自 `metrics_service.read_gpu()`，扫描 `/sys/class/devfreq/*` 里名字或 `device/uevent` 含 `gpu`/`mali` 的节点，读 `cur_freq`/`max_freq`/`min_freq`/`load`/`busy_time`/`total_time`。内核没暴露就返回 `{"devices": [], "available": false}`，不是“GPU 没被使用”的证据。
- 诊断会对每张输入图和输出图各做一次 `cv2.imread()` 以获取尺寸，这部分开销会计入 `total_elapsed_ms`。
- 字段清单见 `docs/04_api_compatibility.md` 的「拼接诊断日志」一节。

## 当前 config.json 真实默认值

仓库内 `config.json` 当前生效的关键项：

```json
{
  "system": { "port": 18080, "log_file": "./backend.log", "switch_script": "./switch_to_systemui.sh" },
  "ui": { "font_size": "medium" },
  "stitch": {
    "engine": "sequential",
    "script_path": "./stitch_demo.py",
    "work_dir": "./_stitch_work",
    "input_dir": "./stitch_input",
    "output_dir": "./stitch_output",
    "max_image_bytes": 15728640,
    "camera": {
      "backend": "auto",
      "capture_backend": "auto_raw",
      "source": "/dev/video-camera0",
      "pixel_format": "NV12",
      "rotation": "ccw90",
      "frame_width": 1920,
      "frame_height": 1080,
      "fps": 30,
      "preview_max_dim": 960,
      "preview_jpeg_quality": 70,
      "preview_fps": 30,
      "auto_interval_sec": 0.5,
      "jpeg_quality": 88
    }
  },
  "accel": { "preprocess": "rga", "geometry": "opencl", "selector": "off" },
  "selector": { "cpu_basic": { "min_interval_sec": 0.5, "blur_threshold": 60.0, "diff_threshold": 3.0, "diff_resize_width": 320 } }
}
```

注意 `app/config.py` 的 `DEFAULT_CONFIG` 与 `config.json` 并不完全一致，缺字段时才用内置默认：

| 项 | `config.json` | `DEFAULT_CONFIG` |
| --- | --- | --- |
| `stitch.engine` | `sequential` | `builtin` |
| `accel.geometry` | `opencl` | `cpu` |
| `accel.preprocess` | `rga` | `rga` |

另外 `normalize_choice()` 的兜底值又是另一层：`accel.preprocess`/`accel.geometry` 非法时回落到 `cpu`，`accel.selector` 非法时回落到 `off`，`stitch.engine` 非法时回落到 `builtin`。

## 切换拼接引擎

```json
"stitch": { "engine": "sequential" }
```

允许值与别名（`app/config.py:STITCH_ENGINE`）：

- `builtin`：`OpenCVStitchEngine`，OpenCV `PANORAMA` 模式；输入先做 `bilateralFilter`，成功后做 USM + `fastNlMeansDenoisingColored` 后处理；正序失败会再试一次反序；恰好两张图时会回退到 `common.stitch_two_images_with_orb()`。
- `sequential`：`SequentialPanoEngine`，按输入顺序两两 ORB 拼接；整条序列失败时自动回退到 `OpenCVStitchEngine`。
- `scans`：`ScansStitchEngine`，OpenCV `SCANS` 模式，带 Laplacian 质量过滤（阈值 80.0）、`setRegistrationResol(0.6)`、线程池并行读图和 `smart_crop`。
- `script`：调用 `stitch.script_path`（默认 `./stitch_demo.py`），超时 `stitch.script_timeout_sec`，参数形如 `--output <path> --auto-crop|--no-auto-crop <images...>`。
- 别名：`opencv`/`cv2`/`opencvstitch` → `builtin`，`scan`/`opencvscans` → `scans`。

`common.DEFAULT_MAX_IMAGE_WIDTH = 1920`，`builtin` 与 `sequential` 默认把超宽输入缩到 1920；`scans` 的 `max_image_width` 默认 0，即不缩放。

## 切换预处理引擎

```json
"accel": { "preprocess": "cpu" }   // CPU baseline
"accel": { "preprocess": "rga" }   // 请求 RGA
```

`RgaPreprocessEngine` 的 `mode_tag` 有三种真实取值：

- `rga_ready`：wrapper 已加载但还没处理过 NV12 帧。
- `rga_active`：真实 native 调用成功。
- `rga_fallback_cpu`：wrapper 缺失、加载失败、输入不是 NV12，或单帧 native 调用失败。

wrapper 查找顺序（`_candidate_lib_paths_static()`）：`MYUI_RGA_LIB` → `<BASE_DIR>/native/rga/libmyui_rga.so` → `<cwd>/native/rga/libmyui_rga.so` → `/userdata/myui/native/rga/libmyui_rga.so` → `/usr/local/lib/libmyui_rga.so` → `/usr/lib/libmyui_rga.so` → `/lib/libmyui_rga.so`。

1920x1080 且 `rotation` 为 `ccw90`/`cw90` 时，RGA 只完成 `NV12 -> BGR`（预览路径还顺带缩放），90° 旋转由 CPU 补做，状态里会看到：

```text
rga_transform=convert_only_cpu_rotate          # save 路径
rga_transform=convert_resize_only_cpu_rotate   # preview 预缩放路径
post_rotate_cpu=True
```

## 切换几何引擎

```json
"accel": { "geometry": "opencl" }
```

`OpenCLGeometryEngine` 通过 `app/geometry/opencl_runtime.py` 的 `ctypes -> libOpenCL.so` 工作，不依赖 `cv2.ocl`/UMat：

- runtime 可用：`actual=opencl`、`mode_tag=geometry_opencl_direct`。
- runtime 不可用：`actual=cpu`、`mode_tag=opencl_fallback_cpu`。
- `warp_perspective()` 走 direct OpenCL，异常时逐次 fallback 并累加 `fallback_calls`。
- `remap()` 没有 OpenCL 实现，每次调用都 `remap_fallback_calls += 1` 并转给 CPU。

覆盖范围限制：几何层目前只在 `common.stitch_two_images_with_orb()` 这条 ORB 路径被直接调用，也就是 `builtin` 的两图 fallback 和 `sequential` 的每一步两两拼接。主 `cv2.Stitcher` 成功时不经过 `GeometryEngine`；`ScansStitchEngine` 完全不接几何引擎。

## 切换关键帧筛选

```json
"accel": { "selector": "off" }        // 关闭
"accel": { "selector": "cpu_basic" }  // CPU basic
"accel": { "selector": "rknn" }       // 当前等于 cpu_basic + 标记
```

`cpu_basic`（`CpuSelector`）的判断顺序和阈值来源：

1. 距上一保留帧间隔 < `min_interval_sec` → `reason=interval`
2. Laplacian 方差 < `blur_threshold` → `reason=blur`
3. 与上一保留帧灰度均值差 < `diff_threshold` → `reason=duplicate`
4. 否则 `keep=true`，`reason` 为 `first` 或 `keep`

`min_interval_sec` 缺省时继承 `stitch.camera.auto_interval_sec`。`rknn` 目前是 `RknnSelector`，内部直接委托 `CpuSelector`，`mode_tag=rknn_fallback_cpu_basic`，`available=false`。

别名：`cpu`/`basic` → `cpu_basic`，`rknn_selector` → `rknn`。

## benchmark

```bash
python3 tests/benchmark/run_benchmark.py --preprocess cpu --selector off
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector cpu_basic
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --output-json /tmp/benchmark_rga.json
```

可用参数：`--input-dir`、`--output-json`、`--frames`、`--preprocess {cpu,rga}`、`--rga-lib`、`--require-rga`、`--feed-format {auto,bgr,nv12}`、`--geometry {cpu,opencl}`、`--selector {off,cpu_basic}`、`--stitch-engine {opencv,sequential}`、`--auto-crop`、`--skip-stitch`。

`--feed-format auto` 的实际含义是：`--preprocess rga` 时用 `nv12`，否则用 `bgr`。synthetic 输入固定生成 320x240 的裁切帧，这是为了避开 RGA virtual-address 路径对尺寸对齐的敏感性。

报告默认写入 `reports/benchmark_YYYYmmdd_HHMMSS.json`；`.gitignore` 已忽略 `reports/*`（仓库当前没有 `reports/` 目录，首次运行会自动创建）。

退出码：`--require-rga` 且 `--preprocess rga` 但实际 `preprocess_actual != "rga"` → `3`；`stitch_ok` 为假 → `2`；正常 → `0`。注意 `--skip-stitch` 会直接把 `stitch_ok` 置为真。

验证真实 RGA 时使用强制模式：

```bash
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --require-rga --output-json /tmp/benchmark_rga_require.json
```

## smoke 脚本

`tests/smoke/` 下四个脚本都是板端硬件相关，PC 上不适用：

```bash
python3 tests/smoke/test_v4l2_nv12_rga_smoke.py --frames 1 --require-rga
python3 tests/smoke/test_gst_nv12_rga_smoke.py --frames 3 --require-rga
python3 tests/smoke/test_camera_api_rga_smoke.py --capture-backend gst_nv12_raw --require-rga --captures 2
python3 tests/smoke/test_rga_rotate_matrix_smoke.py
```

对应的 Makefile 目标：`py-check`、`test-camera-nv12`、`smoke-camera-rga`、`smoke-camera-api-rga`、`smoke-rga-rotate-matrix`。
