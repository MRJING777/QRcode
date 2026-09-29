# qr-file-transfer —— 终端多帧二维码传文件

把文件切成小块，每块编码成一帧二维码，在终端循环播放；iPhone 用浏览器打开接收页，相机连续扫码、拼装、还原文件。**不需要数据线、蓝牙或局域网**，跨网络（甚至跨物理隔离设备）也能传。

```
┌─────────────┐   多帧二维码循环播放   ┌──────────────────┐
│ 电脑终端     │ ────────────────────▶ │ iPhone 浏览器接收页 │
│ qrsend.py   │   (相机逐帧解码拼装)    │ index.html + jsQR │
└─────────────┘                       └──────────────────┘
```

## 目录结构

```
qrsend.py           发送端 (Python 3, 依赖 qrcode + Pillow)
receiver/
  index.html        接收页 (自包含, 已内嵌 jsQR, 需部署到 HTTPS 静态托管)
  body.html         接收页源码 (不含 jsQR, 修改后用下面命令重新生成 index.html)
tests/
  test_e2e.sh       端到端自测 (随机文件 → 分帧 → jsQR 解码 → 校验)
  test_decode.js    测试用解码器 (jsQR + 帧协议拼装)
```

> 修改 `receiver/body.html` 后重新生成自包含页面：
> ```bash
> python3 -c "body=open('receiver/body.html',encoding='utf-8').read(); jsqr=open('/tmp/jsQR.js',encoding='utf-8').read(); open('receiver/index.html','w',encoding='utf-8').write(body.replace('/*__JSQR__*/', jsqr))"
> ```
> (`/tmp/jsQR.js` 取自 `curl -sL https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js -o /tmp/jsQR.js`)

## 一、部署接收页（只做一次）

iPhone 浏览器只允许在 **HTTPS** 页面调用相机，所以接收页必须托管。最简单的是 GitHub Pages：

1. 在 GitHub 新建仓库（如 `qr-file-transfer`，设为 Public）
2. 把整个目录推上去（本目录不含敏感内容）
3. Settings → Pages → Branch 选 `main` / 根目录 → Save
4. 记下页面地址，例如 `https://<你的用户名>.github.io/qr-file-transfer/`
5. 把 `qrsend.py` 开头的 `DEFAULT_RECEIVER` 改成这个地址

之后每次使用都会先显示一个**引导码**，iPhone 扫它直达接收页，不用手输网址。

## 二、使用方法

**电脑端（发送）：**
```bash
python3 qrsend.py 要发送的文件.pdf
```
1. 屏幕先显示引导码 + 接收页地址
2. **iPhone 用系统相机（或微信 → 「在 Safari 打开」）扫引导码**，打开接收页
3. 手机点「开始接收」，授权相机
4. 回电脑按回车，二维码开始循环播放
5. 手机收齐后自动保存（进度到 100%），电脑按 `Ctrl-C` 停止

**可选参数：**
| 参数 | 说明 |
|---|---|
| `--receiver URL` | 接收页地址（不填则用脚本里的默认值） |
| `--chunk N` | 每帧数据字节数；**默认按终端窗口大小自动选择** |
| `--fps N` | 播放帧率，默认 15；太高手机解码跟不上会丢帧 |
| `--dump 目录` | 调试：把帧导出成 PNG 后退出，不播放 |

## 三、速度与调优

速度 = 每帧字节数 × 实际解码帧率。

- **终端窗口最大化**：窗口越高二维码越大、每帧装得越多。24 行终端约 92 字节/帧（~1.3 KB/s），80 行约 2054 字节/帧（~30 KB/s）
- 调低终端字号、拉高窗口行数，效果立竿见影
- 手机屏幕调亮、正对屏幕、距离适中（二维码占画面 1/3 左右）
- 太高的 `--fps` 只会让手机丢帧，15 是比较稳的起点

## 四、帧协议（收发两端共用）

```
偏移 0   magic  4B  'QSF1'
偏移 4   total  2B  总帧数
偏移 6   index  2B  帧序号 (从 0 开始)
偏移 8   len    2B  数据区长度
偏移 10  crc32  4B  数据区 CRC32
偏移 14  data   lenB 数据
帧 0 的 data 前部: 2B 文件名长度 + UTF-8 文件名, 之后是文件内容
```
大端序。接收端按 index 去重、收齐 total 帧后按序拼装。

## 五、已知限制

- **微信内打不开相机**（iOS WKWebView 不开放 getUserMedia）：微信扫引导码后会提示「在 Safari 打开」，点一下即可；之后建议直接用系统相机扫
- 二维码纠错级别 L：靠「循环播放 + 去重」容忍个别坏帧，换来更大容量
- 适合几 MB 以内的文件；更大文件请耐心等待（30 KB/s 传 1 MB 约半分钟）

## 六、自测

```bash
bash tests/test_e2e.sh
```
输出 `✅ 端到端校验通过` 即两端协议一致。
