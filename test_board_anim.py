# -*- coding: utf-8 -*-
"""棋盘胜负动画测试: 屏幕外+透明度0运行。
验证: 连五结束后棋盘上出现缩小版桌宠(board_pet 元素), 动画帧持续推进,
尺寸占棋盘一半, 再来一局后消失。"""
import os
import time
import gomoku as g


def pump(a, b, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        a.root.update()
        b.root.update()
        time.sleep(0.01)


def play_move(app, x, y):
    app._touch()            # 落子=用户活跃, 防止5秒空闲回桌宠
    assert app.playing and not app.game_over and app.turn == app.my_stone
    app.apply_move(x, y, app.my_stone)
    app.send_msg({"t": "move", "x": x, "y": y})


CFG_A = "test_cfg_a.json"
CFG_B = "test_cfg_b.json"
for p in (CFG_A, CFG_B):
    if os.path.exists(p):
        os.remove(p)

a = g.App(27190, start_pos=(3100, 100), config_path=CFG_A)
b = g.App(27191, start_pos=(3100, 500), config_path=CFG_B)
a.root.attributes("-alpha", 0.0)
b.root.attributes("-alpha", 0.0)
a.alpha = b.alpha = 0.0
a.cfg["name"] = "甲"
b.cfg["name"] = "乙"

skin_a = a.skins[a.cfg["skin"] % len(a.skins)]
print(f"皮肤: pack={skin_a.get('pack')} img={skin_a.get('img')}")

# 握手
a.entry_ip.delete(0, "end")
a.entry_ip.insert(0, "127.0.0.1:27191")
a.invite()
pump(a, b, 3000)
assert a.playing and b.playing

black = a if a.my_stone == g.BLACK else b
white = b if black is a else a

# 黑连五获胜
for i in range(4):
    play_move(black, i, 0)
    pump(a, b, 250)
    play_move(white, i, 1)
    pump(a, b, 250)
play_move(black, 4, 0)
pump(a, b, 500)

assert a.game_over and b.game_over
assert black.result == "win" and white.result == "lose"
a._touch(); b._touch()      # 玩家在看结果=活跃
pump(a, b, 100)
assert black.mode == "board" and white.mode == "board"

# 1) 棋盘上出现 board_pet 元素(双方都有)
items_a = a.canvas.find_withtag("board_pet")
items_b = b.canvas.find_withtag("board_pet")
assert items_a, "胜方棋盘无胜负动画元素"
assert items_b, "负方棋盘无胜负动画元素"

# 2) 尺寸占棋盘一半: bbox 最长边 ≈ BOARD_W/2, 且在棋盘区内
def check_bbox(app, tag):
    bb = app.canvas.bbox(tag)
    assert bb, f"{tag} 无 bbox"
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    assert max(w, h) <= g.BOARD_W // 2 + 12, f"动画过大: {w}x{h}"
    assert bb[3] <= g.TOPBAR + g.BOARD_W + 2, "动画底部超出棋盘区"
    assert bb[1] >= g.TOPBAR, "动画顶部超出棋盘区"
    # 必须在棋盘正中心
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    assert abs(cx - g.SIZE_BOARD[0] / 2) <= 2, f"水平未居中: {cx}"
    assert abs(cy - (g.TOPBAR + g.BOARD_W / 2)) <= 2, f"垂直未居中: {cy}"
    return w, h

wa, ha = check_bbox(a, "board_pet")
wb, hb = check_bbox(b, "board_pet")
print(f"胜方动画 bbox {wa}x{ha}, 负方 {wb}x{hb} (棋盘 {g.BOARD_W} 宽)")

if skin_a.get("pack"):
    side = max(wa, ha)
    assert abs(side - g.BOARD_W // 2) <= 12, f"最长边应≈{g.BOARD_W//2}: {side}"

# 3) 动画在动: 600ms 后图像引用应变化(帧推进)
a._touch(); b._touch()
img0 = a.canvas.itemcget(items_a[0], "image")
pump(a, b, 600)
items_a = a.canvas.find_withtag("board_pet")
img1 = a.canvas.itemcget(items_a[0], "image")
assert img0 != img1, f"动画帧未推进: {img0} == {img1}"
print("动画帧推进OK")

# 4) 再来一局后消失
a._touch(); b._touch()
black.restart()
pump(a, b, 500)
assert not a.game_over and not b.game_over
assert not a.canvas.find_withtag("board_pet"), "重开后动画未消失"
assert not b.canvas.find_withtag("board_pet"), "重开后动画未消失"
print("重开后动画消失OK")

# 5) 认输同样触发(负方)
a._touch(); b._touch()
white.resign()
pump(a, b, 500)
assert a.game_over and b.game_over
assert b.canvas.find_withtag("board_pet") or a.canvas.find_withtag("board_pet")
print("认输也触发胜负动画OK")

a.root.destroy()
b.root.destroy()
print("BOARD_ANIM_OK")
