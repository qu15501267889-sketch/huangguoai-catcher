# -*- coding: utf-8 -*-
"""解析/工具逻辑单元测试 —— 用真实 HTML 片段固化，防站点改版导致静默空跑。"""
from hgcatcher.parsers import HuangguoParser, clean_title, _unescape
from hgcatcher.utils import save_manifest, human_size
from hgcatcher.config import Config, DEFAULT_CONFIG
from hgcatcher.watchdog import cleanup_junks

P = HuangguoParser()

# 真实抓取的视频页片段（含 videoSrc）
VIDEO_HTML = r'''
<script id="videoInitialData">{"author":"黄果官方","coverSrc":"https://pic.vjxyrj.cn/x.jpg?auth_key=1-0-abc","description":"2000年前后，B中老师老施离婚后净身出户。","ep":2,"epPlaySrcs":{"1":"https://yd-hls.nkgjoa.cn/v/a.m3u8?auth_key=1\u0026v=3\u0026via=hgdj\u0026via_bm=dx"},"posterSrc":"https://pic.vjxyrj.cn/upload/p.jpg?auth_key=2-0-def","title":"高三爱情故事","videoSrc":"https://yd-hls.nkgjoa.cn/videos5/079c5056c5c6da0409ad654cc691ccfd/079c5056c5c6da0409ad654cc691ccfd.m3u8?auth_key=1788239522-64b4c3fc1a2eb-0-f31cb797840381ff190caca4e3066a3a\u0026v=3\u0026time=0\u0026via=hgdj\u0026via_bm=dx"}</script>
'''


def test_parse_src():
    src = P.parse_src(VIDEO_HTML)
    assert src is not None
    assert ".m3u8" in src
    assert "&v=3" in src
    assert "\\u0026" not in src


def test_parse_src_no_source():
    assert P.parse_src("<html>no player</html>") is None
    assert P.parse_src('<script>{}"videoSrc":"https://x/movie.mp4"</script>') is None


def test_parse_detail_title_maxep():
    html = '<title>高三爱情故事 - 短剧视频在线观看 | 黄果短剧</title>' \
           '<a href="/video/117/ep-2/">02</a>' \
           '<a href="/video/117/ep-3/">03</a>' \
           '<a href="/video/117/ep-8/">08</a>'
    title, max_ep, poster, desc = P.parse_detail(html, "117")
    assert title == "高三爱情故事"
    assert max_ep == 8


def test_parse_detail_poster_desc():
    title, max_ep, poster, desc = P.parse_detail(VIDEO_HTML, "117")
    assert poster.startswith("https://pic.vjxyrj.cn")
    assert "老施离婚" in desc
    assert "高清视频" not in desc
    assert "一站式平台" not in desc


def test_parse_poster():
    assert P.parse_poster(VIDEO_HTML) == "https://pic.vjxyrj.cn/upload/p.jpg?auth_key=2-0-def"
    assert P.parse_poster("<html>none</html>") == ""


def test_parse_list():
    html = ('{"@type":"ListItem","name":"主播日常","position":1,'
            '"url":"https://huangguoai.com/detail/3690/"},'
            '{"@type":"ListItem","name":"征服傲慢继母","position":2,'
            '"url":"https://huangguoai.com/detail/3689/"}')
    pairs = P.parse_list(html)
    assert pairs[0] == ("主播日常", "3690")
    assert pairs[1] == ("征服傲慢继母", "3689")


def test_clean_title():
    assert clean_title('a/b:c*?"<>|') == "a_b_c______"
    assert clean_title("  ") == "unknown"


def test_unescape():
    assert _unescape("a\\u0026b\\u002Fc") == "a&b/c"
    assert _unescape("plain") == "plain"


def test_save_manifest_atomic(tmp_path):
    mf = str(tmp_path / "m.json")
    save_manifest({"117": {"title": "t", "done": [1, 2]}}, mf)
    import json
    import os
    data = json.load(open(mf, encoding="utf-8"))
    assert data["117"]["done"] == [1, 2]
    assert not os.path.exists(mf + ".tmp")


def test_cleanup_junks(tmp_path):
    import os, logging
    logger = logging.getLogger("t"); logger.addHandler(logging.NullHandler())
    d = str(tmp_path)
    open(os.path.join(d, "ep01.mp4.part.ts"), "w").write("x" * 2000)
    os.makedirs(os.path.join(d, ".ep01"), exist_ok=True)
    open(os.path.join(d, ".ep01", "00001.ts"), "w").write("y" * 3000)
    open(os.path.join(d, "manifest.json.tmp"), "w").write("{}")
    open(os.path.join(d, "ep01.mp4"), "w").write("z" * 200000)
    freed = cleanup_junks(d, logger)
    assert freed > 0
    assert os.path.exists(os.path.join(d, "ep01.mp4"))
    assert not os.path.exists(os.path.join(d, "ep01.mp4.part.ts"))
    assert not os.path.exists(os.path.join(d, ".ep01"))
    assert not os.path.exists(os.path.join(d, "manifest.json.tmp"))


def test_notify_disabled_by_default():
    cfg = Config(dict(DEFAULT_CONFIG))
    assert cfg.notify.get("enabled") is False


def test_human_size():
    assert human_size(2 ** 30) == "1.00 GB"
    assert human_size(2 ** 20) == "1.0 MB"
    assert human_size(500) == "500 B"
