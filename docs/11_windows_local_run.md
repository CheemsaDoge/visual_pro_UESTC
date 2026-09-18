# Windows 本地运行

这份指南用于 Windows 上测试页面、静态图片拼接和 partial panorama 展示。它不替代 RK3588 开发板运行。

## 一键启动

在项目目录中执行：

```powershell
conda activate cv_projectforfreshman
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
```

脚本会：

1. 使用当前激活环境中的 `python`；
2. 按 `requirements.txt` 检查或安装 NumPy 和 OpenCV；
3. 检查端口 `18080` 未被占用；
4. 启动 `backend.py`；
5. 服务就绪后自动打开 `http://127.0.0.1:18080`。

按 `Ctrl+C` 停止服务。若依赖已经安装，可加 `-SkipInstall`：

```powershell
.\start_windows.ps1 -SkipInstall
```

## 为什么此前会失败

Linux 开发板上的 Wi-Fi 页面使用 `pty` 和 `termios` 驱动 `connmanctl` 的交互式密码输入。Windows 没有这两个 POSIX 模块，所以原先在导入 `wifi_routes.py` 时就终止了整个后端。

现在 `wifi_routes.py` 在 Windows 会跳过 `pty`，后端可以正常启动；Wi-Fi 页面会明确提示“仅 Linux 开发板可用”，不会尝试在 Windows 调用 ConnMan。

## 本地可用与不可用功能

| 本地 Windows 可测试 | 需要 RK3588 开发板 |
| --- | --- |
| 页面、接口、静态图片拼接、输出图、Pannellum 全景展示 | CSI 摄像头、`/dev/video*`、NV12、RGA、V4L2/GStreamer、ConnMan Wi-Fi、Chromium kiosk |

本地拼接图片请放进 `stitch_input/`，从首页进入“图片拼接”。相机模式是开发板硬件功能；Windows 上不应把相机启动失败当作 Python 环境问题。
