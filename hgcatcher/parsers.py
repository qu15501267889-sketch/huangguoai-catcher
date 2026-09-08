# -*- coding: utf-8 -*-
"""解析模块：站点 HTML -> 结构化数据。

升级接口：抽象 BaseParser。站点改版/新增站点时，实现/替换 parser 即可，
下载器与主流程无需改动。正则全部模块级预编译以提升性能。
"""
import re

# ── 预编译正则（性能优化：避免每次解析重复 compile） ──
_RE_VIDEO_SRC = re.compile(r'"videoSrc"\s*:\s*"([^"]+)"')
_RE_TITLE = re.compile(r"<title>([^<]+)</title>")
_RE_EP_LINK = re.compile(r"/video/(\d+)/ep-(\d+)/")
_RE_POSTER_SRC = re.compile(r'"posterSrc"\s*:\s*"([^"]+)"')
_RE_COVER_SRC = re.compile(r'"coverSrc"\s*:\s*"([^"]+)"')
_RE_OG_IMAGE = re.compile(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"')
_RE_META_DESC = re.compile(r'<meta[^>]*name="description"[^>]*content="([^"]+)"')
_RE_DESC = re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"')
_RE_ITEMLIST = re.compile(
    r'\{"@type":\s*"ListItem",\s*"name":\s*"((?:[^"\\]|\\.)*)",'
    r'\s*"position":\s*\d+,\s*"url":\s*"https://huangguoai\.com/detail/(\d+)/"')
_RE_PLAIN_DETAIL = re.compile(r'href="/detail/(\d+)/"')
_RE_ILLEGAL_FNAME = re.compile(r'[\\/:*?"<>|\r\n\t]')
_RE_EXT_KEY_URI = re.compile(r'URI="([^"]+)"')
_RE_EXT_KEY_IV = re.compile(r"IV=0x([0-9a-fA-F]+)")


def _unescape(s):
    return (s.replace("\\u0026", "&").replace("\\u002F", "/")
            .replace("\\u002f", "/"))


def clean_title(t):
    if not t:
        return "unknown"
    return _RE_ILLEGAL_FNAME.sub("_", t).strip() or "unknown"


class BaseParser:
    """站点解析器接口。子类实现即可接入新站点/应对改版。"""

    def parse_src(self, html):
        """视频页 -> 单集 m3u8 源字符串，无则 None"""
        raise NotImplementedError

    def parse_detail(self, html, vid):
        """详情页 -> (title, max_ep, poster_url, desc)"""
        raise NotImplementedError

    def parse_poster(self, video_html):
        """视频页 -> posterSrc(图床加密 url)"""
        raise NotImplementedError

    def parse_list(self, html):
        """分类页 -> [(title, vid), ...]（ItemList JSON-LD）"""
        raise NotImplementedError

    def parse_plain_detail_ids(self, html):
        """分类页兜底 -> [vid, ...]（无标题版）"""
        raise NotImplementedError


class HuangguoParser(BaseParser):
    """黄果短剧(huguoai)解析实现。"""

    def parse_src(self, html):
        m = _RE_VIDEO_SRC.search(html)
        if not m:
            return None
        src = _unescape(m.group(1))
        return src if ".m3u8" in src else None

    def parse_detail(self, html, vid):
        m = _RE_TITLE.search(html)
        title = clean_title(m.group(1).split(" - ")[0]) if m else f"series_{vid}"
        eps = set(int(ep) for _, ep in _RE_EP_LINK.findall(html))
        max_ep = max(eps) if eps else 0
        # 海报：优先 coverSrc/postersrc，og:image 兜底
        poster = ""
        pm = _RE_COVER_SRC.search(html) or _RE_POSTER_SRC.search(html)
        if pm:
            poster = _unescape(pm.group(1))
        if not poster:
            om = _RE_OG_IMAGE.search(html)
            if om:
                poster = om.group(1).replace("&amp;", "&")
                poster = _unescape(poster)
        # 剧情简介：优先 <meta name="description">，再 JSON-LD description
        # （站点通用简介特征词一并过滤，防"作品平台"类文案混入）
        _JUNK = ("高清视频", "一站式平台", "作品平台", "免费在线观看", "每日更新")
        desc = ""
        mm = _RE_META_DESC.search(html)
        if mm:
            cand = (mm.group(1).replace("&amp;", "&").replace("&#39;", "'")
                    .replace("&quot;", '"').strip())
            if cand and len(cand) > 10 and not any(j in cand for j in _JUNK):
                desc = cand
        if not desc:
            for cand in _RE_DESC.findall(html):
                c = (cand.replace("\\u0026", "&").replace("\\u002F", "/")
                     .replace("\\n", " ").replace("\\/", "/")
                     .replace("\\'", "'").replace('\\"', '"').strip())
                if c and len(c) > 10 and not any(j in c for j in _JUNK):
                    desc = c
                    break
        return title, max_ep, poster, desc

    def parse_poster(self, video_html):
        m = _RE_POSTER_SRC.search(video_html)
        return _unescape(m.group(1)) if m else ""

    def parse_list(self, html):
        pairs = _RE_ITEMLIST.findall(html)
        out = []
        for title, vid in pairs:
            t = (title.replace("\\u0026", "&").replace("\\u002F", "/")
                 .replace("\\/", "/").strip())
            out.append((clean_title(t) if t else f"series_{vid}", vid))
        return out

    def parse_plain_detail_ids(self, html):
        return _RE_PLAIN_DETAIL.findall(html)


# ── 解析器工厂（升级接口：多站点注册） ──
_PARSER_REGISTRY = {}


def register(name):
    def deco(cls):
        _PARSER_REGISTRY[name] = cls
        return cls
    return deco


register("huangguoai")(HuangguoParser)


def get_parser(name="huangguoai"):
    """按名字取解析器实例。新站点注册后即可用。"""
    cls = _PARSER_REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"未知解析器: {name}，可注册: {list(_PARSER_REGISTRY)}")
    return cls()
