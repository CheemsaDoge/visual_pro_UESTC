# Windows 本地运行

这份指南用于 Windows 上测试页面、静态图片拼接和 partial panorama 展示。它不替代 RK3588 开发板运行。

## 一键启动

在项目目录中执行：

```powershell
conda activate cv_projectforfreshman
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
```

脚本会：

1. 使用当前激活环境中的 `python`（`Get-Command python`，找不到就直接报错）；
2. 按 `requirements.txt` 检查或安装依赖（当前只有 `numpy>=1.24,<3` 和 `opencv-python>=4.8,<5`）；
3. 再显式 `import cv2, numpy` 验证一次并打印版本；
4. 检查端口 `18080` 未被监听；
5. 启动后台 Job 轮询 `/api/status`（最多 40 次、每次间隔 250ms），成功后打开浏览器；
6. 前台启动 `backend.py`，日志留在当前终端。

按 `Ctrl+C` 停止服务。可用参数：

```powershell
.\start_windows.ps1 -SkipInstall   # 跳过 pip 安装
.\start_windows.ps1 -NoBrowser     # 不自动打开浏览器
```

## 为什么此前会失败

Linux 开发板上的 Wi-Fi 页面使用 `pty` 和 `termios` 驱动 `connmanctl` 的交互式密码输入。Windows 没有这两个 POSIX 模块，所以原先在导入 `wifi_routes.py` 时就终止了整个后端。

现在 `wifi_routes.py` 在 Windows 会跳过 `pty`，后端可以正常启动；Wi-Fi 页面会明确提示“仅 Linux 开发板可用”，不会尝试在 Windows 调用 ConnMan。

## 本地可用与不可用功能

| 本地 Windows 可测试 | 需要 RK3588 开发板 |
| --- | --- |
| 页面、接口、静态图片拼接、输出图、Pannellum 全景展示 | CSI 摄像头、`/dev/video*`、NV12、RGA、OpenCL、V4L2/GStreamer、ConnMan Wi-Fi、Chromium kiosk |

本地拼接图片请放进 `stitch_input/`，从首页进入“图片拼接”。相机模式是开发板硬件功能；Windows 上不应把相机启动失败当作 Python 环境问题。

## Windows 上各引擎的实际表现

即使 `config.json` 写着 `accel.preprocess=rga`、`accel.geometry=opencl`，Windows 上也会自动降级，这是预期行为：

- `RgaPreprocessEngine`：`_probe_rga()` 找不到 `/dev/rga*`，`mode_tag` 落到 `rga_fallback_cpu`，实际用 `CpuPreprocessEngine`。
- `OpenCLGeometryEngine`：`DirectOpenCLRuntime` 加载不到 `libOpenCL.so`，`mode_tag` 落到 `opencl_fallback_cpu`，`warpPerspective`/`remap` 都走 `cv2`。
- `/api/status` 的 `wifi` 字段返回 `Windows local mode (board Wi-Fi unavailable)`；`ip`/`uptime`/`kernel` 依赖 Linux 命令与 `/proc`，本地大多返回 `-`。
- `metrics_service` 依赖 `/proc`、`/sys`，所以 benchmark 的 `cpu_percent` 为 `null`，`memory`/`thermal` 为空或带 `error`。
- `/api/start-systemui` 会尝试 `/bin/sh <switch_script>`，Windows 上必然失败。

## 本地跑测试

```powershell
python -m py_compile backend.py stitch_demo.py
python -m unittest discover tests
```

`tests/` 里 12 条用例中有 8 条 `import cv2`，未安装 OpenCV 时会在导入阶段报 `ModuleNotFoundError: No module named 'cv2'`；只有 `tests/unit/test_opencl_geometry.py`（4 条，全部用 fake runtime）无依赖。`tests/smoke/` 下四个脚本是板端硬件 smoke，Windows 上不要执行。
