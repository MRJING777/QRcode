#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qrsend - 终端多帧二维码文件发送器

原理: 把文件分块,每块加帧头后编码成一帧二维码,在终端按顺序循环播放。
      iPhone 打开接收页(receiver/index.html),用相机连续扫码,收齐后自动下载。

帧协议 (大端序, 共 14 字节帧头):
    偏移 0  magic  4B  'QSF1'
    偏移 4  total  2B  总帧数
    偏移 6  index  2B  帧序号 (从 0 开始)
    偏移 8  len    2B  数据区长度
    偏移 10 crc32  4B  数据区 CRC32
    偏移 14 data   lenB 数据
帧 0 的 data 前部: 2B 文件名长度 + UTF-8 文件名, 之后是文件内容。

用法:
    python3 qrsend.py 文件 [--receiver URL] [--chunk 600] [--fps 15] [--dump 目录]
"""

import argparse
import os
import shutil
import struct
import sys
import time
import zlib

import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M
from qrcode.exceptions import DataOverflowError

MAGIC = b'QSF1'
HEADER = struct.Struct('>4sHHHI')   # magic, total, index, len, crc32
DEFAULT_RECEIVER = 'https://mrjing777.github.io/QRcode/'

# 终端颜色: 黑底白字(白=亮, 黑=暗, 手机扫屏时黑底白码对比度最好)
BLACK_BG = '\033[40;97m'
RESET = '\033[0m'

# QR 码 L 纠错级各版本的字节模式容量 (version 1~40)
CAPACITY_L = [17, 32, 53, 78, 106, 134, 154, 192, 230, 271, 321, 367, 425,
              458, 520, 586, 644, 718, 792, 858, 929, 1003, 1091, 1171, 1273,
              1367, 1465, 1528, 1628, 1732, 1840, 1952, 2068, 2188, 2303,
              2431, 2563, 2699, 2809, 2953]


def build_frames(fname, data, chunk=600):
    """把文件内容按协议分帧。返回帧字节列表。"""
    nb = fname.encode('utf-8')
    name_field = struct.pack('>H', len(nb)) + nb

    parts = []
    first_cap = chunk - len(name_field)
    if first_cap < 0:
        raise ValueError('文件名太长 (UTF-8 编码后不能超过 %d 字节)' % chunk)
    parts.append(name_field + data[:first_cap])
    rest = data[first_cap:]
    for i in range(0, len(rest), chunk):
        parts.append(rest[i:i + chunk])

    frames = []
    total = len(parts)
    for i, payload in enumerate(parts):
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        frames.append(HEADER.pack(MAGIC, total, i, len(payload), crc) + payload)
    return frames


def qr_for(frame_bytes):
    """编码一帧为二维码对象(纠错级别 L, 自动选择最小版本)。"""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_L, border=0)
    qr.add_data(frame_bytes, optimize=0)
    qr.make(fit=True)
    return qr


def render(matrix, border=2):
    """模块矩阵 -> 终端文本。每字符表示 2x2 模块:
    ' '(黑底空格)=全黑  '█'=全白  '▀'=上白下黑  '▄'=上黑下白"""
    n = len(matrix)
    if n % 2:  # 模块数为奇数时右侧/下方补一列/一行黑
        matrix = [row + [0] for row in matrix] + [[0] * (n + 1)]
        n += 1

    def cell(r, c):
        if r < 0 or r >= n or c < 0 or c >= n:
            return False
        return matrix[r][c]

    lines = []
    for r in range(-2, n + 2, 2):
        line = []
        for c in range(-2, n + 2):
            top, bot = cell(r, c), cell(r + 1, c)
            if top and bot:
                line.append(u'█')   # █ 全白
            elif top:
                line.append(u'▀')   # ▀ 上白下黑
            elif bot:
                line.append(u'▄')   # ▄ 上黑下白
            else:
                line.append(' ')         # 全黑
        lines.append(BLACK_BG + ''.join(line) + RESET)
    return lines


def draw(qr_lines, info_line):
    """整屏重绘: 光标回左上, 进度行 + 二维码 + 提示行。"""
    out = ['\033[H', info_line + '\033[K\n']
    for l in qr_lines:
        out.append(l + '\033[K\n')
    out.append(RESET + '\033[K')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()


def play(frames, fps, fname, receiver, qr_lines_list):
    """循环播放所有帧,直到 Ctrl-C。"""
    total = len(frames)
    try:
        while True:
            for i, ls in enumerate(qr_lines_list):
                info = '\033[1m[%d/%d]\033[0m %s  (%d 帧/秒, Ctrl-C 停止)' % (
                    i + 1, total, fname, fps)
                draw(ls, info)
                time.sleep(1.0 / fps)
    except KeyboardInterrupt:
        sys.stdout.write('\033[0m\033[2J\033[H')
        sys.stdout.flush()


def max_chunk_for_lines(lines):
    """根据终端行数算每帧最大数据字节数 (二维码必须放得进屏幕)。
    返回保守值: 按 L 级容量表选版本, 再用实际编码验证。"""
    avail = max(4, lines - 3)          # 可用字符行数 (进度行+提示行占 3)
    max_modules = 2 * avail - 5        # 模块数 m 为奇数, 加 2x2 静区后向上取整
    v = max(1, min(40, (max_modules - 17) // 4))   # m = 21 + 4*(v-1)
    chunk = CAPACITY_L[v - 1] - 14     # 减去帧头
    while chunk > 40:                  # 用真实编码验证 (表格有余量差异时向下调)
        try:
            qr_for(build_frames('t', b'\x00' * chunk, chunk)[0])
            return chunk
        except DataOverflowError:
            chunk -= 50
    return 40


def main():
    ap = argparse.ArgumentParser(description='终端多帧二维码文件发送器')
    ap.add_argument('file', help='要发送的文件')
    ap.add_argument('--receiver', default=DEFAULT_RECEIVER,
                    help='接收页 URL (接收端网页地址)')
    ap.add_argument('--chunk', type=int, default=None,
                    help='每帧数据字节数; 默认按终端窗口大小自动选择')
    ap.add_argument('--fps', type=int, default=15,
                    help='播放帧率, 默认 15 (手机相机解码速度有限, 勿设太高)')
    ap.add_argument('--dump', metavar='DIR', default=None,
                    help='调试用: 把所有帧存成 PNG 到指定目录')
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print('文件不存在: %s' % args.file)
        sys.exit(1)

    cols, lines = shutil.get_terminal_size((80, 24))
    if args.chunk:
        chunk = args.chunk
    else:
        chunk = max_chunk_for_lines(lines)
        if lines < 50:
            print('提示: 终端只有 %d 行, 每帧仅 %d 字节 (约 %.1f KB/s)。'
                  '把终端窗口最大化(建议 50 行以上)可大幅提速。'
                  % (lines, chunk, chunk * args.fps / 1024.0))

    data = open(args.file, 'rb').read()
    fname = os.path.basename(args.file)
    frames = build_frames(fname, data, chunk)
    print('文件: %s (%d 字节), 共 %d 帧, 每帧 %d 字节, 约 %.1f KB/s'
          % (fname, len(data), len(frames), chunk, chunk * args.fps / 1024.0))

    # 编码全部帧
    print('生成二维码...', end=' ', flush=True)
    qrs = [qr_for(f) for f in frames]
    print('完成 (版本 v%d, %dx%d 模块)' % (qrs[0].version, qrs[0].version * 4 + 17,
                                           qrs[0].version * 4 + 17))

    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
        for i, qr in enumerate(qrs):
            qr.make_image().save(os.path.join(args.dump, 'frame_%04d.png' % i))
        print('帧已导出到 %s (调试模式, 到此结束)' % args.dump)
        sys.exit(0)

    qr_lines_list = [render(q.get_matrix()) for q in qrs]

    # 引导码: 手机扫它直达接收页
    guide = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=2)
    guide.add_data(args.receiver)
    guide.make(fit=True)
    print('\033[2J\033[H')
    print('\033[1m====== 第一步: 手机打开接收页 ======\033[0m')
    print('接收页地址: \033[1;34m%s\033[0m' % args.receiver)
    print('用 iPhone 相机或微信扫下面的引导码, 在打开的页面点「开始接收」:')
    for l in render(guide.get_matrix()):
        print(l)
    print()
    input('\033[1m手机准备好后, 回到这里按回车开始播放\033[0m')
    print('(保持接收页在前台, 屏幕调亮; 接收完成后按 Ctrl-C 停止)')
    time.sleep(1)
    play(frames, args.fps, fname, args.receiver, qr_lines_list)


if __name__ == '__main__':
    main()
