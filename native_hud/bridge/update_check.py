# -*- coding: utf-8 -*-
"""检测 GitHub 最新发布版,多源轮询(有人连不上 GitHub)。

要点(实测得来):
  · **直连,不走系统代理**:不少用户的系统代理(VPN/Clash 残留规则、企业代理)会把这些
    请求路由坏掉 —— 实测同机「系统代理」下 github-api 失败,而「直连」+ jsdelivr 全部成功。
    所以这里统一用一个空 ProxyHandler 的 opener 直连;最后才兜底用系统代理重试一次。
  · **jsdelivr 是国内可达的主力**:它有国内 CDN 节点,免代理可达;5 个边缘节点实测全通。
    旧的 ghproxy 系镜像大多已死(403/超时/DNS),且死镜像每个要等 ~7s 超时,拖慢检测 → 已删。

依次试多个源,首个成功即返回最新版本号;全程 urllib(stdlib,免依赖),每源短超时;
调用方请放后台线程跑,别卡 GUI。
"""
from __future__ import annotations
import json
import re
import urllib.request

REPO = "Airexplosion/yixian-hud"
RELEASES_URL = "https://github.com/%s/releases" % REPO   # 给用户点【去下载】

_UA = {"User-Agent": "YiXianHUD-update-check"}
_TIMEOUT = 6

# 直连 opener:不读系统代理设置(getproxies),避免被坏掉的系统代理路由失败。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# jsdelivr 边缘节点(读 main 上的 hud_version.py;发布时 dev 会同步 bump 该文件)。
# 实测国内可达、免代理;多节点冗余,挂一个不影响其它。
_JSD_CDN_HOSTS = [
    "cdn.jsdelivr.net",
    "fastly.jsdelivr.net",
    "gcore.jsdelivr.net",
    "quantil.jsdelivr.net",
    "testingcf.jsdelivr.net",
]


def _norm(tag):
    """'v1.0.6' / '1.0.6' / 'V1.2' → (1,0,6) 元组;取不到数字 → None。"""
    if not tag:
        return None
    m = re.search(r"(\d+(?:\.\d+)+)", str(tag))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _get(url, timeout=_TIMEOUT, opener=_DIRECT):
    req = urllib.request.Request(url, headers=_UA)
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _src_api(opener=_DIRECT):
    """GitHub releases/latest 的 JSON → tag_name(未被墙用户直连可达)。"""
    url = "https://api.github.com/repos/%s/releases/latest" % REPO
    return json.loads(_get(url, opener=opener)).get("tag_name")


def _src_jsdelivr_data():
    """jsdelivr 的 gh 包元数据:{tags:{latest},versions:[...]} → 最新 tag(国内可达)。"""
    j = json.loads(_get("https://data.jsdelivr.com/v1/packages/gh/%s" % REPO))
    return (j.get("tags") or {}).get("latest") or (j.get("versions") or [None])[0]


def _src_jsdelivr_file(host):
    """读 main 上的 hud_version.py 里 HUD_VERSION(发布时 dev 会同步 bump)。
    jsdelivr CDN 有国内节点、免代理可达;分支内容缓存 ~12h,检测延迟可接受。"""
    x = _get("https://%s/gh/%s@main/native_hud/bridge/hud_version.py" % (host, REPO))
    m = re.search(r'HUD_VERSION\s*=\s*["\']([\d.]+)', x)
    return m.group(1) if m else None


def _src_atom(opener=_DIRECT):
    """GitHub releases.atom(另一 GitHub 域,api 被挡时偶尔仍可达)→ 最新 tag。"""
    x = _get("https://github.com/%s/releases.atom" % REPO, opener=opener)
    m = re.search(r"/releases/tag/([^<\"]+)", x)
    return m.group(1) if m else None


def _sources():
    """(名字, 取版本函数) 序列;按 可达性/新鲜度 排序。全部直连(不走系统代理)。"""
    yield ("github-api", _src_api)                 # 未被墙用户直连最快最准
    yield ("jsdelivr-data", _src_jsdelivr_data)    # 国内可达,取最新 tag(较新鲜)
    for h in _JSD_CDN_HOSTS:                        # 国内可达 CDN,读 main 版本号(冗余)
        yield ("jsdelivr:" + h, (lambda hh=h: _src_jsdelivr_file(hh)))
    yield ("github-atom", _src_atom)               # api 被挡时的另一 GitHub 域兜底
    # 最后兜底:用系统代理重试 github-api(只有必须走代理才能上网的环境才轮到这条)。
    yield ("github-api-proxied", (lambda: _src_api(opener=urllib.request.build_opener())))


def latest_version():
    """轮询所有源,返回首个成功的最新版本号字符串(可能带 v);全失败 → None。"""
    for _name, fn in _sources():
        try:
            tag = fn()
            if _norm(tag):
                return str(tag)
        except Exception:
            continue
    return None


def check_update(current):
    """→ {current, latest, has_update, ok}。ok=False = 所有源都失败(离线/全被墙)。"""
    latest = latest_version()
    if latest is None:
        return {"current": current, "latest": None, "has_update": False, "ok": False}
    cv, lv = _norm(current), _norm(latest)
    return {"current": current, "latest": latest,
            "has_update": bool(cv and lv and lv > cv), "ok": True}
