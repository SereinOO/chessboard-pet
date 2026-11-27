# -*- coding: utf-8 -*-
"""UI 改版专项测试(屏幕外+透明0): 桌宠去名/去顶栏、左键拖拽持久化、
菜单防超屏、动作选择窗、/api/trigger 网页触发、全屏设置页"""
import json
import os
import tempfile
import time
import types
import urllib.request
from urllib.parse import quote

import gomoku as g

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CFG = os.path.join(tempfile.gettempdir(), "gomoku_test_ui.json")
if os.path.exists(CFG):
    os.remove(CFG)

a = g.App(27185, start_pos=(3100, 100), config_path=CFG)
a.root.attributes("-alpha", 0.0)
a.alpha = 0.0

# 1. pet 模式: 无顶栏热点(右上角"—"已移除), 不渲染名字
a.set_mode("pet")
a.root.update()
assert a.hotspots == [], f"pet 模式不应有热点(顶栏已删): {a.hotspots}"
texts = [a.canvas.itemcget(i, "text") for i in a.canvas.find_withtag("ui")
         if a.canvas.type(i) == "text"]
assert a.cfg["name"] not in texts, f"桌宠上不应显示名字: {texts}"
print("桌宠净化OK  无顶栏热点/无名字")

# 2. 左键拖拽: 按住->移动->松手, 位置更新并持久化
old = a._pos
a._route_click(types.SimpleNamespace(x_root=old[0] + 40, y_root=old[1] + 30))
a._drag_move(types.SimpleNamespace(x_root=old[0] + 140, y_root=old[1] + 130))
a._drag_end(None)
assert a._pos == (old[0] + 100, old[1] + 100), f"拖拽未生效: {a._pos}"
a.root.update()
cfg_disk = json.load(open(CFG, encoding="utf-8"))
assert cfg_disk.get("pet_pos") == [old[0] + 100, old[1] + 100], cfg_disk.get("pet_pos")
print(f"拖拽持久化OK  {old} -> {a._pos} 已写入 pet_pos")

# 3. 重启恢复位置: 新实例用 pet_pos 而非默认角
b = g.App(27184, config_path=CFG)
b.root.attributes("-alpha", 0.0)
assert b._pos == (old[0] + 100, old[1] + 100), f"位置未恢复: {b._pos}"
b.root.destroy()
print("位置恢复OK  新实例启动在上次拖到的位置")

# 4. 菜单防超屏: 桌宠贴右下角时, 菜单完整落在屏幕内
a._pos = (a.root.winfo_screenwidth() - 60, a.root.winfo_screenheight() - 80)
a._apply_size()
a.root.update()
a.close_menu()
a.open_menu()
a.root.update()
mw = a.menu_win
sw, sh = mw.winfo_screenwidth(), mw.winfo_screenheight()
assert mw.winfo_x() >= 0 and mw.winfo_x() + mw.winfo_width() <= sw, \
    f"菜单横向超屏: x={mw.winfo_x()} w={mw.winfo_width()} sw={sw}"
assert mw.winfo_y() >= 0 and mw.winfo_y() + mw.winfo_height() <= sh, \
    f"菜单纵向超屏: y={mw.winfo_y()} h={mw.winfo_height()} sh={sh}"
print(f"菜单防超屏OK  贴角弹出 {mw.winfo_x()},{mw.winfo_y()} "
      f"{mw.winfo_width()}x{mw.winfo_height()} 在 {sw}x{sh} 内")

# 5. 动作选择窗: 视频皮肤有入口, 打开后可滚动列表 + 触发
pack = [s for s in a.skins if s.get("pack")]
assert pack, "没有视频桌宠包"
a.cfg["skin"] = a.skins.index(pack[0])
a._pos = (3100, 100)
a.open_menu()
a.close_menu()
a._open_anim_picker()
assert a.anim_win is not None, "动作选择窗未打开"
a.root.update()
a._close_anim_picker()
assert a.anim_win is None
name0 = pack[0]["anims"][0]
assert a.trigger_anim(name0) is True
assert a._pack_anim == name0 and a._anim_t == 0
print(f"动作选择窗OK  触发动作: {name0}")

