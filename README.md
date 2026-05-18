# 视觉拼接工作台（GUI）

本项目已支持通过 `config.json` 配置界面字号和拼接路径。

## 1. 快速启动

```bash
python3 backend.py
```

默认访问：`http://127.0.0.1:18080`

## 2. 配置文件

配置文件路径：`./config.json`

可通过环境变量指定其他配置文件：

```bash
MYUI_CONFIG=/path/to/config.json python3 backend.py
```

## 3. 字体大小配置（四档）

在 `config.json` 中设置：

```json
{
  "ui": {
    "font_size": "medium"
  }
}
```

可选值：
- `small`（小）
- `medium`（中，默认）
- `large`（大）
- `xlarge`（特大）

也兼容中文值：`"小" / "中" / "大" / "特大"`。

> 字号由后端配置下发，页面启动时自动应用，不需要网页内单独设置入口。

## 4. 关键可配置项

```json
{
  "system": {
    "port": 18080,
    "log_file": "./backend.log",
    "switch_script": "./switch_to_systemui.sh"
  },
  "stitch": {
    "engine": "builtin",
    "script_path": "./stitch_demo.py",
    "python_bin": "python3",
    "script_timeout_sec": 180,
    "work_dir": "./_stitch_work",
    "input_dir": "./stitch_input",
    "output_dir": "./stitch_output",
    "input_url_prefix": "/stitch_input/",
    "output_url_prefix": "/stitch_output/",
    "camera": {
      "source": 0,
      "frame_width": 0,
      "frame_height": 0,
      "fps": 0,
      "auto_interval_sec": 0.5,
      "jpeg_quality": 88
    }
  }
}
```

说明：
- `stitch.engine`：
  - `builtin`：使用增强后的 OpenCV `PANORAMA` 拼接，带双边滤波预处理、USM+去噪后处理，以及双图 ORB 回退
  - `sequential`：按输入顺序做两两 ORB 配准与融合，失败时回退到 `builtin`
  - `scans`：使用增强后的 OpenCV `SCANS` 模式，带质量过滤、注册分辨率设置和后处理
  - `script`：调用 `stitch.script_path` 外部脚本
- `stitch.script_path`：拼接脚本路径
- `stitch.input_dir` / `stitch.output_dir`：输入/输出目录
- `stitch.work_dir`：临时工作目录
- `stitch.camera.source`：摄像头源（常见为 `0` 或 `/dev/video0`）
- `stitch.camera.auto_interval_sec`：自动拍摄间隔（默认 `0.5s`）

## 5. 摄像头拼接模式

`stitch.html?mode=camera` 已支持两种模式：

- **自行拍摄**：开始后显示实时画面，可手动点击“拍照”保存到 `stitch_input`。
- **自动拍摄**：开始后后端每 `0.5s` 自动拍 1 张，仅保留“停止录像并拼接”按钮。

停止后会自动调用同一套拼接后端，输出到 `stitch_output` 并在页面展示结果图。

## 6. 路径建议

当前开发环境与实际边缘环境不同，默认使用**相对路径**（如 `./stitch_input`）。

后续部署到边缘设备时，可按需改成**绝对路径**，例如：

```json
{
  "stitch": {
    "input_dir": "/userdata/myui/stitch_input",
    "output_dir": "/userdata/myui/stitch_output"
  }
}
```

## 7. 外部脚本模式说明

当 `stitch.engine = "script"` 时，后端将调用：

```bash
python3 stitch_demo.py --output <输出文件> [--auto-crop/--no-auto-crop] <图片1> <图片2> ...
```

本仓库中的 `stitch_demo.py` 已支持：
- `--output`
- `--auto-crop`
- `--no-auto-crop`
