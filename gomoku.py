# -*- coding: utf-8 -*-
"""
桌宠五子棋 · 摸鱼版 —— 局域网双人对弈 + 桌宠待机

用法:
    双击 start_gomoku.bat       # 推荐: 自动找 Python, 无黑窗启动
    python gomoku.py            # 默认监听 27183 端口
    python gomoku.py 27184      # 自定义监听端口(同一台电脑开两个测试时用)

分发:
    python make_dist.py --roles kimi   # 生成 dist/ 绿色文件夹, 拷给同事即用

玩法:
    - 平时是桌宠待机形态, 右键点击桌宠弹菜单: 五子棋 / 象棋(开发中) / 设置 / 隐藏 / 退出
    - 菜单/空闲棋盘 5 秒无操作自动回到桌宠待机
    - 设置在浏览器里打开(本地页面): 改昵称、切换动漫桌宠形象、管理好友IP、查看战绩
    - 对局中输入对方 IP(或点选好友)发起对局; 系统随机黑白, 黑先
    - 对局状态栏显示轮到谁出手; 有 [认输] 和 [邀新一局](对局中邀请需对方接受)
    - Ctrl+Q  全局隐藏/呼出;  Esc 快速隐藏;  滚轮调透明度 0%~100%(0=完全隐形仍可落子)
"""
import ctypes
import hashlib
import json
import math
import os
import queue
import random
import shutil
import socket
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
import zipfile
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

try:
    from PIL import Image, ImageTk, ImageFilter
except ImportError:          # 无 PIL 时退化为旧版浮动动画
    Image = ImageTk = ImageFilter = None

# ---------------- 常量 ----------------
N = 15                    # 15 路棋盘
CELL = 20                 # 交叉点间距(px)
MARGIN = 22               # 棋盘边距
TOPBAR = 22               # 顶栏高度(状态/拖动/隐藏)
DEFAULT_PORT = 27183
BOARD_W = MARGIN * 2 + CELL * (N - 1)      # 324

# 各模式窗口尺寸 (宽, 高)
SIZE_PET = (180, 215)
SIZE_BOARD = (BOARD_W, TOPBAR + BOARD_W + 86)   # 底栏3行

MAGIC = "#010204"          # 抠透明色: 该颜色像素完全透明(点击穿透)
INPUT_ALPHA = 0.01         # 输入层透明度(接近0但保留命中)
ALPHA_DEFAULT = 0.80
ALPHA_MIN, ALPHA_MAX = 0.00, 1.00

# 配色: 文字一律中灰底板+亮字(任意桌面背景可读)
PLATE = "#5a5a5a"
PLATE_DARK = "#404040"
FG = "#f2f2f2"
FG_DIM = "#c8c8c8"
GREEN_BG, GREEN_FG = "#4a6a42", "#e8f2e0"
BLUE_BG, BLUE_FG = "#42556a", "#e0e8f2"
RED_BG, RED_FG = "#6a4242", "#f2e0e0"

LINE_COLOR = "#8f8f8f"

# 棋子: 0空 1黑 2白
BLACK, WHITE = 1, 2

# 全局热键
WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
VK_Q = 0x51
HOTKEY_ID = 37219

MSG_LIMIT = 512
IDLE_SECONDS = 5           # 无操作自动回待机

# 桌宠待机动画参数: 呼吸(缩放) + 摇摆(旋转) + 浮动(位移) 逐帧预烘焙
ANIM_FRAMES = 90           # 一个完整循环的帧数
ANIM_MS = 30               # 每帧间隔 -> 循环周期约 2.7 秒
ANIM_CACHE_MAX = 8         # 动画帧缓存上限(动作数), 防随机换动作内存膨胀
ANIM_BOB = 4.0             # 浮动幅度(px)
ANIM_ROT = 2.5             # 摇摆幅度(度)
ANIM_SQUASH = 0.03         # 呼吸缩放幅度(宽高反向, 3%)

# 对局结果 -> 情绪动作的关键词匹配表(动作名因角色而异, 用关键词模糊命中)
MOOD_WIN_KW = ("舞", "庆祝", "欢呼", "撒花", "开心", "跃动", "挥手", "胜利",
               "击掌", "生花", "蹦跳", "骄傲", "掌声", "微笑")
MOOD_LOSE_KW = ("哭", "泪", "伤心", "难过", "委屈", "生气", "气急败坏", "沮丧",
                "叹气", "沉眠", "小憩", "分文不剩", "袋空如洗", "吓一跳", "躺")

PETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pets")
ANIMS_DIR = os.path.join(PETS_DIR, "anims")   # 视频桌宠包根目录

# 图片桌宠已按用户要求全部移除(2026-11-23); pets/*.png 文件保留, 想恢复往列表加回即可
IMAGE_PETS = []

# 视频桌宠包默认显示名(无 pack.json 时按目录名兜底)
PACK_NAMES = {"claude": "大肥鱼"}

# 角色包在线下载(GitHub Release, 国内走 ghfast.top 加速):
# 用 make_pet_release.py 发布后, 把 catalog.json 的地址填到这里再重新打包。
# 留空 = 设置页"角色包"里显示"下载源未配置", 其余功能不受影响。
PET_CATALOG_URL = ""
# 全新安装(无角色包)或装完角色包后, 默认选中的形象目录名
DEFAULT_PET_ROLE = "claude"


def default_config():
    return {"name": "摸鱼选手", "skin": 0, "friends": [], "records": [],
            "pet_pos": None,          # 桌宠被拖动后的位置 [x, y], 重启恢复
            "pet_scale": 1.0}         # 桌宠显示比例 0.5~2.5, 设置页滑条可调


def config_path_default():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


# ---------------- 纯逻辑(可独立测试) ----------------
def check_win(board, x, y):
    """刚在 (x,y) 落子后, 返回连成五子的坐标列表(含该子), 没有则返回 None"""
    c = board[y][x]
    if not c:
        return None
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        cells = [(x, y)]
        for s in (1, -1):
            nx, ny = x + dx * s, y + dy * s
            while 0 <= nx < N and 0 <= ny < N and board[ny][nx] == c:
                cells.append((nx, ny))
                nx += dx * s
                ny += dy * s
        if len(cells) >= 5:
            return cells
    return None


def board_full(board):
    return all(v for row in board for v in row)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def parse_target(text, default_port=DEFAULT_PORT):
    """解析 '192.168.1.5' 或 '192.168.1.5:27184' -> (ip, port) 或 None"""
    text = (text or "").strip()
    if not text:
        return None
    if ":" in text:
        host, _, port = text.rpartition(":")
        try:
            return (host, int(port))
        except ValueError:
            return None
    return (text, default_port)


def valid_addr(text):
    """地址校验: 要求含点分的IP/主机名, 或显式带端口"""
    t = parse_target(text)
    if not t:
        return False
    host, port = t
    if not host or not (0 < port < 65536):
        return False
    return "." in host or ":" in (text or "")


# ---------------- 桌宠形象(纯 canvas 绘制, 无外部图片依赖) ----------------
def _pet_base(cv, cx, cy, R, body, outline):
    cv.create_oval(cx - R, cy - R, cx + R, cy + R, fill=body, outline=outline)


def _pet_face(cv, cx, cy, R, eye="#2a2a2a", blush="#f2a0a8"):
    for sx in (-1, 1):
        ex = cx + sx * R * 0.38
        cv.create_oval(ex - R * 0.09, cy - R * 0.18 - R * 0.09,
                       ex + R * 0.09, cy - R * 0.18 + R * 0.09,
                       fill=eye, outline="")
        cv.create_oval(cx + sx * R * 0.62 - R * 0.14, cy + R * 0.12 - R * 0.07,
                       cx + sx * R * 0.62 + R * 0.14, cy + R * 0.12 + R * 0.07,
                       fill=blush, outline="")


def _pet_smile(cv, cx, cy, R, color="#2a2a2a"):
    cv.create_arc(cx - R * 0.22, cy + R * 0.08,
                  cx + R * 0.22, cy + R * 0.42,
                  start=200, extent=140, style="arc",
                  outline=color, width=2)


def pet_cat(cv, cx, cy, s=1.0):
    R = 40 * s
    for sx in (-1, 1):  # 耳朵
        ax = cx + sx * R * 0.55
        cv.create_polygon(ax - R * 0.28, cy - R * 0.62,
                          ax, cy - R * 1.22,
                          ax + R * 0.28, cy - R * 0.6,
                          fill="#9aa0b5", outline="#6a6f80")
    _pet_base(cv, cx, cy, R, "#c5c9d8", "#6a6f80")
    _pet_face(cv, cx, cy, R)
    cv.create_oval(cx - R * 0.08, cy + R * 0.1 - R * 0.06,
                   cx + R * 0.08, cy + R * 0.1 + R * 0.06,
                   fill="#e08080", outline="")  # 鼻子
    _pet_smile(cv, cx, cy, R)
    for sy in (0.28, 0.42):  # 胡须
        for sx in (-1, 1):
            cv.create_line(cx + sx * R * 0.55, cy + R * sy,
                           cx + sx * R * 0.95, cy + R * (sy - 0.08),
                           fill="#6a6f80")


def pet_panda(cv, cx, cy, s=1.0):
    R = 40 * s
    for sx in (-1, 1):
        cv.create_oval(cx + sx * R * 0.72 - R * 0.26, cy - R * 0.78 - R * 0.26,
                       cx + sx * R * 0.72 + R * 0.26, cy - R * 0.78 + R * 0.26,
                       fill="#333333", outline="#111111")
    _pet_base(cv, cx, cy, R, "#f5f5f0", "#555555")
    for sx in (-1, 1):  # 眼斑
        ex = cx + sx * R * 0.38
        cv.create_oval(ex - R * 0.2, cy - R * 0.18 - R * 0.26,
                       ex + R * 0.2, cy - R * 0.18 + R * 0.26,
                       fill="#333333", outline="")
        cv.create_oval(ex - R * 0.07, cy - R * 0.22 - R * 0.07,
                       ex + R * 0.07, cy - R * 0.22 + R * 0.07,
                       fill="#ffffff", outline="")
    cv.create_oval(cx - R * 0.09, cy + R * 0.12 - R * 0.07,
                   cx + R * 0.09, cy + R * 0.12 + R * 0.07,
                   fill="#333333", outline="")
    _pet_smile(cv, cx, cy, R)


def pet_chick(cv, cx, cy, s=1.0):
    R = 40 * s
    _pet_base(cv, cx, cy, R, "#ffd94a", "#d8a800")
    for ang in (-14, 0, 14):  # 头顶呆毛
        cv.create_line(cx, cy - R, cx + ang * R * 0.02, cy - R * 1.28,
                       fill="#d8a800", width=2)
    _pet_face(cv, cx, cy, R)
    cv.create_polygon(cx - R * 0.14, cy + R * 0.16,
                      cx + R * 0.14, cy + R * 0.16,
                      cx, cy + R * 0.34, fill="#ff9d2e", outline="")  # 嘴
    _pet_smile(cv, cx, cy, R, "#b07800")


def pet_bunny(cv, cx, cy, s=1.0):
    R = 40 * s
    for sx in (-1, 1):  # 长耳朵
        ex = cx + sx * R * 0.42
        cv.create_oval(ex - R * 0.16, cy - R * 1.9,
                       ex + R * 0.16, cy - R * 0.55,
                       fill="#f7f7f2", outline="#aaaaaa")
        cv.create_oval(ex - R * 0.07, cy - R * 1.75,
                       ex + R * 0.07, cy - R * 0.7,
                       fill="#f6b8c0", outline="")
    _pet_base(cv, cx, cy, R, "#f7f7f2", "#aaaaaa")
    _pet_face(cv, cx, cy, R)
    cv.create_oval(cx - R * 0.07, cy + R * 0.14 - R * 0.06,
                   cx + R * 0.07, cy + R * 0.14 + R * 0.06,
                   fill="#f6a0b0", outline="")
    _pet_smile(cv, cx, cy, R)


