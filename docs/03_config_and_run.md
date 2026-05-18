# 03 配置与运行

## 启动

```bash
python3 backend.py
```

默认访问：`http://127.0.0.1:18080`

使用备用配置：

```bash
MYUI_CONFIG=/path/to/config.json python3 backend.py
```

## 快速检查

```bash
python3 -m py_compile backend.py stitch_demo.py $(find app tests -name '*.py')
python3 -m unittest discover tests
curl http://127.0.0.1:18080/api/status
curl http://127.0.0.1:18080/api/config/public
```

## 新增配置

`config.json` 保留旧配置，同时新增：

```json
{
  "accel": {
    "preprocess": "cpu",
    "geometry": "cpu",
    "selector": "off"
  },
  "selector": {
    "cpu_basic": {
      "min_interval_sec": 0.5,
      "blur_threshold": 60.0,
      "diff_threshold": 3.0,
      "diff_resize_width": 320
    }
  }
}
```

## 切换拼接引擎

```json
"stitch": { "engine": "builtin" }
```

- `builtin`：增强后的 OpenCV `PANORAMA` 模式，默认启用双边滤波预处理、后处理，以及双图 ORB 回退。
- `sequential`：按输入顺序做两两 ORB 拼接；主路径失败时自动回退到 `builtin`。
- `scans`：增强后的 OpenCV `SCANS` 模式，带图像质量过滤、`registration_resol=0.6` 和后处理。
- `script`：继续调用 `stitch.script_path` 指定的外部脚本。

## 切换预处理引擎

CPU baseline：

```json
"accel": { "preprocess": "cpu" }
```

请求 RGA：

```json
"accel": { "preprocess": "rga" }
```

当前若没有真实 RGA Python binding，会自动回退 CPU，并在状态/日志/benchmark 中显示 `rga_fallback_cpu`。

## 切换几何引擎

```json
"accel": { "geometry": "opencl" }
```

当前配置 `opencl` 只表示“请求 OpenCLGeometryEngine”。

截至 2026-05-13 的板端实测结论是：

- 原生 `libOpenCL.so` 已能枚举 `ARM Platform / Mali-G610 r0p0`
- 可通过 direct OpenCL 真实完成 `build program + launch kernel + read back`
- 但 OpenCV 4.5.4 仍报告 `cv2.ocl.haveOpenCL() == False`
- 当前项目里只有 `warpPerspective` 接到了 direct OpenCL；`remap` 仍回退 CPU

当前限制也要看清楚：

- 这条 direct OpenCL 几何路径目前只覆盖 `OpenCLGeometryEngine.warp_perspective()`。
- 当前几何层只在 `OpenCVStitchEngine` 的 ORB fallback 路径里被直接调用。
- 如果主 `cv2.Stitcher` 直接拼接成功，它不会自动经过这条 OpenCL 几何路径。

因此，`geometry=opencl` 现在已经不再只是空占位；但也不能把它理解成“整个拼接流程已经全面走 GPU”。

## 切换关键帧筛选

关闭筛选：

```json
"accel": { "selector": "off" }
```

启用 CPU basic：

```json
"accel": { "selector": "cpu_basic" }
```

`cpu_basic` 当前依据：

- 距上一保留帧时间间隔
- Laplacian 清晰度分数
- 与上一保留帧的灰度均值差异

## benchmark

```bash
python3 tests/benchmark/run_benchmark.py --preprocess cpu --selector off
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector cpu_basic
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --output-json /tmp/benchmark_rga.json
```

报告默认写入 `reports/benchmark_YYYYmmdd_HHMMSS.json`，该目录的生成 JSON 已被 `.gitignore` 忽略。

验证真实 RGA 时使用强制模式：

```bash
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch --require-rga --output-json /tmp/benchmark_rga_require.json
```

当前没有 `libmyui_rga.so` 时该命令应返回退出码 `3`；wrapper 成功后应输出 `preprocess_actual=rga` 且 `rga_active_calls>0`。