# 6. 网页 /api/trigger -> 事件队列 -> 桌宠表演
port = a._ensure_settings_server()
anim1 = pack[0]["anims"][1]
req = urllib.request.Request(
    f"http://127.0.0.1:{port}/api/trigger",
    data=json.dumps({"anim": anim1}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with opener.open(req, timeout=5) as r:
    assert json.loads(r.read())["ok"] is True
for _ in range(80):
    a.root.update()
    time.sleep(0.02)                # _poll 80ms 一跳, 必须给真实时间
    if a._pack_anim == anim1:
        break
assert a._pack_anim == anim1, f"/api/trigger 未生效: {a._pack_anim}"
print(f"网页触发OK  /api/trigger -> {anim1}")

# 7. 全屏设置页: 侧边导航 + 形象动作区 + 大小滑条 + 战绩筛选存在
with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as r:
    html = r.read().decode("utf-8")
for kw in ("桌宠控制台", "形象与动作", "showSec", "/api/trigger", "actcard",
           "pscale", "oppfilter", "renderRecs", "单机试玩"):
    assert kw in html, f"设置页缺 {kw}"
assert "<aside>" in html and "position:fixed" in html, "不是整页布局"
with opener.open(f"http://127.0.0.1:{port}/api/config", timeout=5) as r:
    cfg_api = json.loads(r.read())
assert cfg_api["skins"][a.skins.index(pack[0])]["animbase"], "api 缺 animbase"
assert cfg_api["skins"][a.skins.index(pack[0])]["anims"], "api 缺 anims"
assert "pet_scale" in cfg_api, "api 缺 pet_scale"
print("全屏设置页OK  整页布局/动作网格/大小滑条/战绩筛选齐全")

# 8. 图片桌宠已移除: 皮肤表不应再出现悟空/佐助/阿尼亚/小僵尸
names = [s["name"] for s in a.skins]
for gone in ("悟空", "佐助", "阿尼亚", "小僵尸"):
    assert gone not in names, f"图片形象 {gone} 未移除: {names}"
print("图片形象移除OK  皮肤表:", names)

# 9. 单机试玩: AI 自动应答 + 不计战绩 + 结束清理
a.set_mode("pet")               # 清理前面的对局状态
a.root.update()
assert not a.solo
a.start_solo()
a.root.update()
assert a.solo and a.playing and a.mode == "board"
assert a.peer_name == "单机AI"
# 玩家先手就先走一步; AI 先手则等它落子
if a.turn == a.my_stone and not a.game_over:
    x, y = next((x, y) for y in range(15) for x in range(15) if not a.board[y][x])
    a.apply_move(x, y, a.my_stone)
before_cnt = sum(v != 0 for row in a.board for v in row)
deadline = time.time() + 6
while time.time() < deadline and sum(v != 0 for row in a.board for v in row) <= before_cnt:
    a.root.update()
    time.sleep(0.05)
after_cnt = sum(v != 0 for row in a.board for v in row)
assert after_cnt > before_cnt, "AI 未落子/未回应"
print(f"单机试玩OK  已落 {after_cnt} 子, AI 正常应答(玩家执{'黑' if a.my_stone==1 else '白'})")

# 10. 缩放: rescale 后窗口变大, 帧缓存按新档生成
a._net_reset()                  # 结束单机(直接清状态)
a.set_mode("pet")
a.cfg["pet_scale"] = 2.0
a._handle(("rescale",))
a.root.update()
# 视频包窗口按帧比例适配: 期望值从包首帧尺寸动态计算(重导出后帧尺寸会变)
pk = [s for s in a.skins if s.get("pack")][0]
fw, fh = pk["fsize"]
ph = max(60, round(g.SIZE_PET[0] * fh / fw))
assert a._pet_size() == (int(g.SIZE_PET[0] * 2.0), int(ph * 2.0)), a._pet_size()
assert a.cfg["pet_scale"] == 2.0
print(f"桌宠缩放OK  2.0x -> 窗口 {a._pet_size()[0]}x{a._pet_size()[1]} (帧比例 {fw}x{fh})")

a.root.destroy()
print("UI_OK")