def pet_frog(cv, cx, cy, s=1.0):
    R = 40 * s
    for sx in (-1, 1):  # 眼睛凸起
        ex = cx + sx * R * 0.42
        ey = cy - R * 0.78
        cv.create_oval(ex - R * 0.26, ey - R * 0.26,
                       ex + R * 0.26, ey + R * 0.26,
                       fill="#7ac96a", outline="#3e7a34")
        cv.create_oval(ex - R * 0.12, ey - R * 0.12,
                       ex + R * 0.12, ey + R * 0.12,
                       fill="#ffffff", outline="")
        cv.create_oval(ex - R * 0.05, ey - R * 0.05,
                       ex + R * 0.05, ey + R * 0.05,
                       fill="#2a2a2a", outline="")
    _pet_base(cv, cx, cy, R, "#7ac96a", "#3e7a34")
    cv.create_arc(cx - R * 0.4, cy - R * 0.05,
                  cx + R * 0.4, cy + R * 0.45,
                  start=15, extent=150, style="arc",
                  outline="#2a2a2a", width=2)  # 宽笑
    for sx in (-1, 1):
        cv.create_oval(cx + sx * R * 0.6 - R * 0.14, cy + R * 0.12 - R * 0.07,
                       cx + sx * R * 0.6 + R * 0.14, cy + R * 0.12 + R * 0.07,
                       fill="#f2a0a8", outline="")


# 备用 canvas 桌宠(图片缺失时兜底)
CANVAS_PETS = [("猫咪", pet_cat), ("熊猫", pet_panda)]


def _anim_frame_size(pdir, anim):
    """读动作包首帧尺寸, 用于让桌宠窗口比例匹配视频帧(横版 176x99)"""
    try:
        with Image.open(os.path.join(pdir, anim, "f000.png")) as im:
            return im.size
    except Exception:
        return None


def _load_pack_anim(adir, target_w, target_h, pad=4):
    """加载动作帧: 裁掉人物周边空白 -> 等比放大铺满目标区域 -> alpha 二值化。

    视频包原始帧是 176x99 横版画面, 人物只占中间约 45%x85%,
    直接塞进竖版窗口会显得'窗口很大人物占一半'。按整个动作所有帧的
    联合 alpha bbox 裁剪(动作位移不露馅), 单次插值缩放保证清晰度,
    放大超过 1.05 倍时叠加 UnsharpMask 缓解放大发虚。
    """
    if Image is None:
        return []
    imgs, boxes = [], []
    for fn in sorted(os.listdir(adir)):
        if not fn.endswith(".png") or fn == "preview.png":
            continue
        im = Image.open(os.path.join(adir, fn)).convert("RGBA")
        imgs.append(im)
        boxes.append(im.getchannel("A").getbbox())
    if not imgs:
        return []
    solid = [b for b in boxes if b]
    out = []
    if solid:
        ux1 = max(0, min(b[0] for b in solid) - pad)
        uy1 = max(0, min(b[1] for b in solid) - pad)
        ux2 = min(imgs[0].width, max(b[2] for b in solid) + pad)
        uy2 = min(imgs[0].height, max(b[3] for b in solid) + pad)
    else:                                   # 全透明帧兜底: 不裁剪
        ux1, uy1, ux2, uy2 = 0, 0, imgs[0].width, imgs[0].height
    cw, ch = max(1, ux2 - ux1), max(1, uy2 - uy1)
    fit = min(target_w / cw, target_h / ch)
    for im in imgs:
        fr = im.crop((ux1, uy1, ux2, uy2))
        if abs(fit - 1.0) > 0.02:
            fr = fr.resize((max(1, round(cw * fit)),
                            max(1, round(ch * fit))), Image.LANCZOS)
            if fit > 1.05 and ImageFilter is not None:
                fr = fr.filter(ImageFilter.UnsharpMask(
                    radius=1.5, percent=90, threshold=2))
        # alpha 二值化, 与 process_pets.py 一致, 防止透明抠图黑边
        a = fr.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        fr.putalpha(a)
        out.append(fr)
    return out


def load_skin_list():
    """视频桌宠包优先; 图片桌宠(已移除)与 canvas 兜底按需出现"""
    skins = []

    # 视频桌宠包(pets/anims/<角色>/<动作>/f000.png ..., 由 import_anims.py 抽帧生成)
    if os.path.isdir(ANIMS_DIR):
        for pd in sorted(os.listdir(ANIMS_DIR)):
            pdir = os.path.join(ANIMS_DIR, pd)
            if not os.path.isdir(pdir):
                continue
            anims = sorted(d for d in os.listdir(pdir)
                           if os.path.exists(os.path.join(pdir, d, "f000.png")))
            if not anims:
                continue
            meta = {}
            try:
                with open(os.path.join(pdir, "pack.json"), encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass
            skins.append({"name": str(meta.get("name") or PACK_NAMES.get(pd, pd)),
                          "img": None, "file": None, "draw": None,
                          "pack": pdir, "anims": anims,
                          "animbase": "anims/%s" % pd,
                          "fps": int(meta.get("fps") or 12),
                          "fsize": _anim_frame_size(pdir, anims[0]),
                          "thumb": "anims/%s/%s/preview.png" % (pd, anims[0])})

    # 图片桌宠(可选恢复: IMAGE_PETS 里加回条目即出现)
    for nm, img_file in IMAGE_PETS:
        p = os.path.join(PETS_DIR, img_file)
        if os.path.exists(p):
            skins.append({"name": nm, "img": p, "file": img_file, "draw": None})

    # 兜底: 什么形象都没有时用 canvas 画一个, 避免空列表崩溃
    if not skins:
        for nm, fn in CANVAS_PETS[:1]:
            skins.append({"name": nm, "img": None, "file": None, "draw": fn})
    return skins


# ---------------- 全局热键线程 ----------------
def hotkey_thread(eq):
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL, VK_Q):
        eq.put(("hotkey_fail",))
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            eq.put(("toggle",))


