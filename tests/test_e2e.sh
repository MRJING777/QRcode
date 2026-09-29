#!/bin/bash
# 端到端自测: 随机文件 -> qrsend 分帧 PNG -> jsQR 解码拼装 -> sha1 对比
set -e
cd "$(dirname "$0")/.."
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# 1. 生成测试文件 (含中文文件名, 200KB 随机 + 文本)
head -c 200000 /dev/urandom > "$T/测试文件.bin"
echo "qr-file-transfer e2e check 世界你好" >> "$T/测试文件.bin"

# 2. 发送端分帧 (仅 dump, 不播放)
python3 qrsend.py "$T/测试文件.bin" --dump "$T/frames" --chunk 600

# 3. PNG 转 PPM (Pillow)
python3 - "$T/frames" <<'EOF'
import glob, os, sys
from PIL import Image
for p in sorted(glob.glob(os.path.join(sys.argv[1], '*.png'))):
    Image.open(p).convert('RGB').save(p[:-4] + '.ppm', 'PPM')
print('converted', len(glob.glob(os.path.join(sys.argv[1], '*.ppm'))), 'frames')
EOF

# 4. Node 端 jsQR 解码拼装
node tests/test_decode.js "$T/frames" "$T/out.bin"

# 5. 校验
if cmp -s "$T/测试文件.bin" "$T/out.bin"; then
  echo "✅ 端到端校验通过: 内容完全一致 ($(stat -c%s "$T/out.bin") 字节)"
else
  echo "❌ 校验失败: 内容不一致"
  sha1sum "$T/测试文件.bin" "$T/out.bin"
  exit 1
fi
