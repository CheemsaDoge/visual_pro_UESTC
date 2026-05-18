# 04 API 兼容性

## 保留的旧 API

| API | 状态 | 说明 |
| --- | --- | --- |
| `/` | 保留 | 仍映射到 `index.html` |
| `/api/config/public` | 保留 | 新增 `accel` 状态字段 |
| `/api/status` | 保留 | 仍返回 hostname/kernel/uptime/ip/wifi/backend |
| `/api/camera/start` | 保留 | 返回字段基本兼容，新增 preprocess/selector 状态 |
| `/api/camera/capture` | 保留 | 手动拍照仍保存到 `stitch_input/` |
| `/api/camera/stop` | 保留 | 停止后仍尝试拼接，新增 dropped_count/engine 字段 |
| `/api/camera/status` | 保留 | 新增 preprocess/selector/last_selector_decision/dropped_count |
| `/api/camera/frame.jpg` | 保留 | 单帧预览 JPEG |
| `/api/camera/stream` | 保留 | MJPEG 流 |
| `/api/stitch/status` | 保留 | 新增 geometry/engine_status |
| `/api/stitch/image` | 保留 | 仍支持 base64 images 和 server_files |
| `/api/stitch/input-list` | 保留 | 列出输入目录图片 |
| `/api/stitch/output-list` | 保留 | 列出输出目录图片 |
| `/api/stitch/output-clear` | 保留 | 清理输出目录图片 |

## 行为变化

- 自动拍摄不再无条件保存每个间隔帧，而是：
  1. 先 `PreprocessEngine.process_for_save()`；
  2. 再 `KeyframeSelector.decision()`；
  3. `keep=true` 才保存。
- 默认 `selector=off`，所以默认行为仍近似旧版：达到自动间隔就保存。
- 相机预览和保存统一走预处理引擎，因此旋转/缩放逻辑集中到 `app/preprocess/`。

## 仅内部重构

前端页面 `index.html`、`stitch.html`、`wifi.html` 暂未重写。主要路由路径和返回核心字段保持兼容。