# ---------------- 主应用 ----------------
class App:
    def __init__(self, port, start_pos=None, config_path=None):
        self.port = port
        self.eq = queue.Queue()
        self.cfg_path = config_path or config_path_default()
        self.cfg = self._load_cfg()

        # 界面状态
        self.mode = "pet"            # pet / menu / board
        self.hotspots = []           # [(x0,y0,x1,y1,fn,widget)]
        self.toast = None
        self.toast_until = 0.0
        self.last_active = time.time()
        self._pos = start_pos or (0, 0)
        self.cfg_lock = threading.Lock()

        # 角色包在线下载状态(设置页后台下载用)
        self._pets_state = {"phase": "idle", "dir": None,
                            "got": 0, "total": 0, "msg": ""}
        self._pets_lock = threading.Lock()
        self._pets_catalog = None
        self._pets_catalog_at = 0.0

        # 桌宠形象 + 浏览器设置服务
        self.skins = load_skin_list()
        if not (0 <= self.cfg["skin"] < len(self.skins)):
            self.cfg["skin"] = 0        # 旧配置索引越界(如已移除的猫咪/熊猫)时归零
        self._anim_frames = {}       # path 或 (pack,anim,scale) -> [PhotoImage, ...]
        self._anim_lru = []          # LRU 顺序, 超过 ANIM_CACHE_MAX 淘汰防内存膨胀
        self._anim_t = 0             # 当前动画帧号
        self._anim_running = False
        self._pack_anim = None       # 视频桌宠当前动作名
        self._pack_loops = 0         # 当前动作已完整循环次数
        self._bp_anim_t = 0          # 棋盘胜负动画帧号
        self._bp_running = False     # 棋盘胜负动画链在跑
        self._srv = None
        self._srv_port = 0
        self.menu_win = None
        self.anim_win = None         # 动作选择窗
        self.solo = False            # 单机试玩模式(内置AI, 不联网)

        # 对局状态
        self.board = [[0] * N for _ in range(N)]
        self.my_stone = 0
        self.turn = BLACK
        self.game_over = False
        self.result = None           # win / lose / draw
        self.resigned = False
        self.peer_resigned = False
        self.awaiting_new = False
        self.win_cells = None
        self.last_move = None
        self.playing = False
        self.connecting = False
        self.new_req_pending = False
        self.new_req_until = 0.0
        self.awaiting_new = False
        self.awaiting_new_until = 0.0

        # 网络状态
        self.sock = None
        self.conn = None
        self.send_lock = threading.Lock()
        self.listen_sock = None
        self.peer_name = ""
        self.peer_remark = ""
        self.peer_addr = ""

        self._build_ui(start_pos)
        self._start_listener()
        threading.Thread(target=hotkey_thread, args=(self.eq,), daemon=True).start()
        self.root.after(80, self._poll)
        self.set_mode("pet")

    # ---------- 配置 ----------
    def _load_cfg(self):
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            base = default_config()
            base.update({k: v for k, v in cfg.items() if k in base})
            return base
        except Exception:
            return default_config()

    def save_cfg(self):
        try:
            with open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ---------- UI 骨架 ----------
    def _build_ui(self, start_pos):
        # ===== 视觉层 root: 抠透明, 只显示线条/棋子/桌宠/文字 =====
        self.root = tk.Tk()
        self.root.title("gomoku")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", ALPHA_DEFAULT)
        self.root.attributes("-transparentcolor", MAGIC)
        self.alpha = ALPHA_DEFAULT
        self.root.configure(bg=MAGIC)

        if start_pos:
            self._pos = tuple(start_pos)      # 测试/显式指定优先
        else:
            pp = self.cfg.get("pet_pos")      # 上次拖动保存的位置
            if (isinstance(pp, (list, tuple)) and len(pp) == 2
                    and all(isinstance(v, int) and -100 <= v < 8000 for v in pp)):
                self._pos = tuple(pp)
            else:
                sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
                self._pos = (sw - 200, sh - 300)
        self.canvas = tk.Canvas(self.root, bg=MAGIC, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # ===== 输入层 iw: 近乎全透明但承接全部鼠标事件 =====
        self.iw = tk.Toplevel(self.root)
        self.iw.overrideredirect(True)
        self.iw.attributes("-topmost", True)
        self.iw.attributes("-alpha", INPUT_ALPHA)
        self.iw.configure(bg="#000000")
        self.iw_canvas = tk.Canvas(self.iw, bg="#000000", highlightthickness=0)
        self.iw_canvas.pack(fill="both", expand=True)
        self.iw_canvas.bind("<Button-1>", self._route_click)
        self.iw_canvas.bind("<B1-Motion>", self._drag_move)
        self.iw_canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.iw_canvas.bind("<ButtonPress-3>", self._right_press)
        self.iw_canvas.bind("<B3-Motion>", self._drag_move)
        self.iw_canvas.bind("<ButtonRelease-3>", self._drag_end)
        self.iw.bind("<Escape>", lambda e: self.hide())
        self.iw.bind("<MouseWheel>", self._on_wheel)
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<MouseWheel>", self._on_wheel)

        # 常驻输入框(按需嵌入画布)
        self.entry_ip = tk.Entry(self.canvas, font=("Microsoft YaHei", 9),
                                 bg=PLATE_DARK, fg=FG, insertbackground=FG,
                                 relief="flat", justify="center")
        self.entry_ip.insert(0, "对方IP:端口")
        self.entry_ip.bind("<FocusIn>", self._placeholder_clear)
        self.entry_ip.bind("<Return>", lambda e: self.invite())
        self.entry_ip.bind("<Key>", lambda e: self._touch())

    # ---------- UI 小部件助手 ----------
    def _placeholder_clear(self, e):
        if self.entry_ip.get() == "对方IP:端口":
            self.entry_ip.delete(0, "end")

    def _touch(self):
        self.last_active = time.time()

    def btn(self, x, y, w, h, text, cmd, fg=FG, bg=PLATE, fsize=9):
        self.canvas.create_rectangle(x, y, x + w, y + h, fill=bg, outline="", tags="ui")
        self.canvas.create_text(x + w / 2, y + h / 2, text=text, fill=fg,
                                font=("Microsoft YaHei", fsize), tags="ui")
        self.hotspots.append((x, y, x + w, y + h, cmd, None))

    def label(self, x, y, text, fg=FG_DIM, fsize=8, plate=True, anchor="w"):
        tid = self.canvas.create_text(x, y, text=text, fill=fg,
                                      font=("Microsoft YaHei", fsize),
                                      anchor=anchor, tags="ui")
        if plate:
            bb = self.canvas.bbox(tid)
            if bb:
                rid = self.canvas.create_rectangle(bb[0] - 4, bb[1] - 1,
                                                   bb[2] + 4, bb[3] + 1,
                                                   fill=PLATE, outline="", tags="ui")
                self.canvas.tag_lower(rid, tid)   # 底板压到文字下层
        return tid

    def place_entry(self, widget, x, y, w, h):
        widget.configure(width=max(4, w // 9))
        self.canvas.create_window(x, y, window=widget, width=w, height=h,
                                  anchor="nw", tags="ui")
        self.hotspots.append((x, y, x + w, y + h, None, widget))

    def set_toast(self, text):
        self.toast = text
        self.toast_until = time.time() + 2.0
        self.render()

    def topbar(self, status_text, w):
        if status_text:
            self.label(10, TOPBAR / 2, status_text, fg=FG, fsize=9)
        self.canvas.create_text(w - 16, TOPBAR / 2, text="—", fill=FG,
                                font=("Microsoft YaHei", 10), tags="ui")
        self.hotspots.append((w - 30, 0, w, TOPBAR, self.hide, None))

    # ---------- 模式切换 ----------
    def set_mode(self, m):
        self.mode = m
        self.close_menu()
        if m == "pet" and self.solo:
            # 从单机试玩回到桌宠: 若局已结束(或被中断)就清空对局状态
            self.solo = False
            if self.game_over or not self.playing:
                self._net_reset()
        self.new_req_pending = False
        self._touch()
        self._apply_size()
        self.render()

    def _pet_size(self):
        """桌宠窗口尺寸(随显示比例缩放); 视频包按帧比例适配, 避免大窗口小人"""
        s = max(0.5, min(2.5, float(self.cfg.get("pet_scale") or 1.0)))
        skins = getattr(self, "skins", None)
        if skins:
            skin = skins[self.cfg["skin"] % len(skins)]
            fs = skin.get("fsize") if skin.get("pack") else None
            if fs:
                # 视频帧是横版(如 176x99): 窗口取同比例, 宽度沿用 SIZE_PET[0]
                h = max(60, round(SIZE_PET[0] * fs[1] / fs[0]))
                return (int(SIZE_PET[0] * s), int(h * s))
        return (int(SIZE_PET[0] * s), int(SIZE_PET[1] * s))

    def _apply_size(self):
        w, h = self._pet_size() if self.mode == "pet" else SIZE_BOARD
        g = f"{w}x{h}+{self._pos[0]}+{self._pos[1]}"
        self.root.geometry(g)
        self.iw.geometry(g)
        self.canvas.configure(width=w, height=h)
        self.iw_canvas.configure(width=w, height=h)

    # ---------- 渲染 ----------
    def render(self):
        w, h = self._pet_size() if self.mode == "pet" else SIZE_BOARD
        self.canvas.delete("all")
        self.hotspots = []
        draw = {"pet": self.render_pet, "board": self.render_board}
        draw[self.mode]()
        if self.toast and time.time() < self.toast_until:
            self.label(w / 2, h - 12, self.toast,
                       fg="#ffd0d0", fsize=8, anchor="center")

    def render_pet(self):
        # 无顶栏无名字(用户要求): 隐藏走右键菜单[隐藏], 拖动=左键按住桌宠
        self._anim_t = 0
        self._pack_loops = 0
        self._draw_pet_frame()
        self._start_anim()

    # ---------- 桌宠流畅待机动画 ----------
    def _draw_pet_frame(self):
        """按当前帧号重绘桌宠(只动 pet_anim 标签内的元素, 不重建热点)"""
        self.canvas.delete("pet_anim")
        t = self._anim_t
        T = ANIM_FRAMES
        base = math.tau * t / T
        dy = ANIM_BOB * math.sin(base + math.pi)              # 浮动
        ang = ANIM_ROT * math.sin(base + math.pi / 2)         # 摇摆
        sq = ANIM_SQUASH * math.sin(base)                     # 呼吸(宽涨高缩)
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        w, h = self._pet_size()
        cx, cy = w / 2, h * 0.43
        scale = max(0.5, min(2.5, float(self.cfg.get("pet_scale") or 1.0)))
        if skin.get("pack"):
            # 视频桌宠: 动画自带动作, 不叠加呼吸/摇摆, 按 pet_scale 缩放逐帧播放
            frames = self._pack_frames(skin, self._pack_anim, scale)
            n = len(frames)
            if n:
                self.canvas.create_image(w / 2, h / 2,
                                         image=frames[self._anim_t % n],
                                         tags="pet_anim")
        elif skin["img"]:
            frames = self._pet_frames(skin["img"], scale)
            if len(frames) == 1:                    # 无 PIL: 只有浮动
                self.canvas.create_image(cx, cy + dy, image=frames[0],
                                         tags="pet_anim")
            else:
                self.canvas.create_image(cx, cy + dy,
                                         image=frames[t % len(frames)],
                                         tags="pet_anim")
        else:
            before = set(self.canvas.find_all())
            skin["draw"](self.canvas, cx, cy - 4 + dy, (1.0 + sq) * scale)
            for item in set(self.canvas.find_all()) - before:
                self.canvas.addtag_withtag("pet_anim", item)

    def _pet_frames(self, path, scale=1.0):
        """懒加载预烘焙一整个循环的动画帧(呼吸缩放+旋转, LANCZOS 高质量)"""
        key = (path, round(scale, 2))
        frames = self._anim_cache_get(key)
        if frames is not None:
            return frames
        if Image is None:
            ph = tk.PhotoImage(file=path, master=self.root)
            self._anim_frames[key] = [ph]
            return self._anim_frames[key]
        img = Image.open(path).convert("RGBA")
        if scale != 1.0:
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))), Image.LANCZOS)
        # alpha 二值化, 与 process_pets.py 一致, 防止透明色抠图出现黑边
        alpha = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        img.putalpha(alpha)
        w0, h0 = img.size
        out = []
        for i in range(ANIM_FRAMES):
            base = math.tau * i / ANIM_FRAMES
            sw = max(1, int(round(w0 * (1 + ANIM_SQUASH * math.sin(base)))))
            sh = max(1, int(round(h0 * (1 - ANIM_SQUASH * math.sin(base)))))
            fr = img.resize((sw, sh), Image.LANCZOS)
            fr = fr.rotate(ANIM_ROT * math.sin(base + math.pi / 2),
                           resample=Image.BICUBIC, expand=False)
            out.append(ImageTk.PhotoImage(fr, master=self.root))
        self._anim_cache_put(key, out)
        return out

    def _anim_cache_get(self, key):
        frames = self._anim_frames.get(key)
        if frames is not None and key in self._anim_lru:
            self._anim_lru.remove(key)
            self._anim_lru.append(key)      # 触碰: 移到 MRU 端
        return frames

    def _anim_cache_put(self, key, frames):
        self._anim_frames[key] = frames
        if key in self._anim_lru:
            self._anim_lru.remove(key)
        self._anim_lru.append(key)
        # 每个动作 ~120 帧×200KB ≈ 25MB, 不设上限随机换动作会把内存吃爆
        while len(self._anim_lru) > ANIM_CACHE_MAX:
            old = self._anim_lru.pop(0)
            self._anim_frames.pop(old, None)

    def _pack_frames(self, skin, anim, scale=1.0):
        """懒加载视频桌宠动作帧: 裁空白+铺满窗口+按 scale 缩放(见 _load_pack_anim)"""
        anims = skin["anims"]
        if anim not in anims:
            anim = anims[0]
            self._pack_anim = anim
        key = (skin["pack"], anim, round(scale, 2))
        frames = self._anim_cache_get(key)
        if frames is None:
            adir = os.path.join(skin["pack"], anim)
            frames = []
            if Image is not None:
                w, h = self._pet_size()
                # 目标区域留 12px/10px 边距, 与 scale 相乘一次插值到位
                pil = _load_pack_anim(adir, max(1, w - 12), max(1, h - 10))
                frames = [ImageTk.PhotoImage(im, master=self.root) for im in pil]
            if not frames:              # 无 PIL: 至少给一张静态图防崩溃
                ph = tk.PhotoImage(file=os.path.join(adir, "preview.png"),
                                   master=self.root)
                frames = [ph]
            self._anim_cache_put(key, frames)
        return frames

    def _start_anim(self):
        if self._anim_running:
            return
        self._anim_running = True
        self._anim_loop()

    def _anim_loop(self):
        self._anim_running = False
        if self.mode != "pet":
            return
        try:
            if self.root.state() == "withdrawn":
                return
        except tk.TclError:
            return
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        if skin.get("pack"):
            scale = max(0.5, min(2.5, float(self.cfg.get("pet_scale") or 1.0)))
            frames = self._pack_frames(skin, self._pack_anim, scale)
            self._anim_t += 1
            if self._anim_t >= max(1, len(frames)):     # 一个动作播完一轮
                self._anim_t = 0
                self._pack_loops += 1
                # 循环 1 圈后有机会换个动作, 让桌宠更活
                if (self._pack_loops >= 1 and len(skin["anims"]) > 1
                        and random.random() < 0.35):
                    others = [a for a in skin["anims"] if a != self._pack_anim]
                    self._pack_anim = random.choice(others)
                    self._pack_loops = 0
            ms = int(1000 / max(1, skin.get("fps") or 12))
        else:
            self._anim_t = (self._anim_t + 1) % ANIM_FRAMES
            ms = ANIM_MS
        try:
            self._draw_pet_frame()
        except tk.TclError:
            return
        self._anim_running = True
        self.root.after(ms, self._anim_loop)

    # ---------- 棋盘胜负动画(缩小版桌宠播情绪动作) ----------
    def _board_pet_frames(self):
        """棋盘胜负动画帧: 用 _load_pack_anim 按「棋盘一半边长」为目标区域
        直接生成(裁空白铺满), 独立于桌宠窗口尺寸与 pet_scale。"""
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        if not skin.get("pack"):
            return None                 # 仅视频桌宠包支持; canvas/img 兜底不显示
        side = BOARD_W // 2
        key = ("board_pet", skin["pack"], self._pack_anim)
        frames = self._anim_cache_get(key)
        if frames is None:
            adir = os.path.join(skin["pack"], self._pack_anim)
            pil = _load_pack_anim(adir, side, side)
            if not pil:
                return None
            frames = [ImageTk.PhotoImage(im, master=self.root) for im in pil]
            self._anim_cache_put(key, frames)
        return frames

    def _draw_board_pet(self):
        frames = self._board_pet_frames()
        if not frames:
            return
        img = frames[self._bp_anim_t % len(frames)]
        # 棋盘正中心(用户指定): 盖住棋盘区中央
        self.canvas.create_image(SIZE_BOARD[0] / 2, TOPBAR + BOARD_W / 2,
                                 image=img, anchor="center", tags="board_pet")

    def _start_board_anim(self):
        if self._bp_running:
            return
        self._bp_running = True
        self._board_anim_loop()

    def _board_anim_loop(self):
        self._bp_running = False
        if (self.mode != "board" or not self.game_over
                or self.result not in ("win", "lose")):
            return
        try:
            if self.root.state() == "withdrawn":
                return
        except tk.TclError:
            return
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        if not (skin.get("pack") or skin.get("img")):
            return
        self._bp_anim_t += 1
        try:
            self.canvas.delete("board_pet")
            self._draw_board_pet()
        except tk.TclError:
            return
        ms = int(1000 / max(1, skin.get("fps") or 12))
        self._bp_running = True
        self.root.after(ms, self._board_anim_loop)

    def render_board(self):
        w = SIZE_BOARD[0]
        oy = TOPBAR
        # 状态栏: 轮到谁出手
        self.topbar(self.board_status_text(), w)
        # 网格
        for i in range(N):
            p = MARGIN + i * CELL
            self.canvas.create_line(MARGIN, oy + p, w - MARGIN, oy + p, fill=LINE_COLOR)
            self.canvas.create_line(p, oy + MARGIN, p, oy + BOARD_W - MARGIN, fill=LINE_COLOR)
        for sx, sy in ((3, 3), (11, 3), (7, 7), (3, 11), (11, 11)):
            px, py = MARGIN + sx * CELL, oy + MARGIN + sy * CELL
            self.canvas.create_oval(px - 2, py - 2, px + 2, py + 2, fill=LINE_COLOR)
        # 棋子
        for y in range(N):
            for x in range(N):
                c = self.board[y][x]
                if not c:
                    continue
                px, py = MARGIN + x * CELL, oy + MARGIN + y * CELL
                if c == BLACK:
                    self.canvas.create_oval(px - 8, py - 8, px + 8, py + 8,
                                            fill="#111111", outline="#000000")
                else:
                    self.canvas.create_oval(px - 8, py - 8, px + 8, py + 8,
                                            fill="#f5f5f0", outline="#555555")
        if self.last_move:
            px = MARGIN + self.last_move[0] * CELL
            py = oy + MARGIN + self.last_move[1] * CELL
            self.canvas.create_oval(px - 2, py - 2, px + 2, py + 2,
                                    fill="#e04040", outline="")
        if self.win_cells:
            (x0, y0), (x1, y1) = self.win_cells[0], self.win_cells[-1]
            self.canvas.create_line(MARGIN + x0 * CELL, oy + MARGIN + y0 * CELL,
                                    MARGIN + x1 * CELL, oy + MARGIN + y1 * CELL,
                                    fill="#ff5050", width=2)
        # 胜负动画: 缩小版桌宠站在棋盘下半区播情绪动作(占棋盘一半, 用户要求)
        if self.game_over and self.result in ("win", "lose"):
            self._draw_board_pet()
            self._start_board_anim()

        # 底栏三行
        y0 = TOPBAR + BOARD_W
        if not self.playing:
            # 行1: 好友快捷
            fx = 8
            friends = self.cfg["friends"][:4]
            if friends:
                for f in friends:
                    self.btn(fx, y0 + 4, 76, 24, f["name"][:6],
                             (lambda fr: (lambda: self.pick_friend(fr)))(f),
                             fg=BLUE_FG, bg=BLUE_BG, fsize=8)
                    fx += 80
            else:
                self.label(10, y0 + 16, "提示: 在设置-好友里添加对手IP, 可一键选择", fsize=8)
            # 行2: IP输入 + 发起
            self.place_entry(self.entry_ip, 8, y0 + 32, 220, 26)
            self.btn(234, y0 + 32, 82, 26, "发起对局", self.invite,
                     fg=GREEN_FG, bg=GREEN_BG)
            # 行3: 返回 + 本机
            self.btn(8, y0 + 60, 60, 24, "返回", lambda: self.set_mode("pet"))
            self.label(w - 10, y0 + 72, f"本机 {local_ip()}:{self.port}",
                       fg=FG_DIM, fsize=8, anchor="e")
        elif self.game_over:
            if self.result == "win":
                text = "你赢了! 🎉" + (" (对方认输)" if self.peer_resigned else "")
            elif self.result == "lose":
                text = "你认输了" if self.resigned else "你输了 :("
            else:
                text = "🤝 和棋"
            self.btn(8, y0 + 6, 140, 28, "邀新一局", self.restart,
                     fg=GREEN_FG, bg=GREEN_BG)
            self.btn(156, y0 + 6, 90, 28, "返回桌宠", lambda: self.set_mode("pet"))
            self.label(10, y0 + 56, text, fg=FG, fsize=9)
            self.label(w - 10, y0 + 56, f"vs {self.peer_display()}",
                       fg=FG_DIM, fsize=8, anchor="e")
        else:
            # 对局中: 认输 + 邀新一局
            self.btn(8, y0 + 6, 100, 28, "认输", self.resign, fg=RED_FG, bg=RED_BG)
            self.btn(116, y0 + 6, 110, 28, "邀新一局", self.request_new,
                     fg=BLUE_FG, bg=BLUE_BG)
            self.btn(234, y0 + 6, 82, 28,
                     "结束测试" if self.solo else "断开", self.disconnect, fsize=9)
            me = self.cfg["name"]
            opp = self.peer_display()
            info = f"我 {me}·{'黑' if self.my_stone == BLACK else '白'} ｜ 对方 {opp}·{'白' if self.my_stone == BLACK else '黑'}"
            self.label(10, y0 + 50, info, fsize=8)
            if self.new_req_pending:
                self.btn(8, y0 + 50, 90, 24, "接受新局", self.accept_new,
                         fg=GREEN_FG, bg=GREEN_BG, fsize=8)
                self.label(110, y0 + 62, "对方想开新局", fsize=8)

    # ---------- 浏览器设置(本地HTTP服务, 整页布局) ----------
    SETTINGS_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>桌宠控制台</title><style>
