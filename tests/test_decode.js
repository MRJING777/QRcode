// 端到端解码测试: 读目录下的 PPM 二维码帧 -> jsQR 解码 -> 按协议拼装 -> 输出文件
// 用法: node test_decode.js <帧目录> <输出文件>
'use strict';
const fs = require('fs');
const path = require('path');
const jsQR = require('/tmp/jsQR.js');

const MAGIC = 0x51534631; // 'QSF1'

// PPM P6 解析 (Pillow 导出, 无注释行, maxval=255)
function readPPM(file) {
  const buf = fs.readFileSync(file);
  if (buf.toString('ascii', 0, 2) !== 'P6') throw new Error('not P6: ' + file);
  let off = 2;
  function nextToken() {
    while (off < buf.length && [0x20, 0x0a, 0x09, 0x0d].includes(buf[off])) off++;
    let s = '';
    while (off < buf.length && ![0x20, 0x0a, 0x09, 0x0d].includes(buf[off])) {
      s += String.fromCharCode(buf[off++]);
    }
    return s;
  }
  const w = +nextToken(), h = +nextToken(), maxv = +nextToken();
  const px = buf.slice(off); // 每个 token 后均以空白结束, 光栅数据紧随其后
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    // 反相: 模拟终端黑底白码(真实屏幕方向), 与接收页 onlyInvert 解码一致
    data[i * 4] = 255 - px[i * 3];
    data[i * 4 + 1] = 255 - px[i * 3 + 1];
    data[i * 4 + 2] = 255 - px[i * 3 + 2];
    data[i * 4 + 3] = 255;
  }
  return { data, width: w, height: h };
}

const dir = process.argv[2], out = process.argv[3];
const files = fs.readdirSync(dir).filter(f => f.endsWith('.ppm')).sort();
const frames = new Map();
let total = null;

for (const f of files) {
  const { data, width, height } = readPPM(path.join(dir, f));
  const q = jsQR(data, width, height, { inversionAttempts: 'invertFirst' });
  if (!q || !q.binaryData) { console.error('解码失败: ' + f); process.exit(1); }
  const bin = q.binaryData;
  // 手动读大端 (jsQR 的 binaryData 可能是普通数组, 不能用 DataView)
  function u32(o) { return ((bin[o] << 24) | (bin[o + 1] << 16) | (bin[o + 2] << 8) | bin[o + 3]) >>> 0; }
  function u16(o) { return (bin[o] << 8) | bin[o + 1]; }
  if (u32(0) !== MAGIC) { console.error('magic 不符: ' + f); process.exit(1); }
  total = u16(4);
  const idx = u16(6), len = u16(8);
  frames.set(idx, Buffer.from(bin.slice(14, 14 + len)));
}

if (total !== null && frames.size !== total) {
  console.error('帧数不符: 收 %d, 应 %d', frames.size, total);
  process.exit(1);
}

// 拼装: 帧 0 数据区前部为文件名
const keys = Array.from(frames.keys()).sort((a, b) => a - b);
const parts = [];
let fname = 'received.bin';
for (let i = 0; i < keys.length; i++) {
  const d = frames.get(keys[i]);
  if (i === 0) {
    const nl = d.readUInt16BE(0);
    fname = d.slice(2, 2 + nl).toString('utf8');
    parts.push(d.slice(2 + nl));
  } else {
    parts.push(d);
  }
}
fs.writeFileSync(out, Buffer.concat(parts));
console.log('解码完成: %d 帧 -> %s (%d 字节)', frames.size, fname, Buffer.concat(parts).length);
