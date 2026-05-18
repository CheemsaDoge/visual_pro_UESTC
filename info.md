# 摄像头环境信息采集（请在边缘设备执行）

> 目的：确认 `backend.py` 中摄像头调用方式（`source=0` 还是 `/dev/videoX`），并记录分辨率/FPS能力。

## 1) 设备与系统

```bash
date
uname -a
python3 --version
```

把输出粘贴到这里：

```
TODO
```

## 2) 视频设备节点

```bash
ls -l /dev/video*
```

把输出粘贴到这里：

```
TODO
```

## 3) v4l2 信息（如果设备有 v4l2-ctl）

```bash
which v4l2-ctl || echo "v4l2-ctl not found"
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext -d /dev/video0
```

若主设备不是 `/dev/video0`，请把上面命令中的设备改成实际节点（例如 `/dev/video1`）。

把输出粘贴到这里：

```
TODO
```

## 4) OpenCV 可用性与快速抓帧测试

```bash
python3 - <<'PY'
import cv2
print("opencv:", cv2.__version__)
for src in [0, 1, "/dev/video0", "/dev/video1"]:
    cap = cv2.VideoCapture(src)
    ok = cap.isOpened()
    print("source", src, "opened:", ok)
    if ok:
        ret, frame = cap.read()
        print("  read:", ret, "shape:", None if frame is None else frame.shape)
    cap.release()
PY
```

把输出粘贴到这里：

```
TODO
```

## 5) 最终建议配置（我来填）

> 你把上面结果给我后，我会补充这里并更新 `config.json` 中的摄像头参数。

```json
{
  "stitch": {
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

