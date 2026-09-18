# 05 Benchmark 计划

## 要测什么

`tests/benchmark/run_benchmark.py` 当前实际写入报告的内容：

- 单帧预处理耗时、逐帧耗时列表、平均预处理耗时
- 拼接总耗时、整轮总耗时
- CPU 占用（`/proc/stat` 前后差值）
- 内存摘要（`/proc/meminfo`）与当前进程内存（`/proc/<pid>/status`）
- 温度（`/sys/class/thermal/thermal_zone*`）
- 输入帧数、保留帧数、每帧 selector 决策
- 拼接成功/失败与原因
- requested 与 actual 的引擎对照，以及各引擎完整 `status()`

## 为什么测

项目路线是 RGA first → GPU next → NPU later。必须在每个阶段能回答：

- 配置请求了哪个引擎？
- 实际用了哪个引擎？
- 是否 fallback？
- 单步耗时和端到端耗时是否改善？
- 如果生产验证要求必须走 RGA，是否能在 fallback 时让命令失败？

## 指标定义

报告顶层字段与含义：

- `mode`：`<preprocess mode_tag>+<selector mode_tag>`，例如 `rga_active+selector_off`。
- `preprocess_mode` / `preprocess_actual` / `preprocess_reason`：预处理引擎 `status()` 中的 `mode_tag` / `actual` / `reason`。
- `geometry_mode`：几何引擎 `mode_tag`，例如 `geometry_opencl_direct` 或 `opencl_fallback_cpu`。
- `selector_mode`：`selector_off` / `selector_cpu_basic` / `rknn_fallback_cpu_basic`。
- `stitch_mode`：拼接引擎 `mode_tag`，例如 `opencv_panorama_enhanced`、`sequential_pairwise_orb`、`opencv_scans_enhanced`。
- `single_frame_preprocess_ms`：第一帧 `process_for_save()` 耗时。
- `preprocess_times_ms` / `avg_preprocess_ms`：全部输入帧的逐帧与平均预处理耗时。
- `stitch_total_ms`：调用 `StitchEngine.stitch()` 的总耗时；`--skip-stitch` 时为 `0.0`。
- `total_elapsed_ms`：从快照开始到结束的整轮耗时。
- `cpu_percent`：`metrics_service.cpu_percent_between()` 基于 `/proc/stat` 估算的全系统 CPU 使用率；非 Linux 上为 `null`。
- `memory` / `process_memory` / `thermal`：分别来自 `/proc/meminfo`、`/proc/<pid>/status`（`VmRSS`/`VmHWM`/`VmSize`/`Threads`）、thermal zone。`snapshot()` 现在还会额外采集 `gpu`（devfreq/sysfs），但 benchmark 报告目前只把它放进 `snapshots.before/after`，没有单独的顶层 GPU 字段。
- `rga_wrapper_available`：是否加载到 `libmyui_rga.so` 且 `myui_rga_available()` 成功。
- `rga_active_calls` / `rga_fallback_calls`：本轮真实 RGA 成功次数与回退 CPU 次数。
- `rga`：嵌套块，额外含 `require_rga`、`lib_path`、`lib_version`、`load_error`。
- `requested` / `actual`：请求与实际生效的 preprocess / geometry / selector / stitch_engine，`requested` 还带 `feed_format`。
- `selector_decisions`：逐帧决策字典，含 `keep`、`reason` 及触发阈值。
- `snapshots.before` / `snapshots.after`：完整的 `metrics_service.snapshot()` 原始数据。

## 当前支持

入口：

```bash
python3 tests/benchmark/run_benchmark.py
```

常用模式：

```bash
python3 tests/benchmark/run_benchmark.py --preprocess cpu --selector off
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector cpu_basic
python3 tests/benchmark/run_benchmark.py --geometry opencl
python3 tests/benchmark/run_benchmark.py --preprocess rga --selector off --feed-format nv12 --skip-stitch
```

注意几何引擎当前只在 ORB 路径生效，所以 `--geometry opencl` 需要配合 `--stitch-engine sequential`，或使用只有两张图的输入让 `opencv` 引擎走 ORB fallback，否则 `cv2.Stitcher` 成功时不会经过 `GeometryEngine`。

生产验证 RGA 时必须使用强制模式，避免把 CPU fallback 看成成功：

```bash
python3 tests/benchmark/run_benchmark.py \
  --preprocess rga \
  --selector off \
  --feed-format nv12 \
  --skip-stitch \
  --require-rga \
  --output-json /tmp/benchmark_rga_require.json
```

## 退出码

`run_benchmark.py:run()` 的真实返回值：

| 条件 | 退出码 |
| --- | --- |
| `--require-rga` + `--preprocess rga`，但 `preprocess_actual != "rga"` | 3 |
| `stitch_ok` 为假 | 2 |
| 其余 | 0 |

`--skip-stitch` 会无条件把 `stitch_ok` 置为 `True`，因此在 skip 模式下 `2` 不会出现。

## 输入数据

- `--input-dir` 为空，或目录内可用图片少于 2 张时，自动生成 synthetic 帧。
- synthetic 帧固定为 320x240 裁切窗口，在 `320 + 160*(n-1)` 宽的画布上按 160 像素步长横向滑动，保证相邻帧有重叠。
- 尺寸选 320x240 是为了避开 RGA virtual-address 路径对非对齐尺寸返回 `im2d_status=-1` 的问题，不要随意改回 300x220 这类尺寸。
- `--feed-format nv12` 时通过 `bgr_to_nv12()` 把 BGR 转成 `(h*3/2, w)` 的 NV12 ndarray，再构造 `FramePacket(pixel_format="NV12")`。

## 报告中会出现的模式标识

- 预处理：`cpu_base`、`rga_ready`、`rga_active`、`rga_fallback_cpu`
- 几何：`geometry_cpu`、`geometry_opencl_direct`、`opencl_fallback_cpu`
- 选择器：`selector_off`、`selector_cpu_basic`、`rknn_fallback_cpu_basic`
- 拼接：`opencv_panorama_enhanced`、`sequential_pairwise_orb`、`opencv_scans_enhanced`

## 已知局限

- `metrics_service` 全部依赖 Linux `/proc`、`/sys`，Windows 上 `cpu_percent` 为 `null`、`memory`/`thermal`/`gpu` 为空或带 `error` 字段。
- benchmark 直接 new 引擎实例，不经过 `app/services/*` 单例工厂，因此它反映的是命令行参数而不是 `config.json` 当前生效的 service 状态。
- benchmark 不经过 `run_image_stitch()`，所以**不会**产生 `/api/stitch/logs` 里的诊断报告。想看分阶段耗时与 ORB 特征数据，要走 HTTP 拼接接口再看日志页；两者的数据口径不同，不要混用。
- `--stitch-engine sequential` 在 benchmark 里构造为 `SequentialPanoEngine(opencv)`，即把 `OpenCVStitchEngine` 作为第一个位置参数（`geometry_engine`）传入，与 `stitch_service.create_stitch_engine()` 的关键字装配方式不同；解读 sequential 的 benchmark 结果时要注意这一差异。
- benchmark 初版用于结构化记录，不代表最终性能结论。
