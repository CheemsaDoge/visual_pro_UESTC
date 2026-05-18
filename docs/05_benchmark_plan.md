# 05 Benchmark 计划

## 要测什么

当前 benchmark 初版覆盖：

- 单帧预处理耗时
- 平均预处理耗时
- 拼接总耗时
- CPU 占用
- 内存占用
- 输入帧数
- 保留帧数
- 拼接成功/失败
- 当前模式标识

## 为什么测

项目路线是 RGA first → GPU next → NPU later。必须在每个阶段能回答：

- 配置请求了哪个引擎？
- 实际用了哪个引擎？
- 是否 fallback？
- 单步耗时和端到端耗时是否改善？
- 如果生产验证要求必须走 RGA，是否能在 fallback 时让命令失败？

## 指标定义

- `single_frame_preprocess_ms`：第一帧 `process_for_save()` 耗时。
- `avg_preprocess_ms`：全部输入帧预处理平均耗时。
- `stitch_total_ms`：调用 `StitchEngine.stitch()` 的总耗时。
- `cpu_percent`：通过 `/proc/stat` 前后快照估算的全系统 CPU 使用率。
- `memory`：来自 `/proc/meminfo` 的内存摘要。
- `process_memory`：来自 `/proc/<pid>/status` 的当前进程内存字段。
- `thermal`：若存在 `/sys/class/thermal/thermal_zone*`，记录温区温度。
- `preprocess_actual`：实际使用的预处理引擎，例如 `cpu` 或 `rga`。
- `preprocess_reason`：fallback 或当前状态原因。
- `rga_wrapper_available`：是否加载到 `libmyui_rga.so` 且 `myui_rga_available()` 成功。
- `rga_active_calls`：本次 benchmark 中真实 RGA 成功调用次数。
- `rga_fallback_calls`：本次 benchmark 中回退 CPU 的调用次数。

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

当前没有 `libmyui_rga.so` 时，`--require-rga` 应返回退出码 `3`。wrapper 真实可用后，目标输出应为 `preprocess_actual=rga`、`rga_active_calls>0`、`rga_fallback_calls=0`。

报告会明确显示：

- `cpu_base`
- `rga_fallback_cpu`
- `rga_active`
- `selector_off`
- `selector_cpu_basic`
- `opencl_fallback_cpu`
