# -*- coding: utf-8 -*-
"""dist 产物冒烟: 屏外启动 dist 里的 gomoku.py, 验证无桌宠包时 canvas 兜底正常"""
import os
import sys

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "chessboard_desktop_pet")
sys.path.insert(0, DIST)

import gomoku

skins = gomoku.load_skin_list()
print("skins:", [(s.get("name"), s.get("type", "?")) for s in skins])

cfg = os.path.join(DIST, "config.json")
print("config_path:", cfg, "| 存在:", os.path.isfile(cfg))

app = gomoku.App(27250, start_pos=(3100, 100), config_path=cfg)
app.root.update()
print("启动OK, 窗口尺寸:", app.root.winfo_width(), "x", app.root.winfo_height())
app.root.destroy()
print("DIST_SMOKE_PASS")
