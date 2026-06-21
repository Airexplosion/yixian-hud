# -*- coding: utf-8 -*-
"""YiXianHUD 版本号(单一来源)。

发布时 build_hud.py 会用 CI 的 tag(GITHUB_REF_NAME,如 v1.0.7)覆盖 HUD_VERSION,
所以**发布版的"当前版本"永远等于它的 release tag**;本地/手动构建用这里的默认值。
"""
HUD_VERSION = "1.0.12"
