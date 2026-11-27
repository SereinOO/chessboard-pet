# -*- coding: utf-8 -*-
"""视频桌宠包冒烟测试: 包加载/帧序列/循环随机换动作/设置页缩略图接口(屏幕外+透明0)"""
import json
import os
import tempfile
import time
import urllib.request
from urllib.parse import quote

import gomoku as g

CFG = os.path.join(tempfile.gettempdir(), "gomoku_test_pack.json")
if os.path.exists(CFG):
    os.remove(CFG)

# 屏幕外 + 透明度0(自测约定, 不闪现窗口)
a = g.App(27189, start_pos=(3100, 100), config_path=CFG)
a.root.attributes("-alpha", 0.0)
a.alpha = 0.0

# 1. 包皮肤已加载(至少一个视频桌宠包)
pack_skins = [s for s in a.skins if s.get("pack")]
assert pack_skins, f"视频桌宠包未加载: {[s['name'] for s in a.skins]}"
skin = pack_skins[0]
idx = a.skins.index(skin)
assert len(skin["anims"]) >= 10, skin["anims"]
assert skin.get("thumb") and skin.get("animbase"), "缺缩略图/动作根路径"
print(f"加载OK  皮肤表: {[s['name'] for s in a.skins]}  "
      f"首个视频包[{skin['name']}]动作数: {len(skin['anims'])}")

# 2. 切到视频桌宠, 帧序列加载(每个动作120帧)
a.cfg["skin"] = idx
a.set_mode("pet")
a.root.update()
a._pack_anim = None
frames = a._pack_frames(skin, None)
assert len(frames) == 120, f"动作帧数异常: {len(frames)}"
assert a._pack_anim in skin["anims"]
a.root.update()          # 确认能渲染不崩
print(f"帧序列OK  当前动作: {a._pack_anim}  120帧")

# 3. 循环播完随机换动作(强制 loops>=2, 多次触发统计)
switched = set()
for _ in range(300):
    a._pack_loops = 2
    cur = a._pack_frames(skin, a._pack_anim)
    a._anim_t = len(cur)          # 让 _anim_loop 触发换帧边界
    a._anim_loop()
    a.root.update()
    switched.add(a._pack_anim)
assert len(switched) > 1, f"动作随机切换失败: {switched}"
assert len(a._anim_frames) <= g.ANIM_CACHE_MAX, \
    f"帧缓存未按 LRU 上限淘汰: {len(a._anim_frames)}"
print(f"随机换动作OK  播过 {len(switched)} 个动作, 缓存 {len(a._anim_frames)} 个(上限 {g.ANIM_CACHE_MAX})")

# 4. 设置页缩略图接口 /petimg/ 可取到 preview.png
# (本机有系统代理, urllib 会把 127.0.0.1 请求也发给代理导致 404, 测试用直连 opener)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
port = a._ensure_settings_server()
assert port
thumb_url = "http://127.0.0.1:%d/petimg/%s" % (port, quote(skin["thumb"]))
with opener.open(thumb_url, timeout=5) as r:
    data = r.read()
assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000, "缩略图不是有效PNG"
# 路径穿越防护
try:
    opener.open("http://127.0.0.1:%d/petimg/../gomoku.py" % port, timeout=5)
    raise AssertionError("路径穿越未被拦截")
except Exception:
    pass
print(f"缩略图接口OK  /petimg/ 返回PNG({len(data)//1024}KB), 穿越被封")

a.root.destroy()
print("PACK_OK")
