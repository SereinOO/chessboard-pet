# -*- coding: utf-8 -*-
"""桌宠动画自测: 视频包帧序列/整循环渲染/动画循环/缩放/模式切换(屏幕外+透明0)"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gomoku import App, ANIM_FRAMES

cfg = os.path.join(tempfile.gettempdir(), "anim_test_cfg.json")
if os.path.exists(cfg):
    os.remove(cfg)          # 上次运行保存的 skin 索引会污染断言, 每次全新开始
app = App(27198, start_pos=(3100, 100), config_path=cfg)
app.root.attributes("-alpha", 0.0)   # 按约定: 测试窗口放屏外且不可见
app.root.update()

pack = [s for s in app.skins if s.get("pack")]
assert pack, "应有视频桌宠包"
skin = pack[0]
app.cfg["skin"] = app.skins.index(skin)

# 1) 视频包帧序列: 每动作 120 帧
frames = app._pack_frames(skin, None, 1.0)
assert len(frames) == 120, f"动作帧数异常: {len(frames)}"
assert app._pack_anim in skin["anims"]
t0 = time.time()
app._pack_frames(skin, skin["anims"][1], 1.5)     # 缩放档懒加载
bake = time.time() - t0
assert bake < 15, f"缩放帧加载过慢: {bake:.1f}s"
print(f"帧序列OK  120帧  1.5x缩放档加载 {bake:.2f}s")

# 2) 整循环逐帧渲染不报错, pet_anim 标签存在
app.set_mode("pet")
app.root.update()
for i in range(ANIM_FRAMES):
    app._anim_t = i
    app._draw_pet_frame()
app.canvas.update()
items = app.canvas.find_withtag("pet_anim")
assert len(items) >= 1, "pet_anim 画布项缺失"
print(f"整循环 120 帧渲染 OK, pet_anim 项数={len(items)}")

# 3) 动画循环调度推进(12fps)
app._anim_t = 0
app._start_anim()
for _ in range(10):
    app.root.update()
    time.sleep(0.04)
assert app._anim_t > 0, "动画循环未推进"
print("动画循环推进 OK, _anim_t =", app._anim_t)

# 4) 缩放: rescale 事件后窗口按比例变大(视频包按帧比例适配)
app.cfg["pet_scale"] = 1.5
app._handle(("rescale",))
app.root.update()
w, h = app._pet_size()
fw, fh = skin["fsize"]
ph = max(60, round(180 * fh / fw))
assert (w, h) == (270, int(ph * 1.5)), f"缩放窗口尺寸异常: {(w, h)}"
assert app.canvas.winfo_width() >= 270, "画布未随缩放变大"
assert (skin["pack"], app._pack_anim, 1.5) in app._anim_frames, "缩放帧缓存缺失"
print(f"缩放OK  窗口 {w}x{h}, 1.5x 帧缓存生效")

# 5) 模式切换后动画停止
app.cfg["pet_scale"] = 1.0
app._handle(("rescale",))
app.set_mode("board")
app.root.update()
t_before = app._anim_t
time.sleep(0.1)
app.root.update()
assert app._anim_t == t_before, "非 pet 模式动画未停止"
print("模式切换停止动画 OK")

app.quit_app()
print("ALL ANIM TESTS PASSED")