*{box-sizing:border-box}
body{font-family:"Microsoft YaHei",sans-serif;background:#eef0f4;margin:0;color:#333}
aside{position:fixed;left:0;top:0;bottom:0;width:220px;background:#fff;box-shadow:2px 0 10px rgba(0,0,0,.05);padding:26px 14px;z-index:10}
aside h1{font-size:17px;margin:0 8px 24px;color:#222}
aside button{display:block;width:100%;text-align:left;padding:11px 14px;margin-bottom:6px;border:0;border-radius:10px;background:none;font-size:14px;color:#555;cursor:pointer}
aside button:hover{background:#f2f4f8}
aside button.active{background:#e8f0ff;color:#3d7dff;font-weight:bold}
main{margin-left:220px;padding:30px 40px;max-width:1080px}
h2{font-size:19px;margin:0 0 6px}
.sub{color:#98a0ab;font-size:13px;margin-bottom:20px}
.card{background:#fff;border-radius:16px;box-shadow:0 2px 10px rgba(0,0,0,.06);padding:22px;margin-bottom:20px}
section{display:none}
section.active{display:block}
input{padding:8px 12px;border:1px solid #dcdfe6;border-radius:9px;font-size:13.5px;outline:none}
input:focus{border-color:#3d7dff}
button.op{padding:8px 18px;border:0;border-radius:9px;background:#3d7dff;color:#fff;cursor:pointer;font-size:13.5px}
button.op:hover{background:#2f66d9}
button.op.del{background:#e5484d}
button.op.mini{padding:4px 12px;font-size:12.5px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.skins{display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:14px}
.skinbox{text-align:center;cursor:pointer;padding:10px 6px;border-radius:12px;border:2px solid transparent;background:#f7f8fa;transition:border-color .12s}
.skinbox:hover{border-color:#b9d0ff}
.skinbox.sel{border-color:#3d7dff;background:#eef4ff}
.skinbox img{width:80px;height:104px;object-fit:contain}
.skinbox .nm{font-size:13px;margin-top:6px;color:#333}
.skinbox .cnt{font-size:11px;color:#98a0ab}
.acts{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:12px;margin-top:16px}
.act{text-align:center;cursor:pointer;padding:8px 4px;border-radius:11px;background:#f7f8fa;border:2px solid transparent;transition:all .12s}
.act:hover{border-color:#3d7dff;background:#eef4ff;transform:translateY(-2px)}
.act img{width:64px;height:84px;object-fit:contain}
.act .nm{font-size:11.5px;color:#444;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td{padding:7px;border-bottom:1px solid #eef0f4}
.win{color:#2a8a3a;font-weight:bold}.lose{color:#a83a3a;font-weight:bold}.draw{color:#888;font-weight:bold}
.muted{color:#98a0ab;font-size:13px}
#toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 22px;border-radius:99px;font-size:13.5px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:99}
#toast.show{opacity:.92}
</style></head><body>
<aside>
<h1>🐾 桌宠控制台</h1>
<button class="active" data-sec="skin" onclick="showSec('skin',this)">🎭 形象与动作</button>
<button data-sec="pets" onclick="showSec('pets',this)">📦 角色包</button>
<button data-sec="name" onclick="showSec('name',this)">✏️ 昵称</button>
<button data-sec="friend" onclick="showSec('friend',this)">👥 好友 IP</button>
<button data-sec="rec" onclick="showSec('rec',this)">📊 战绩统计</button>
<button data-sec="about" onclick="showSec('about',this)">❓ 关于</button>
</aside>
<main>
<section id="sec-skin" class="active">
  <h2>形象与动作</h2>
  <div class="sub">点卡片切换形象; 选中视频形象后, 点下面的动作卡桌宠会立即表演</div>
  <div class="card">
    <h2 style="font-size:15px">桌宠大小</h2>
    <div class="row" style="margin-top:10px">
      <input type="range" id="pscale" min="0.5" max="2.5" step="0.05" style="flex:1;min-width:180px" oninput="document.getElementById('pval').textContent=Math.round(this.value*100)+'%'">
      <span id="pval" style="font-size:13px;width:52px;text-align:right"></span>
      <button class="op" onclick="saveAll()">应用</button>
    </div>
    <div class="muted" style="margin-top:6px">拖到想要的尺寸后点应用, 桌宠立即变大/变小</div>
  </div>
  <div class="card"><div class="skins" id="skins"></div></div>
  <div class="card" id="actcard" style="display:none">
    <h2 style="font-size:15px" id="acttitle"></h2>
    <div class="acts" id="acts"></div>
  </div>
</section>
<section id="sec-pets">
  <h2>角色包下载</h2>
  <div class="sub">精简安装包不带桌宠视频形象, 在这里按需下载(每个角色约 1.2~2GB, 需临时占用约 2 倍磁盘空间); 装完在「形象与动作」里切换</div>
  <div class="card">
    <div id="petsbox"><div class="muted">加载中…</div></div>
    <div id="petsprog" style="display:none;margin-top:14px">
      <div class="muted" id="petsmsg"></div>
      <div style="background:#e8ebf2;border-radius:99px;height:14px;margin-top:8px;overflow:hidden">
        <div id="petsbar" style="background:#3d7dff;height:100%;width:0%;border-radius:99px;transition:width .3s"></div>
      </div>
    </div>
  </div>
</section>
<section id="sec-name">
  <h2>昵称</h2>
  <div class="sub">桌宠身上不显示名字; 昵称用于对弈时向对方标识自己</div>
  <div class="card"><div class="row"><input id="name" style="width:260px"> <button class="op" onclick="saveAll()">保存</button></div></div>
</section>
<section id="sec-friend">
  <h2>好友 IP</h2>
  <div class="sub">添加常一起玩的对手, 桌宠右键菜单里点名字直接约战</div>
  <div class="card"><table id="ftab"></table>
  <div class="row" style="margin-top:14px">备注 <input id="fname" style="width:110px" placeholder="如:小明">
  地址 <input id="faddr" style="width:170px" placeholder="IP:端口">
  <button class="op" onclick="addFriend()">添加</button></div></div>
</section>
<section id="sec-rec">
  <h2>战绩统计</h2>
  <div class="sub">保存在程序目录 config.json, 上限 200 条; 单机试玩不计入</div>
  <div class="card">
    <div class="row">
      <div id="stats" style="font-size:14px"></div>
      <select id="oppfilter" onchange="recFilter=this.value;renderRecs()"
              style="margin-left:auto;padding:6px 10px;border-radius:8px;border:1px solid #dcdfe6;font-size:13px;background:#fff"></select>
    </div>
    <table id="byopp"></table>
    <div style="font-size:14px;font-weight:bold;margin:16px 0 6px">对局明细</div><table id="rtab"></table>
    <div class="row" style="margin-top:16px"><button class="op del" onclick="clearRec()">清空全部记录</button></div>
  </div>
</section>
<section id="sec-about">
  <h2>关于</h2>
  <div class="card"><div class="muted">
    五子棋桌宠 · 双人对战版<br><br>
    · 左键按住桌宠可拖到桌面任意位置, 位置自动记住<br>
    · 右键桌宠弹出菜单: 五子棋 / 单机试玩 / 动作 / 设置 / 隐藏<br>
    · 「单机试玩」= 内置 AI 的测试模式, 不联网不计战绩, 用来验证五子棋功能<br>
    · 「动作」面板可随时让角色表演指定动作<br>
    · 滚轮调节透明度 0%~100%, Ctrl+Q 全局隐藏/呼出<br>
    · 视频形象资源来自大肥鱼桌宠动作包 (CC BY-NC-SA 4.0, 立绘 lokicorvus/crosspet, 仅限个人非商业使用)
  </div></div>
</section>
</main>
<div id="toast"></div>
<script>
let C = null, curSkin = -1;
function showSec(id, btn){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('active'));
  document.getElementById('sec-'+id).classList.add('active');
  document.querySelectorAll('aside button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(id==='pets') loadPets();
}
let toastTimer = null;
function toast(t){ const el=document.getElementById('toast'); el.textContent=t; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove('show'),2200); }
async function load(){
  C = await (await fetch('/api/config')).json();
  document.getElementById('name').value = C.name;
  const sk = document.getElementById('skins'); sk.innerHTML='';
  C.skins.forEach((s,i)=>{
    const d=document.createElement('div'); d.className='skinbox'+(i===C.skin?' sel':'');
    if(s.thumb){ const im=new Image(); im.src='/petimg/'+encodeURI(s.thumb); d.appendChild(im); }
    else if(s.file){ const im=new Image(); im.src='/pets/'+s.file; d.appendChild(im); }
    const n=document.createElement('div'); n.className='nm'; n.textContent=s.name; d.appendChild(n);
    if(s.anims){ const c=document.createElement('div'); c.className='cnt'; c.textContent=s.anims.length+' 个动作'; d.appendChild(c); }
    d.onclick=()=>{ C.skin=i; saveAll(); };
    sk.appendChild(d);
  });
  renderActs();
  const ft=document.getElementById('ftab'); ft.innerHTML='';
  C.friends.forEach((f,i)=>{
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+f.name+'</td><td>'+f.addr+'</td><td style="text-align:right"><button class="op del mini" onclick="delFriend('+i+')">删除</button></td>';
    ft.appendChild(tr);
  });
  if(!C.friends.length) ft.innerHTML='<tr><td class="muted">还没有好友, 在下方添加后可在右键菜单一键约战</td></tr>';
  document.getElementById('pscale').value = C.pet_scale || 1;
  document.getElementById('pval').textContent = Math.round((C.pet_scale||1)*100)+'%';
  const sel = document.getElementById('oppfilter');
  const opps = [...new Set(C.records.map(r=>r.opp))];
  sel.innerHTML = '<option value="__all__">全部对手</option>' +
    opps.map(o=>`<option value="${o}">${o}</option>`).join('');
  sel.value = (recFilter!=='__all__' && opps.includes(recFilter)) ? recFilter : '__all__';
  recFilter = sel.value;
  renderRecs();
}
let recFilter = '__all__';
function renderRecs(){
  const list = recFilter==='__all__' ? C.records : C.records.filter(r=>r.opp===recFilter);
  const st=document.getElementById('stats');
  const cnt={win:0,lose:0,draw:0}; const by={};
  list.forEach(r=>{ cnt[r.r]++; const d=by[r.opp]=by[r.opp]||{win:0,lose:0,draw:0,addr:r.addr}; d[r.r]++; });
  st.textContent = recFilter==='__all__'
    ? `共 ${list.length} 局：${cnt.win} 胜 / ${cnt.lose} 负 / ${cnt.draw} 和`
    : `vs ${recFilter}：共 ${list.length} 局，${cnt.win} 胜 / ${cnt.lose} 负 / ${cnt.draw} 和`;
  const bo=document.getElementById('byopp'); bo.innerHTML='';
  Object.keys(by).forEach(k=>{
    const d=by[k];
    bo.innerHTML += `<tr><td>${k}<span class="muted" style="margin-left:6px">(${d.addr||'-'})</span></td><td>${d.win+d.lose+d.draw}局</td><td>${d.win}胜 ${d.lose}负 ${d.draw}和</td></tr>`;
  });
  if(!Object.keys(by).length) bo.innerHTML='<tr><td class="muted">暂无对局数据</td></tr>';
  const rt=document.getElementById('rtab'); rt.innerHTML='';
  list.slice(-15).reverse().forEach(r=>{
    const cls = r.r==='win'?'win':(r.r==='lose'?'lose':'draw');
    const mark = r.r==='win'?'胜':(r.r==='lose'?'负':'和');
    rt.innerHTML += `<tr><td>${r.t}</td><td>vs ${r.opp}<span class="muted" style="margin-left:6px">(${r.addr||'-'})</span></td><td class="${cls}">${mark}</td></tr>`;
  });
  if(!list.length) rt.innerHTML='<tr><td class="muted">还没有对局记录, 快去邀请好友切磋吧</td></tr>';
}
function renderActs(){
  const card=document.getElementById('actcard'), box=document.getElementById('acts');
  const s = C.skins[C.skin];
  if(!s || !s.anims){ card.style.display='none'; return; }
  card.style.display='block';
  document.getElementById('acttitle').textContent = '🎭 ' + s.name + ' 的动作 (点击触发)';
  box.innerHTML='';
  s.anims.forEach(a=>{
    const d=document.createElement('div'); d.className='act';
    const im=new Image(); im.src='/petimg/'+encodeURI(s.animbase+'/'+a+'/preview.png'); im.loading='lazy';
    d.appendChild(im);
    const n=document.createElement('div'); n.className='nm'; n.textContent=a; d.appendChild(n);
    d.onclick=()=>triggerAnim(a);
    box.appendChild(d);
  });
}
async function triggerAnim(a){
  const res = await fetch('/api/trigger',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({anim:a})});
  const j = await res.json();
  if(j.ok) toast('🎭 桌宠正在表演: ' + a); else toast('触发失败');
}
async function saveAll(){
  C.name = document.getElementById('name').value.trim() || C.name;
  const ps = parseFloat(document.getElementById('pscale').value);
  if(!isNaN(ps)) C.pet_scale = ps;
  const res = await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:C.name,skin:C.skin,friends:C.friends,pet_scale:C.pet_scale})});
  const j = await res.json(); if(j.ok){ toast('已保存, 桌宠自动生效'); await load(); }
}
async function addFriend(){
  const nm=document.getElementById('fname').value.trim(), ad=document.getElementById('faddr').value.trim();
  if(!nm||!ad){alert('请填写备注和地址');return;}
  C.friends.push({name:nm,addr:ad});
  document.getElementById('fname').value=''; document.getElementById('faddr').value='';
  await saveAll();
}
async function delFriend(i){ C.friends.splice(i,1); await saveAll(); }
async function clearRec(){ if(!confirm('确定清空全部对局记录?'))return;
  await fetch('/api/clear_records',{method:'POST'}); await load(); }
let petsTimer = null;
async function loadPets(){
  const box = document.getElementById('petsbox');
  try{
    const j = await (await fetch('/api/pets_catalog')).json();
    if(!j.ok){ box.innerHTML = '<div class="muted">'+(j.error||'下载源未配置')+'</div>'; return; }
    if(j.busy){ pollPets(); return; }
    box.innerHTML = '';
    if(!j.roles.length){ box.innerHTML = '<div class="muted">下载源里还没有角色包</div>'; return; }
    j.roles.forEach(r=>{
      const d=document.createElement('div');
      d.style.cssText='display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #eef0f4';
      d.innerHTML = `<div><b>${r.name}</b> <span class="muted">${r.dir} · ${r.mb} MB${r.installed?' · 已安装 ✓':''}</span></div>`
        + (r.installed
           ? '<button class="op mini" disabled style="background:#9bb8e8">已安装</button>'
           : `<button class="op" onclick="dlRole('${r.dir}')">下载安装</button>`);
      box.appendChild(d);
    });
  }catch(e){ box.innerHTML = '<div class="muted">加载失败</div>'; }
}
async function dlRole(dir){
  const j = await (await fetch('/api/pets_download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dir:dir})})).json();
  if(!j.ok){ toast(j.error||'无法开始下载'); return; }
  document.getElementById('petsprog').style.display='block';
  pollPets();
}
async function pollPets(){
  clearTimeout(petsTimer);
  const j = await (await fetch('/api/pets_status')).json();
  document.getElementById('petsmsg').textContent = j.msg || '';
  document.getElementById('petsbar').style.width = (j.total? Math.round(j.got/j.total*100):0)+'%';
  if(j.phase==='done'){
    document.getElementById('petsprog').style.display='none';
    toast('角色包已安装, 桌宠换新形象啦'); await load(); await loadPets(); return;
  }
  if(j.phase==='error'){ toast('下载失败: '+(j.msg||'')); await loadPets(); return; }
  if(j.phase!=='idle') petsTimer = setTimeout(pollPets, 800);
}
load();
</script></body></html>"""

    def _right_press(self, e):
        """右键: 桌宠待机时在旁边弹出卡片菜单, 其他模式作为拖动"""
        self._touch()
        if self.mode == "pet":
            self.toggle_menu()
        else:
            self._drag_begin(e)

    # ---------- 侧边卡片菜单(挂桌宠旁边, 桌宠保持可见) ----------
    # 风格参照"大肥鱼桌宠"设置弹窗: 白圆角卡片 + emoji条目 + › + 蓝色胶囊按钮
    MENU_BG = "#ffffff"
    MENU_ROW = "#f7f8fa"
    MENU_ROW_HOVER = "#eef0f4"
    MENU_BORDER = "#e5e7eb"
    MENU_BLUE = "#3d7dff"
    MENU_BLUE_HOVER = "#2f66d9"
    MENU_RED = "#e5484d"

    def toggle_menu(self):
        if self.menu_win is not None:
            self.close_menu()
        else:
            self.open_menu()

    def close_menu(self):
        self._close_anim_picker()
        if self.menu_win is not None:
            try:
                self.menu_win.destroy()
            except Exception:
                pass
            self.menu_win = None

    def open_menu(self):
        if self.menu_win is not None:
            return
        mw = tk.Toplevel(self.root)
        self.menu_win = mw
        mw.overrideredirect(True)
        mw.attributes("-topmost", True)
        mw.configure(bg=self.MENU_BG)
        mw.bind("<Motion>", lambda e: self._touch())
        mw.bind("<Escape>", lambda e: self.close_menu())

        W, PAD = 236, 12
        friends = self.cfg["friends"]
        px, py = self._pos
        x = px + SIZE_PET[0] + 6
        if x + W > mw.winfo_screenwidth():
            x = max(0, px - W - 6)

        cv = tk.Canvas(mw, width=W, height=400, bg=self.MENU_BG,
                       highlightthickness=0, bd=0)
        cv.pack()

        def rr(x1, y1, x2, y2, r, fill, tags=()):
            """圆角矩形: 两块矩形 + 四个饼形角"""
            cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill,
                                outline=fill, tags=tags)
            cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill,
                                outline=fill, tags=tags)
            for bx, by, st in ((x1, y1, 90), (x2 - 2 * r, y1, 0),
                               (x2 - 2 * r, y2 - 2 * r, 270),
                               (x1, y2 - 2 * r, 180)):
                cv.create_arc(bx, by, bx + 2 * r, by + 2 * r, start=st,
                              extent=90, style=tk.PIESLICE, fill=fill,
                              outline=fill, tags=tags)

        def item(y, h, icon, txt, cmd, fg="#333333", bg=None, radius=10):
            """一条 emoji + 文字 + › 的圆角条目, 悬停变色"""
            bg = bg or self.MENU_ROW
            stag = f"s{y}"
            ttag = f"t{y}"
            rr(PAD, y, W - PAD, y + h, radius, bg, stag)
            cv.create_text(PAD + 13, y + h / 2, text=icon,
                           font=("Segoe UI Emoji", 11), anchor="w",
                           tags=ttag, fill=fg)
            cv.create_text(PAD + 40, y + h / 2, text=txt,
                           font=("Microsoft YaHei", 10), anchor="w",
                           tags=ttag, fill=fg)
            cv.create_text(W - PAD - 14, y + h / 2, text="›",
                           fill="#b8bcc6", font=("Microsoft YaHei", 11),
                           tags=ttag)
            cv.tag_bind(stag, "<Button-1>",
                        lambda e: (self._touch(), cmd()))
            cv.tag_bind(stag, "<Enter>",
                        lambda e: cv.itemconfig(stag, fill=self.MENU_ROW_HOVER))
            cv.tag_bind(stag, "<Leave>",
                        lambda e: cv.itemconfig(stag, fill=bg))
            # 文字/箭头是最上层命中项, 必须同样绑定, 否则点文字无反应
            cv.tag_bind(ttag, "<Button-1>",
                        lambda e: (self._touch(), cmd()))
            cv.tag_bind(ttag, "<Enter>",
                        lambda e: cv.itemconfig(stag, fill=self.MENU_ROW_HOVER))
            cv.tag_bind(ttag, "<Leave>",
                        lambda e: cv.itemconfig(stag, fill=bg))

        # 卡片圆角描边(底层灰 + 上层白, 形成 1px 圆角边框)
        rr(0, 0, W, 400, 16, self.MENU_BORDER, "card")
        rr(1, 1, W - 1, 398, 15, self.MENU_BG, "card")

        # 标题: 昵称 + 右上角 ✕
        cv.create_text(PAD + 4, 18, text=f"👋 {self.cfg['name']}",
                       font=("Microsoft YaHei", 12, "bold"), anchor="w",
                       fill="#333333")
        xc = cv.create_text(W - PAD - 2, 18, text="✕", fill="#b0b4bf",
                            font=("Microsoft YaHei", 11))
        cv.tag_bind(xc, "<Button-1>", lambda e: self.close_menu())

        # 主功能条目(当前是视频桌宠时加"动作"面板入口)
        y = 40
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        rows = [
            ("♟️", "五子棋", lambda: self._menu_goto_board()),
            ("🎮", "单机试玩", self.start_solo),
            ("🀄", "象棋(开发中)", lambda: self.set_toast("象棋敬请期待~")),
            ("⚙️", "设置", self.open_settings),
            ("🙈", "隐藏", self.hide),
        ]
        if skin.get("pack"):
            rows.insert(2, ("🎭", "动作", self._open_anim_picker))
        for icon, txt, cmd in rows:
            item(y, 36, icon, txt, cmd)
            y += 44

        # 好友分组
        cv.create_text(PAD + 4, y + 8, text=f"👥 好友 ({len(friends)})",
                       font=("Microsoft YaHei", 9), anchor="w", fill="#9aa0ab")
        y += 24
        if friends:
            for f in friends[:8]:
                item(y, 30, "🤝", f"切磋 · {f['name']}",
                     lambda fr=f: self._menu_invite(fr), radius=9)
                y += 36
        else:
            cv.create_text(PAD + 8, y + 14,
                           text="浏览器设置里添加好友后,\n点名字直接约战",
                           font=("Microsoft YaHei", 9), anchor="w",
                           fill="#b0b4bf", justify="left")
            y += 40
        y += 4

        # 退出程序(红字条目, 无 ›)
        item(y, 34, "🚪", "退出程序", self.quit_app, fg=self.MENU_RED)
        y += 42

        # 右下角蓝色胶囊 关闭 按钮
        bw, bh = 72, 30
        btag = f"btn{y}"
        btxt = f"btnt{y}"
        rr(W - PAD - bw, y, W - PAD, y + bh, bh // 2, self.MENU_BLUE, btag)
        cv.create_text(W - PAD - bw / 2, y + bh / 2, text="关闭",
                       font=("Microsoft YaHei", 10), fill="#ffffff",
                       tags=btxt)
        cv.tag_bind(btag, "<Button-1>", lambda e: self.close_menu())
        cv.tag_bind(btxt, "<Button-1>", lambda e: self.close_menu())
        cv.tag_bind(btag, "<Enter>",
                    lambda e: cv.itemconfig(btag, fill=self.MENU_BLUE_HOVER))
        cv.tag_bind(btag, "<Leave>",
                    lambda e: cv.itemconfig(btag, fill=self.MENU_BLUE))
        cv.tag_bind(btxt, "<Enter>",
                    lambda e: cv.itemconfig(btag, fill=self.MENU_BLUE_HOVER))
        cv.tag_bind(btxt, "<Leave>",
                    lambda e: cv.itemconfig(btag, fill=self.MENU_BLUE))

        # 高度按实际内容计算, 避免底部被截断
        H = y + bh + 12
        cv.configure(height=H)
        # 重画卡片边框到实际高度
        cv.delete("card")
        rr(0, 0, W, H, 16, self.MENU_BORDER, "card")
        rr(1, 1, W - 1, H - 1, 15, self.MENU_BG, "card")
        # 边框层要在最上面内容之下: 提到所有条目之下
        cv.tag_lower("card")
        # 双向夹紧屏幕, 防止靠边时菜单超出桌面显示不全(用户反馈)
        x = min(max(x, 0), max(0, mw.winfo_screenwidth() - W - 8))
        py = min(max(py, 0), max(0, mw.winfo_screenheight() - H - 8))
        mw.geometry(f"{W}x{H}+{x}+{py}")

    def _menu_goto_board(self):
        self.close_menu()
        self.set_mode("board")

    # ---------- 单机试玩(游戏测试模式: 内置简单 AI, 无需联网) ----------
    def start_solo(self):
        if self.playing:
            self.set_toast("当前对局还没结束")
            return
        self.close_menu()
        self.solo = True
        self.playing = True
        self.connecting = False
        self.peer_name = "单机AI"
        self.peer_remark = ""
        self.peer_addr = "本机"
        self.board = [[0] * N for _ in range(N)]
        self.game_over = False
        self.result = None
        self.resigned = self.peer_resigned = False
        self.awaiting_new = False
        self.new_req_pending = False
        self.win_cells = None
        self.last_move = None
        self.my_stone = random.choice((BLACK, WHITE))
        self.turn = BLACK
        self.set_mode("board")
        self.set_toast("单机试玩: 你执%s"
                       % ("黑(先手)" if self.my_stone == BLACK else "白(AI先手)"))
        if self.turn != self.my_stone:
            self.root.after(600, self._solo_move)

    def _solo_after(self):
        """轮到 AI 时安排一手(延迟一点, 像在思考)"""
        if (self.solo and self.playing and not self.game_over
                and self.turn != self.my_stone):
            self.root.after(random.randint(400, 900), self._solo_move)

    def _solo_move(self):
        if not (self.solo and self.playing and not self.game_over):
            return
        if self.turn == self.my_stone:
            return
        x, y = self._solo_pick()
        self.apply_move(x, y, self.turn)

    def _line_cnt(self, x, y, dx, dy, stone):
        """假设 (x,y) 落 stone, 统计该方向连子数与两端开放数"""
        cnt, opens = 1, 0
        for sgn in (1, -1):
            i, j = x + dx * sgn, y + dy * sgn
            while 0 <= i < N and 0 <= j < N and self.board[j][i] == stone:
                cnt += 1
                i += dx * sgn
                j += dy * sgn
            if 0 <= i < N and 0 <= j < N and self.board[j][i] == 0:
                opens += 1
        return cnt, opens

    def _pt_score(self, x, y, stone):
        """在 (x,y) 落 stone 的进攻价值(简化棋型评分)"""
        total = 0
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            cnt, opens = self._line_cnt(x, y, dx, dy, stone)
            if cnt >= 5:
                total += 1000000        # 连五
            elif cnt == 4:
                total += 50000 if opens == 2 else 8000      # 活四/冲四
            elif cnt == 3:
                total += 3000 if opens == 2 else 300        # 活三/眠三
            elif cnt == 2:
                total += 200 if opens == 2 else 30
            else:
                total += 5 * opens
        return total

    def _solo_pick(self):
        """AI 选点: 进攻分 + 0.9×防守权重, 取最高分"""
        cands = set()
        has = False
        for yy in range(N):
            for xx in range(N):
                if self.board[yy][xx]:
                    has = True
                    for dyy in (-2, -1, 0, 1, 2):
                        for dxx in (-2, -1, 0, 1, 2):
                            nx, ny = xx + dxx, yy + dyy
                            if 0 <= nx < N and 0 <= ny < N \
                                    and not self.board[ny][nx]:
                                cands.add((nx, ny))
        if not cands:
            return N // 2, N // 2
        other = 3 - self.turn
        order = list(cands)
        random.shuffle(order)           # 同分随机, AI 不走死板棋
        best, bs = order[0], -1.0
        for x, y in order:
            s = (self._pt_score(x, y, self.turn)
                 + 0.9 * self._pt_score(x, y, other))
            if s > bs:
                best, bs = (x, y), s
        return best

    def _menu_invite(self, f):
        """点好友直接发起切磋"""
        if self.playing or self.connecting:
            self.close_menu()
            self.set_toast("当前对局还没结束")
            return
        self.close_menu()
        self.set_mode("board")
        self.entry_ip.delete(0, "end")
        self.entry_ip.insert(0, f["addr"])
        self.peer_remark = f["name"]
        self.set_toast(f"正在邀请 {f['name']} 切磋…")
        self.invite()

    # ---------- 动作触发(桌宠视频皮肤的动作库) ----------
    def trigger_anim(self, name):
        """让桌宠立即表演指定动作(右键菜单/网页设置/测试共用)"""
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        if not skin.get("pack") or name not in skin["anims"]:
            return False
        if self.playing:
            self.set_toast("对局中不能切动作")
            return False
        self._pack_anim = name
        self._pack_loops = 0
        if self.mode != "pet":
            self.set_mode("pet")       # 会重置 _anim_t 并重绘
        else:
            self._anim_t = 0
            self._draw_pet_frame()
        self._start_anim()             # 确保动画链在跑(_anim_running 防重复)
        self.set_toast(f"🎭 {name}")
        return True

    def _open_anim_picker(self):
        """动作选择窗: 列出当前角色全部动作, 点击即触发"""
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        if not skin.get("pack"):
            self.set_toast("当前形象没有动作库")
            return
        self.close_menu()
        pw = tk.Toplevel(self.root)
        self.anim_win = pw
        pw.overrideredirect(True)
        pw.attributes("-topmost", True)
        pw.configure(bg=self.MENU_BG)
        pw.bind("<Escape>", lambda e: self._close_anim_picker())

        W2, PAD2, ROWH = 210, 12, 32
        anims = skin["anims"]
        px, py = self._pos
        x = px + SIZE_PET[0] + 6
        if x + W2 > pw.winfo_screenwidth():
            x = max(0, px - W2 - 6)

        cv = tk.Canvas(pw, width=W2, height=340, bg=self.MENU_BG,
                       highlightthickness=0, bd=0)
        cv.pack()

        def rr(x1, y1, x2, y2, r, fill, tags=()):
            cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill,
                                outline=fill, tags=tags)
            cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill,
                                outline=fill, tags=tags)
            for bx, by, st in ((x1, y1, 90), (x2 - 2 * r, y1, 0),
                               (x2 - 2 * r, y2 - 2 * r, 270),
                               (x1, y2 - 2 * r, 180)):
                cv.create_arc(bx, by, bx + 2 * r, by + 2 * r, start=st,
                              extent=90, style=tk.PIESLICE, fill=fill,
                              outline=fill, tags=tags)

        # 窗口高度按内容算, 上限 340(超出滚动), 再夹紧屏幕
        total = 36 + len(anims) * ROWH + 10
        VH = max(120, min(total + 8, 340,
                          pw.winfo_screenheight() - 60))
        rr(0, 0, W2, VH, 16, self.MENU_BORDER, "card")
        rr(1, 1, W2 - 1, VH - 1, 15, self.MENU_BG, "card")
        cv.tag_lower("card")

        # 标题: 当前角色名 + 动作数 + ✕
        cv.create_text(PAD2 + 4, 18, text=f"🎭 {skin['name']} ({len(anims)})",
                       font=("Microsoft YaHei", 11, "bold"), anchor="w",
                       fill="#333333")
        xc = cv.create_text(W2 - PAD2 - 2, 18, text="✕", fill="#b0b4bf",
                            font=("Microsoft YaHei", 11))
        cv.tag_bind(xc, "<Button-1>", lambda e: self._close_anim_picker())

        # 可滚动动作列表(矩形与文字分离 tag: hover 只改底色, 否则文字也会变色成"空白")
        ly = 36
        for a in anims:
            rtag, ttag = f"r{ly}", f"t{ly}"
            rr(PAD2, ly, W2 - PAD2, ly + ROWH - 6, 9, self.MENU_ROW, rtag)
            cv.create_text(PAD2 + 12, ly + (ROWH - 6) / 2, text=a,
                           font=("Microsoft YaHei", 10), anchor="w",
                           fill="#333333", tags=ttag)
            for tg in (rtag, ttag):
                cv.tag_bind(tg, "<Button-1>",
                            lambda e, nm=a: (self._close_anim_picker(),
                                             self.trigger_anim(nm)))
                cv.tag_bind(tg, "<Enter>",
                            lambda e, tg=rtag: cv.itemconfig(
                                tg, fill=self.MENU_ROW_HOVER))
                cv.tag_bind(tg, "<Leave>",
                            lambda e, tg=rtag: cv.itemconfig(
                                tg, fill=self.MENU_ROW))
            ly += ROWH
        # 列表区: 窗口高度夹紧屏幕, 防止超出桌面
        cv.configure(scrollregion=(0, 0, W2, total))
        cv.configure(height=VH)
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))
        py = min(max(py, 0), max(0, pw.winfo_screenheight() - VH - 8))
        pw.geometry(f"{W2}x{VH}+{x}+{py}")

    def _close_anim_picker(self):
        if getattr(self, "anim_win", None) is not None:
            try:
                self.anim_win.destroy()
            except Exception:
                pass
            self.anim_win = None

    def open_settings(self):
        """在默认浏览器打开设置页"""
        port = self._ensure_settings_server()
        if port:
            webbrowser.open(f"http://127.0.0.1:{port}/")
            self.set_toast("设置已在浏览器打开")

    def _ensure_settings_server(self):
        if self._srv_port:
            return self._srv_port
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/":
                    data = app.SETTINGS_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path == "/api/config":
                    with app.cfg_lock:
                        snap = {
                            "name": app.cfg["name"],
                            "skin": app.cfg["skin"],
                            "pet_scale": app.cfg.get("pet_scale", 1.0),
                            "skins": [{"name": s["name"], "file": s["file"],
                                       "thumb": s.get("thumb"),
                                       "animbase": s.get("animbase"),
                                       "anims": s.get("anims")}
                                      for s in app.skins],
                            "friends": list(app.cfg["friends"]),
                            "records": list(app.cfg["records"]),
                        }
                    self._json(snap)
                elif self.path == "/api/pets_catalog":
                    if not PET_CATALOG_URL:
                        self._json({"ok": False,
                                    "error": "下载源未配置(精简包未内置 catalog 地址)"})
                    else:
                        try:
                            cat = app._pets_catalog_get()
                            roles = []
                            for r in cat.get("roles", []):
                                d = str(r.get("dir") or "")
                                pdir = os.path.join(ANIMS_DIR, d)
                                installed = (os.path.isdir(pdir) and
                                             os.path.isfile(
                                                 os.path.join(pdir, "pack.json")))
                                roles.append({
                                    "dir": d,
                                    "name": str(r.get("name") or d),
                                    "mb": round(int(r.get("bytes") or 0) / 1e6),
                                    "installed": installed})
                            with app._pets_lock:
                                busy = app._pets_state["phase"] not in (
                                    "idle", "done", "error")
                            self._json({"ok": True, "roles": roles,
                                        "busy": busy})
                        except Exception as e:
                            self._json({"ok": False,
                                        "error": f"下载源不可达: {e}"[:120]})
                elif self.path == "/api/pets_status":
                    with app._pets_lock:
                        snap = dict(app._pets_state)
                    self._json(snap)
                elif self.path.startswith("/petimg/"):
                    # 视频桌宠动作预览图(pets/anims/... 下的 png)
                    rel = unquote(self.path[len("/petimg/"):])
                    fp = os.path.normpath(os.path.join(PETS_DIR, rel))
                    base = os.path.normpath(PETS_DIR)
                    if (fp.startswith(base + os.sep) and fp.endswith(".png")
                            and os.path.exists(fp)):
                        with open(fp, "rb") as f:
                            data = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    else:
                        self._json({"error": "not found"}, 404)
                elif self.path.startswith("/pets/"):
                    fn = os.path.basename(self.path[len("/pets/"):])
                    fp = os.path.join(PETS_DIR, fn)
                    if os.path.exists(fp) and fn.endswith(".png"):
                        with open(fp, "rb") as f:
                            data = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    else:
                        self._json({"error": "not found"}, 404)
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    data = json.loads(self.rfile.read(n).decode("utf-8"))
                except Exception:
                    self._json({"ok": False, "error": "bad json"}, 400)
                    return
                if self.path == "/api/config":
                    app._apply_web_config(data)
                    self._json({"ok": True})
                elif self.path == "/api/trigger":
                    # 网页点动作 → 事件队列 → UI 线程让桌宠表演
                    app.eq.put(("trigger", str(data.get("anim") or "")[:40]))
                    self._json({"ok": True})
                elif self.path == "/api/pets_download":
                    d = str(data.get("dir") or "").strip()
                    if not d or d != os.path.basename(d) or d.startswith("."):
                        self._json({"ok": False, "error": "非法角色名"}, 400)
                        return
                    try:
                        cat = app._pets_catalog_get()
                        if not any(r.get("dir") == d
                                   for r in cat.get("roles", [])):
                            self._json({"ok": False, "error": "没有这个角色"})
                            return
                    except Exception as e:
                        self._json({"ok": False,
                                    "error": f"下载源不可达: {e}"[:120]})
                        return
                    ok, err = app._pets_start_download(d)
                    self._json({"ok": ok, "error": err})
                elif self.path == "/api/clear_records":
                    with app.cfg_lock:
                        app.cfg["records"] = []
                    app.save_cfg()
                    self._json({"ok": True})
                else:
                    self._json({"error": "not found"}, 404)

        class _SettingsServer(ThreadingHTTPServer):
            # Windows 下 SO_REUSEADDR 允许双绑定(与常驻旧进程同端口时请求会被
            # 旧进程截走), 必须禁用复用让 bind 真失败, 才能换到下一个端口
            allow_reuse_address = False

        for port in range(27192, 27212):
            try:
                srv = _SettingsServer(("127.0.0.1", port), Handler)
            except OSError:
                continue
            srv.daemon_threads = True
            self._srv = srv
            self._srv_port = port
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return port
        self.set_toast("⚠ 设置服务端口被占用")
        return 0

    # ---------- 角色包在线下载(GitHub Release) ----------
    def _pets_open_url(self, url, timeout=30):
        """直连打开 URL(绕过系统代理, 防本机代理劫持), 返回 bytes"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.addheaders = [("User-Agent", "chessboard-desktop-pet")]
        with opener.open(url, timeout=timeout) as r:
            return r.read()

    def _pets_catalog_get(self, force=False):
        """拉取并缓存角色包目录(catalog.json), 支持 moved_to 跳到新版目录"""
        now = time.time()
        if (not force and self._pets_catalog
                and now - self._pets_catalog_at < 300):
            return self._pets_catalog
        url = PET_CATALOG_URL
        cat = None
        for _ in range(3):          # 最多跟 3 跳 moved_to
            cat = json.loads(self._pets_open_url(url, timeout=20).decode("utf-8"))
            nxt = str(cat.get("moved_to") or "")
            if nxt and nxt != url:
                url = nxt
                continue
            break
        cat["_fetched_url"] = url
        self._pets_catalog = cat
        self._pets_catalog_at = now
        return cat

    def _pets_start_download(self, role_dir):
        with self._pets_lock:
            if self._pets_state["phase"] not in ("idle", "done", "error"):
                return False, "已有下载任务在进行中"
            self._pets_state.update(phase="prepare", dir=role_dir,
                                    got=0, total=0, msg="准备下载…")
        threading.Thread(target=self._pets_download_thread, args=(role_dir,),
                         daemon=True).start()
        return True, ""

    def _pets_download_thread(self, role_dir):
        st = self._pets_state
        tmp_dir = os.path.join(os.path.dirname(PETS_DIR), "_pets_dl")
        tmp_zip = os.path.join(tmp_dir, f"{role_dir}.zip")
        try:
            cat = self._pets_catalog_get(force=True)
            entry = next((r for r in cat.get("roles", [])
                          if r.get("dir") == role_dir), None)
            if not entry:
                raise RuntimeError("下载源里没有这个角色")
            url = cat["base"].rstrip("/") + "/" + str(entry["file"])
            total = int(entry.get("bytes") or 0)
            want_sha = str(entry.get("sha256") or "")

            with self._pets_lock:
                st.update(phase="download", got=0, total=total, msg="连接下载源…")
            os.makedirs(tmp_dir, exist_ok=True)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            opener.addheaders = [("User-Agent", "chessboard-desktop-pet")]
            h = hashlib.sha256()
            got = 0
            with opener.open(url, timeout=60) as r, open(tmp_zip, "wb") as f:
                if not total:
                    total = int(r.headers.get("Content-Length") or 0)
                    with self._pets_lock:
                        st["total"] = total
                last_ui = 0.0
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if time.time() - last_ui > 0.5:   # 半秒刷一次进度
                        last_ui = time.time()
                        with self._pets_lock:
                            st.update(got=got, total=total,
                                      msg=f"下载中 {got/1e9:.2f}/{total/1e9:.2f} GB")
            if want_sha and h.hexdigest() != want_sha:
                raise RuntimeError("文件校验不符(下载不完整), 请重试")

            with self._pets_lock:
                st.update(phase="extract", msg="解压安装中…(约 1~3 分钟)")
            prefix = f"pets/anims/{role_dir}/"
            with zipfile.ZipFile(tmp_zip) as zf:
                names = [i.filename.replace("\\", "/") for i in zf.infolist()
                         if not i.is_dir()]
                bad = [n for n in names
                       if not n.startswith(prefix) or ".." in n.split("/")
                       or n.startswith("/")]
                if bad:
                    raise RuntimeError(f"压缩包内容异常: {bad[:3]}")
                dst = os.path.join(ANIMS_DIR, role_dir)
                if os.path.isdir(dst):
                    shutil.rmtree(dst)      # 重装 = 覆盖旧角色包
                os.makedirs(dst)
                zf.extractall(os.path.dirname(PETS_DIR))
            os.remove(tmp_zip)
        except Exception as e:
            try:
                if os.path.isfile(tmp_zip):
                    os.remove(tmp_zip)
            except OSError:
                pass
            with self._pets_lock:
                st.update(phase="error", msg=str(e)[:120])
            self.eq.put(("pets_failed", str(e)[:80]))
            return
        with self._pets_lock:
            st.update(phase="done", msg="安装完成")
        self.eq.put(("pets_installed", role_dir))

    def _pets_after_install(self, role_dir):
        """角色包装完: 重载形象列表; 原来只有 canvas 兜底形象时切到新形象"""
        self.skins = load_skin_list()
        with self.cfg_lock:
            cur = self.cfg.get("skin", 0)
            if not (0 <= cur < len(self.skins)):
                self.cfg["skin"] = 0
            elif all(self.skins[cur].get(k) is None
                     for k in ("pack", "img", "file")):
                # canvas 兜底 -> 找默认角色(claude), 找不到就选第一个
                idx = next((i for i, s in enumerate(self.skins)
                            if os.path.basename(s.get("animbase") or "")
                            == DEFAULT_PET_ROLE), 0)
                self.cfg["skin"] = idx
            self.save_cfg()
        self._anim_frames.clear()
        self._anim_lru.clear()
        self._apply_size()
        self.render()
        nm = next((s["name"] for s in self.skins
                   if os.path.basename(s.get("animbase") or "") == role_dir),
                  role_dir)
        self.set_toast(f"🎉 {nm} 已安装, 桌宠换新形象啦")

    def _apply_web_config(self, data):
        """浏览器保存的配置(昵称/形象/好友)"""
        with self.cfg_lock:
            nm = str(data.get("name", self.cfg["name"])).strip()[:12]
            if nm:
                self.cfg["name"] = nm
            skin = data.get("skin")
            if isinstance(skin, int) and 0 <= skin < len(self.skins):
                self.cfg["skin"] = skin
            friends = data.get("friends")
            if isinstance(friends, list):
                cleaned = []
                for f in friends[:20]:
                    if isinstance(f, dict) and valid_addr(str(f.get("addr", ""))):
                        cleaned.append({"name": (str(f.get("name", "")).strip() or "好友")[:8],
                                        "addr": str(f.get("addr", "")).strip()[:40]})
                self.cfg["friends"] = cleaned
            ps = data.get("pet_scale")
            try:
                ps = float(ps)
                if 0.5 <= ps <= 2.5:
                    self.cfg["pet_scale"] = round(ps, 2)
            except (TypeError, ValueError):
                pass
            self.save_cfg()
        self.eq.put(("rescale",))

    def pick_friend(self, f):
        self.entry_ip.delete(0, "end")
        self.entry_ip.insert(0, f["addr"])
        self.peer_remark = f["name"]
        self.set_toast(f"已选择 {f['name']}, 点[发起对局]")

    # ---------- 状态文本 ----------
    def peer_display(self):
        return self.peer_name or self.peer_remark or (self.peer_addr or "对手")

    def board_status_text(self):
        if not self.playing:
            return "五子棋 · 输入对方IP或点好友发起"
        bn = self.cfg["name"] if self.my_stone == BLACK else self.peer_display()
        wn = self.peer_display() if self.my_stone == BLACK else self.cfg["name"]
        if self.game_over:
            return {"win": "你赢了 🎉", "lose": "你输了", "draw": "和棋"}.get(self.result, "对局结束")
        if self.turn == self.my_stone:
            return f"轮到你({self.cfg['name']})出子"
        cur = "黑" if self.turn == BLACK else "白"
        who = bn if self.turn == BLACK else wn
        return f"等对方出子… ({cur}·{who})"

    # ---------- 输入路由 ----------
    def _route_click(self, e):
        self._touch()
        if self.mode == "pet":
            # 左键按住=拖动桌宠(可随意摆放, 松手记住位置); 单击无动作
            self._drag_begin(e)
            return
        lx = e.x_root - self.root.winfo_rootx()
        ly = e.y_root - self.root.winfo_rooty()
        w = self.canvas.winfo_width() or SIZE_BOARD[0]
        if ly < TOPBAR:
            if lx > w - 30:
                self.hide()
            else:
                self._drag_begin(e)
            return
        for x0, y0, x1, y1, fn, widget in self.hotspots:
            if x0 <= lx < x1 and y0 <= ly < y1:
                if widget is not None:
                    widget.focus_set()
                elif fn:
                    fn()
                return
        # 棋盘区域落子
        if self.mode == "board":
            self.on_click_xy(lx, ly)

    def on_click_xy(self, lx, ly):
        if not self.playing or self.game_over or self.turn != self.my_stone:
            return
        x = round((lx - MARGIN) / CELL)
        y = round((ly - TOPBAR - MARGIN) / CELL)
        if not (0 <= x < N and 0 <= y < N):
            return
        if abs(lx - (MARGIN + x * CELL)) > CELL * 0.45:
            return
        if abs(ly - (TOPBAR + MARGIN + y * CELL)) > CELL * 0.45:
            return
        if self.board[y][x]:
            return
        self.apply_move(x, y, self.my_stone)
        self.send_msg({"t": "move", "x": x, "y": y})

    # ---------- 拖动 ----------
    def _drag_begin(self, e):
        self._dx = e.x_root - self._pos[0]
        self._dy = e.y_root - self._pos[1]
        self._dragging = True
        self._drag_moved = False

    def _drag_end(self, _):
        self._dragging = False
        # 桌宠被拖走后记住位置, 重启恢复(用户要求随便放桌面哪里)
        if (self.mode == "pet" and getattr(self, "_drag_moved", False)):
            self.cfg["pet_pos"] = [self._pos[0], self._pos[1]]
            self.save_cfg()

    def _drag_move(self, e):
        if not getattr(self, "_dragging", False):
            return
        self._drag_moved = True
        self._pos = (e.x_root - self._dx, e.y_root - self._dy)
        g = f"+{self._pos[0]}+{self._pos[1]}"
        self.root.geometry(g)
        self.iw.geometry(g)

    def _on_wheel(self, e):
        self._touch()
        step = 0.05 if e.delta > 0 else -0.05
        self.alpha = max(ALPHA_MIN, min(ALPHA_MAX, self.alpha + step))
        self.root.attributes("-alpha", round(self.alpha, 2))
        self.set_toast(f"透明度 {int(self.alpha * 100)}%")

    # ---------- 对局 ----------
    def apply_move(self, x, y, stone):
        self.board[y][x] = stone
        self.last_move = (x, y)
        cells = check_win(self.board, x, y)
        if cells:
            self.win_cells = cells
            self._finish("win" if stone == self.my_stone else "lose")
        elif board_full(self.board):
            self._finish("draw")
        else:
            self.turn = WHITE if stone == BLACK else BLACK
        self.render()
        if self.solo and not self.game_over and self.turn != self.my_stone:
            self._solo_after()          # 玩家落子后轮到 AI

    def _finish(self, result):
        self.game_over = True
        self.result = result
        self._pick_mood_anim(result)
        self._bp_anim_t = 0            # 棋盘胜负动画从头播
        self._record(result)
        self.render()

    def _pick_mood_anim(self, result):
        """对局结束后按输赢挑一个情绪动作(等 5 秒空闲自动回桌宠时播放)。
        动作名因角色包而异, 用关键词模糊匹配; 匹配不到时赢棋兜底随机换、
        输棋保持原动作(不欢快乱跳)。直接改 _pack_anim, 不切模式不弹提示。"""
        skin = self.skins[self.cfg["skin"] % len(self.skins)]
        if not skin.get("pack") or result == "draw":
            return
        anims = skin.get("anims") or []
        if len(anims) < 2:
            return
        kw = MOOD_WIN_KW if result == "win" else MOOD_LOSE_KW
        pool = [a for a in anims if a != self._pack_anim and any(k in a for k in kw)]
        if not pool and result == "win":
            pool = [a for a in anims if a != self._pack_anim]
        if pool:
            self._pack_anim = random.choice(pool)
            self._pack_loops = 0
            if self.mode == "pet":
                self._anim_t = 0

    def _record(self, result):
        if self.solo:
            return                      # 单机试玩不计入战绩
        rec = {"t": time.strftime("%m-%d %H:%M"), "g": "gomoku",
               "opp": self.peer_display(), "addr": self.peer_addr or "-",
               "r": result}
        self.cfg["records"].append(rec)
        if len(self.cfg["records"]) > 200:
            self.cfg["records"] = self.cfg["records"][-200:]
        self.save_cfg()

    def resign(self):
        if not (self.playing and not self.game_over):
            return
        self.send_msg({"t": "resign"})
        self.resigned = True
        self._finish("lose")

    def restart(self):
        """对局结束后的再来一局: 直接换色重开(双方都看到结果, 无需确认)"""
        if not (self.playing and self.game_over):
            return
        self.send_msg({"t": "restart"})
        self._do_restart()

    def request_new(self):
        """对局中邀请新的一局, 需对方接受"""
        if not (self.playing and not self.game_over):
            return
        if self.solo:                   # 单机: 直接重开
            self._do_restart()
            return
        self.send_msg({"t": "new_req"})
        self.awaiting_new = True
        self.awaiting_new_until = time.time() + 10
        self.set_toast("已邀请开新局, 等对方接受…")

    def accept_new(self):
        if not self.new_req_pending:
            return
        self.new_req_pending = False
        self.send_msg({"t": "new_ok"})
        self._do_restart()

    def _do_restart(self):
        self.my_stone = WHITE if self.my_stone == BLACK else BLACK
        self.board = [[0] * N for _ in range(N)]
        self.game_over = False
        self.result = None
        self.resigned = False
        self.peer_resigned = False
        self.awaiting_new = False
        self.win_cells = None
        self.last_move = None
        self.turn = BLACK
        self.render()
        if self.solo and self.turn != self.my_stone:
            self._solo_after()          # 换色后若 AI 先手

    # ---------- 网络 ----------
    def send_msg(self, obj):
        if not (self.sock or self.conn):
            return
        try:
            data = (json.dumps(obj) + "\n").encode("utf-8")
            with self.send_lock:
                (self.sock or self.conn).sendall(data)
        except Exception:
            self.eq.put(("lost", "发送失败"))

    def _start_listener(self):
        def loop():
            try:
                ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                ls.bind(("", self.port))
                ls.listen(2)
                self.listen_sock = ls
            except Exception as e:
                self.eq.put(("port_busy", str(e)))
                return
            while True:
                try:
                    c, addr = ls.accept()
                except OSError:
                    return
                if self.playing:
                    try:
                        c.close()
                    except Exception:
                        pass
                    continue
                c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.conn = c
                self.peer_addr = f"{addr[0]}"
                self.eq.put(("conn_ok", addr[0]))
                threading.Thread(target=self.reader, args=(c,), daemon=True).start()

        threading.Thread(target=loop, daemon=True).start()

    def invite(self):
        if self.playing or self.connecting:
            return
        tgt = parse_target(self.entry_ip.get())
        if not tgt:
            self.set_toast("地址格式: IP 或 IP:端口")
            return
        self.connecting = True
        threading.Thread(target=self._connect_worker, args=tgt, daemon=True).start()

    def _connect_worker(self, host, port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(4)
            s.connect((host, port))
            s.settimeout(None)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as e:
            self.connecting = False
            self.eq.put(("conn_fail", str(e)))
            return
        self.sock = s
        self.peer_addr = host
        threading.Thread(target=self.reader, args=(s,), daemon=True).start()
        self.send_msg({"t": "hello", "name": self.cfg["name"]})
        mine = random.choice((BLACK, WHITE))
        self.send_msg({"t": "color", "yours": WHITE if mine == BLACK else BLACK})
        self.eq.put(("start_game", mine))

    def reader(self, c):
        try:
            f = c.makefile("r", encoding="utf-8")
            while True:
                line = f.readline(MSG_LIMIT)
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                t = msg.get("t")
                if t == "hello":
                    self.eq.put(("peer_name", str(msg.get("name") or "")[:12]))
                    self.send_msg({"t": "peer", "name": self.cfg["name"]})
                elif t == "peer":
                    self.eq.put(("peer_name", str(msg.get("name") or "")[:12]))
                elif t == "color":
                    self.eq.put(("start_game", msg.get("yours")))
                elif t == "move":
                    self.eq.put(("remote_move", msg.get("x"), msg.get("y")))
                elif t == "restart":
                    self.eq.put(("restart",))
                elif t == "new_req":
                    self.eq.put(("new_req",))
                elif t == "new_ok":
                    self.eq.put(("new_ok",))
                elif t == "resign":
                    self.eq.put(("peer_resign",))
                elif t == "bye":
                    self.eq.put(("lost", "对方离开了"))
                    break
        except Exception:
            pass
        self.eq.put(("lost", "连接已断开"))

    def disconnect(self):
        self.send_msg({"t": "bye"})
        self._net_reset()
        self.set_toast("已断开")

    def _net_reset(self):
        for s in (self.sock, self.conn):
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        self.sock = None
        self.conn = None
        self.playing = False
        self.connecting = False
        self.my_stone = 0
        self.board = [[0] * N for _ in range(N)]
        self.game_over = False
        self.result = None
        self.resigned = False
        self.peer_resigned = False
        self.awaiting_new = False
        self.win_cells = None
        self.last_move = None
        self.turn = BLACK
        self.new_req_pending = False
        self.peer_name = ""
        self.peer_remark = ""
        self.render()

    # ---------- 事件队列 ----------
    def _poll(self):
        try:
            while True:
                ev = self.eq.get_nowait()
                self._handle(ev)
        except queue.Empty:
            pass
        self._keep_order()
        self._auto_idle()
        if self.toast and time.time() > self.toast_until:
            self.toast = None
            self.render()
        self.root.after(80, self._poll)

    def _keep_order(self):
        try:
            self.iw.lift(self.root)
        except tk.TclError:
            pass
        if self.menu_win is not None:
            try:
                self.menu_win.lift()
            except tk.TclError:
                pass

    def _auto_idle(self):
        """5 秒无操作: 侧边菜单收起, 空闲棋盘回桌宠待机(对局中除外)"""
        if time.time() - self.last_active < IDLE_SECONDS:
            return
        if self.menu_win is not None:
            self.close_menu()
        if self.mode == "board":
            if self.game_over and not self.new_req_pending:
                self.set_mode("pet")
            elif not self.playing and not self.connecting:
                self.set_mode("pet")
        if self.new_req_pending and time.time() > self.new_req_until:
            self.new_req_pending = False
            self.render()

    def _handle(self, ev):
        k = ev[0]
        if k == "toggle":
            if self.root.state() == "withdrawn":
                self.show()
            else:
                self.hide()
        elif k == "hotkey_fail":
            self.set_toast("⚠ Ctrl+Q 被占用, 用菜单[隐藏]")
        elif k == "port_busy":
            self.set_toast(f"⚠ 端口被占用: {ev[1][:30]}")
        elif k == "trigger":
            self.trigger_anim(ev[1])
        elif k == "conn_fail":
            self.connecting = False
            self.set_toast(f"⚠ 连不上: {ev[1][:36]}")
        elif k == "conn_ok":
            if not self.playing:
                self.playing = True
                if self.mode != "board":
                    self.set_mode("board")
                else:
                    self.render()
        elif k == "peer_name":
            self.peer_name = ev[1]
            self.render()
        elif k == "start_game":
            if not self.playing:
                self.playing = True
            if self.mode != "board":
                self.set_mode("board")
            self.connecting = False
            self.my_stone = ev[1]
            self.board = [[0] * N for _ in range(N)]
            self.game_over = False
            self.result = None
            self.resigned = False
            self.peer_resigned = False
            self.win_cells = None
            self.last_move = None
            self.turn = BLACK
            self.render()
        elif k == "remote_move":
            x, y = ev[1], ev[2]
            if (self.playing and not self.game_over and self.turn != self.my_stone
                    and isinstance(x, int) and isinstance(y, int)
                    and 0 <= x < N and 0 <= y < N and not self.board[y][x]):
                self.apply_move(x, y, WHITE if self.my_stone == BLACK else BLACK)
        elif k == "restart":
            if self.playing and self.game_over:
                self._do_restart()
        elif k == "new_req":
            if self.playing and not self.game_over:
                self.new_req_pending = True
                self.new_req_until = time.time() + 10
                self.render()
            elif self.playing and self.game_over:
                self.send_msg({"t": "new_ok"})
                self._do_restart()
        elif k == "new_ok":
            if self.playing and self.awaiting_new:
                self.awaiting_new = False
                self._do_restart()
        elif k == "peer_resign":
            if self.playing and not self.game_over:
                self.peer_resigned = True
                self._finish("win")
        elif k == "render":
            self.render()
        elif k == "rescale":
            # 设置页改了桌宠大小: 清帧缓存(旧尺寸帧全部失效)并重排窗口
            self._anim_frames.clear()
            self._anim_lru.clear()
            self._apply_size()
            self.render()
        elif k == "pets_installed":
            self._pets_after_install(ev[1])
        elif k == "pets_failed":
            self.set_toast(f"⚠ 角色包下载失败: {ev[1]}")
        elif k == "lost":
            self._net_reset()
            self.set_toast(f"⚠ {ev[1] if len(ev) > 1 else ''}")

    # ---------- 显隐 ----------
    def hide(self):
        self.close_menu()
        self.root.withdraw()
        self.iw.withdraw()

    def show(self):
        self.root.deiconify()
        self.iw.deiconify()
        self.root.attributes("-topmost", True)
        self.iw.attributes("-topmost", True)
        self._keep_order()
        if self.mode == "pet":
            self._draw_pet_frame()
            self._start_anim()

    def quit_app(self):
        self.save_cfg()
        self.close_menu()
        try:
            self.iw.destroy()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("端口参数无效, 使用默认", DEFAULT_PORT)
    App(port).run()


if __name__ == "__main__":
    main()
