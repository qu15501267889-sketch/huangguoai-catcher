# -*- coding: utf-8 -*-
"""解析逻辑单元测试 —— 用真实 HTML 片段固化，防站点改版导致静默空跑。"""
import huangguoai_dl as H


# 真实抓取的视频页片段（含 videoSrc）
VIDEO_HTML = r'''
<script id="videoInitialData">{"author":"黄果官方","coverSrc":"https://pic.vjxyrj.cn/x.jpg?auth_key=1-0-abc","description":"2000年前后，B中老师老施离婚后净身出户。","ep":2,"epPlaySrcs":{"1":"https://yd-hls.nkgjoa.cn/v/a.m3u8?auth_key=1\u0026v=3\u0026via=hgdj\u0026via_bm=dx"},"posterSrc":"https://pic.vjxyrj.cn/upload/p.jpg?auth_key=2-0-def","title":"高三爱情故事","videoSrc":"https://yd-hls.nkgjoa.cn/videos5/079c5056c5c6da0409ad654cc691ccfd/079c5056c5c6da0409ad654cc691ccfd.m3u8?auth_key=1788239522-64b4c3fc1a2eb-0-f31cb797840381ff190caca4e3066a3a\u0026v=3\u0026time=0\u0026via=hgdj\u0026via_bm=dx"}</script>
'''


def test_parse_episode_src():
    src = H.parse_episode_src(VIDEO_HTML)
    assert src is not None
    assert ".m3u8" in src
    # \u0026 被还原为 &
    assert "&v=3" in src
    assert "\\u0026" not in src


def test_parse_episode_src_no_source():
    # 无 videoSrc/不含 m3u8 -> None
    assert H.parse_episode_src("<html>no player</html>") is None
    assert H.parse_episode_src('<script>{}"videoSrc":"https://x/movie.mp4"</script>') is None


def test_parse_series_detail_title_maxep():
    html = '<title>高三爱情故事 - 短剧视频在线观看 | 黄果短剧</title>' \
           '<a href="/video/117/ep-2/">02</a>' \
           '<a href="/video/117/ep-3/">03</a>' \
           '<a href="/video/117/ep-8/">08</a>'
    title, max_ep, poster, desc = H.parse_series_detail(html, "117")
    assert title == "高三爱情故事"
    assert max_ep == 8  # 选集列表漏 ep-1 也能拿到最大集数


def test_parse_series_detail_poster_and_desc():
    html = VIDEO_HTML
    # 只看 poster 提取（detail 页通常也有 posterSrc/coverSrc）
    title, max_ep, poster, desc = H.parse_series_detail(html, "117")
    assert poster.startswith("https://pic.vjxyrj.cn")
    assert "老施离婚" in desc
    assert "高清视频" not in desc
    assert "一站式平台" not in desc


def test_parse_poster_src():
    assert H.parse_poster_src(VIDEO_HTML) == \
        "https://pic.vjxyrj.cn/upload/p.jpg?auth_key=2-0-def"
    assert H.parse_poster_src("<html>none</html>") == ""


def test_parse_item_list():
    html = ('{"@type":"ListItem","name":"主播日常","position":1,'
            '"url":"https://huangguoai.com/detail/3690/"},'
            '{"@type":"ListItem","name":"征服傲慢继母","position":2,'
            '"url":"https://huangguoai.com/detail/3689/"}')
    pairs = H.parse_item_list(html)
    assert pairs[0] == ("主播日常", "3690")
    assert pairs[1] == ("征服傲慢继母", "3689")


def test_clean_title_strips_illegal():
    assert H.clean_title('a/b:c*?"<>|') == "a_b_c______"  # 8 个非法字符 -> 8 下划线
    assert H.clean_title("  ") == "unknown"


def test_decrypt_image_real_poster():
    # 用已知加密 magic(模拟): 需真实数据才能断言，这里只验证无效输入返回 None
    assert H.decrypt_image(b"", b"k"*16, b"i"*16) is None
    assert H.decrypt_image(b"notencrypted", b"k"*16, b"i"*16) is None


def test_unescape():
    assert H._unescape("a\\u0026b\\u002Fc") == "a&b/c"
    assert H._unescape("plain") == "plain"


def test_save_manifest_atomic(tmp_path):
    # 原子写：正常写入 + 临时文件应被清理
    mf = str(tmp_path / "m.json")
    H.save_manifest({"117": {"title": "t", "done": [1, 2]}}, mf)
    import json as _j
    data = _j.load(open(mf, encoding="utf-8"))
    assert data["117"]["done"] == [1, 2]
    # 不应残留 .tmp
    import os
    assert not os.path.exists(mf + ".tmp")


def test_cleanup_junks(tmp_path):
    import os, logging, shutil
    logger = logging.getLogger("t"); logger.addHandler(logging.NullHandler())
    d = str(tmp_path)
    # 造垃圾
    open(os.path.join(d, "ep01.mp4.part.ts"), "w").write("x" * 2000)
    os.makedirs(os.path.join(d, ".ep01"), exist_ok=True)
    open(os.path.join(d, ".ep01", "00001.ts"), "w").write("y" * 3000)
    open(os.path.join(d, "manifest.json.tmp"), "w").write("{}")
    # 正常文件
    open(os.path.join(d, "ep01.mp4"), "w").write("z" * 200000)
    freed = H.cleanup_junks(d, logger)
    assert freed > 0
    assert os.path.exists(os.path.join(d, "ep01.mp4"))  # 正常文件保留
    assert not os.path.exists(os.path.join(d, "ep01.mp4.part.ts"))
    assert not os.path.exists(os.path.join(d, ".ep01"))
    assert not os.path.exists(os.path.join(d, "manifest.json.tmp"))


def test_notify_disabled_by_default():
    # notify 默认 enabled=False -> 不发
    cfg = H.Config(dict(H.DEFAULT_CONFIG))
    assert cfg.notify.get("enabled") is False
