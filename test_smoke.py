# -*- coding: utf-8 -*-
"""双实例对弈冒烟测试: 屏幕外+透明度0运行, 覆盖握手/昵称交换/对弈/战绩/认输/邀新/重开/退出"""
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
    assert app.playing and not app.game_over and app.turn == app.my_stone
    app.apply_move(x, y, app.my_stone)
    app.send_msg({"t": "move", "x": x, "y": y})


CFG_A = "test_cfg_a.json"
CFG_B = "test_cfg_b.json"
for p in (CFG_A, CFG_B):
    if os.path.exists(p):
        os.remove(p)

# 屏幕外 + 透明度0(自测约定, 不闪现窗口)
a = g.App(27190, start_pos=(3100, 100), config_path=CFG_A)
b = g.App(27191, start_pos=(3100, 500), config_path=CFG_B)
a.root.attributes("-alpha", 0.0)
b.root.attributes("-alpha", 0.0)
a.alpha = b.alpha = 0.0
a.cfg["name"] = "甲"
b.cfg["name"] = "乙"

# 1. 连接握手 + 昵称交换
a.entry_ip.delete(0, "end")
a.entry_ip.insert(0, "127.0.0.1:27191")
a.invite()
pump(a, b, 3000)
assert a.playing and b.playing, "双方未进入对局状态"
assert a.my_stone in (g.BLACK, g.WHITE) and b.my_stone in (g.BLACK, g.WHITE)
assert a.my_stone != b.my_stone, "颜色分配冲突"
assert a.peer_name == "乙" and b.peer_name == "甲", f"昵称交换失败: {a.peer_name}/{b.peer_name}"
assert a.turn == g.BLACK and b.turn == g.BLACK, "黑棋应先行"
print(f"握手OK  A执{'黑' if a.my_stone==g.BLACK else '白'}(甲)  B执{'黑' if b.my_stone==g.BLACK else '白'}(乙)")

black = a if a.my_stone == g.BLACK else b
white = b if black is a else a

# 2. 对弈: 黑走 (0,0)..(4,0) 连五, 白走 (0,1)..(3,1) 干扰
for i in range(4):
    play_move(black, i, 0)
    pump(a, b, 250)
    play_move(white, i, 1)
    pump(a, b, 250)
play_move(black, 4, 0)
pump(a, b, 500)

assert a.game_over and b.game_over, "双方都应判定游戏结束"
assert a.win_cells and len(a.win_cells) == 5 and b.win_cells, "胜利连线未识别"
assert a.board == b.board, "双方棋盘不同步"
assert black.result == "win" and white.result == "lose", "胜负结果不符"
assert len(black.cfg["records"]) == 1 and black.cfg["records"][0]["r"] == "win"
assert len(white.cfg["records"]) == 1 and white.cfg["records"][0]["r"] == "lose"
assert black.cfg["records"][0]["opp"] == white.cfg["name"]
assert white.cfg["records"][0]["opp"] == black.cfg["name"]
assert os.path.exists(CFG_A) and os.path.exists(CFG_B), "战绩未持久化"
print("对弈OK  黑棋连五获胜, 战绩已记录并持久化")

# 3. 再来一局(结束后直接重开): 双方换色
old_a, old_b = a.my_stone, b.my_stone
black.restart()
pump(a, b, 500)
assert not a.game_over and not b.game_over and not a.board[0][0]
assert a.my_stone != old_a and b.my_stone != old_b and a.my_stone != b.my_stone
print("重开OK  双方黑白互换")

# 4. 认输: 当前白棋(原黑方)认输
white_now = a if a.my_stone == g.WHITE else b
black_now = b if white_now is a else a
assert a.turn == g.BLACK and b.turn == g.BLACK
white_now.resign()   # 轮到黑走, 白认输
pump(a, b, 400)
assert a.game_over and b.game_over
assert black_now.result == "win" and white_now.result == "lose"
assert black_now.resigned is False and white_now.resigned is True
assert len(black_now.cfg["records"]) == 2 and black_now.cfg["records"][-1]["r"] == "win"
print("认输OK  对方收到胜利并记录战绩")

# 5. 对局中邀新一局(需对方接受): 重开 -> 新黑方走一步 -> 邀新 -> 对方接受
black_now.restart()
pump(a, b, 400)
assert not a.game_over and not b.game_over
new_black = a if a.my_stone == g.BLACK else b
new_white = b if new_black is a else a
play_move(new_black, 7, 7)
pump(a, b, 300)
new_black.request_new()
pump(a, b, 300)
assert new_white.new_req_pending, "对方未收到邀新请求"
new_white.accept_new()
pump(a, b, 500)
assert not a.game_over and not b.game_over
assert a.board == b.board and all(v == 0 for row in a.board for v in row)
assert a.my_stone != b.my_stone
print("邀新OK  对局中邀请->对方接受->换色重开")

# 6. 退出对局
new_white.disconnect()
pump(a, b, 500)
assert not a.playing and not b.playing, "退出后未回到待机"
print("退出OK")

a.root.destroy()
b.root.destroy()
print("SMOKE_OK")
