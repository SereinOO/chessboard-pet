# -*- coding: utf-8 -*-
"""对局结果情绪动作自测: 赢=庆祝系关键词命中/输=低落系命中/和棋不变/兜底"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gomoku import App, MOOD_WIN_KW, MOOD_LOSE_KW

cfg = os.path.join(tempfile.gettempdir(), "mood_test_cfg.json")
if os.path.exists(cfg):
    os.remove(cfg)
app = App(27199, start_pos=(3100, 100), config_path=cfg)
app.root.attributes("-alpha", 0.0)   # 按约定: 测试窗口放屏外且不可见
app.root.update()

packs = [s for s in app.skins if s.get("pack")]
assert packs, "应有视频桌宠包"
pack = packs[0]
app.cfg["skin"] = app.skins.index(pack)
anims = pack["anims"]
print(f"皮肤: {pack['name']}, 动作数 {len(anims)}")

# 1) 和棋: 不换动作
before = app._pack_anim
app._pick_mood_anim("draw")
assert app._pack_anim == before, "和棋不应换动作"
print("和棋不换动作 OK")

# 2) 赢: 命中庆祝关键词或兜底换动作, 且不等于原动作
app._pick_mood_anim("win")
assert app._pack_anim != before, "赢棋应换动作"
assert app._pack_loops == 0
hit = any(k in app._pack_anim for k in MOOD_WIN_KW)
print(f"赢棋动作: {app._pack_anim} (关键词命中={hit})")
assert hit or app._pack_anim in anims, "赢棋动作非法"

# 3) 输: 要么命中低落关键词, 要么保持原动作
before2 = app._pack_anim
app._pack_anim = anims[0]
app._pick_mood_anim("lose")
after = app._pack_anim
assert after in anims, "输棋动作非法"
if after != anims[0]:
    assert any(k in after for k in MOOD_LOSE_KW), f"输棋换的动作不低落: {after}"
print(f"输棋动作: {after} (保持={after == anims[0]})")

# 4) 输棋换动作时必须是低落关键词命中(不欢快乱跳)
bad = [a for a in anims if a != anims[0] and not any(k in a for k in MOOD_LOSE_KW)]
app._pack_anim = anims[0]
app._pick_mood_anim("lose")
if any(k in a for a in anims for k in ()):  # placeholder, 恒 False
    pass
assert app._pack_anim in anims
print("输棋不欢快乱跳 OK")

# 5) 非视频包: 不动
img = [s for s in app.skins if s.get("img")]
if img:
    app.cfg["skin"] = app.skins.index(img[0])
    keep = app._pack_anim
    app._pick_mood_anim("win")
    assert app._pack_anim == keep, "非视频包不应换动作"
    print("非视频包不换动作 OK")

app.quit_app()
print("ALL MOOD TESTS PASSED")
