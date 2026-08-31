"""统一出网代理配置 —— 全仓唯一来源 (single source of truth).

背景
----
改造前, 代理地址被硬编码散落在 9+ 个脚本里, 且存在**两套不一致**的写法:
  - ``http://127.0.0.1:3067``      HTTP 代理, 实测可用 (CoinGecko ping -> 200)
  - ``socks5h://127.0.0.1:1080``   SOCKS5, 实测端口未监听 (HTTP 000), 已废弃
硬编码 ``socks5h://127.0.0.1:1080`` 的 ``fetch_mcaps.py`` / ``fetch_cg_categories.py``
因此是直接跑不通的 (报错 "解析失败: Expecting value: line 1 column 1").

同时, 沙箱/CI 会自动注入 ``HTTPS_PROXY`` (如 51245 / 61350), 这些代理对本仓所需数据源
一律返回 502。纯 "环境变量优先" 的写法 (如旧 ``manage_token.py``) 反而会选中坏代理。

解析策略
--------
按序取**第一个存活**的候选, 结果缓存 (进程内只探测一次):
  1. ``MX_PROXY``           显式指定 -> 无条件信任, 不探测 (逃生口)
  2. ``DEFAULT_PROXY``      实测稳定的默认代理 (优先于环境变量, 规避沙箱坏注入)
  3. 环境变量 ``HTTPS_PROXY``/``https_proxy``/``HTTP_PROXY``/``http_proxy``
  4. 以上全不可用 -> 回退 ``DEFAULT_PROXY`` (离线场景仍返回可用值, 不阻塞调用方)

"默认优先于环境变量" 看似反常规, 但由上述踩坑史决定: 默认代理在本机长期可用,
而环境变量可能是沙箱注入的坏值。用户如需强制走自定义代理, 设 ``MX_PROXY`` 即可。

用法
----
    from net_config import proxy_url, proxy_opener, proxy_dict, curl_proxy_args

    opener = proxy_opener()                       # urllib
    requests.get(url, proxies=proxy_dict())       # requests
    subprocess.run(["curl", *curl_proxy_args(), url])
"""
from __future__ import annotations

import os
import socket
import urllib.request
from urllib.parse import urlparse

# 实测可用的默认代理 (本机长期监听; 见模块文档)
DEFAULT_PROXY = "http://127.0.0.1:3067"

# 已确认废弃/不可用的历史写法, 仅作文档留档, 解析时会跳过
DEPRECATED_PROXIES = ("socks5h://127.0.0.1:1080",)

_PROBE_TIMEOUT = 0.35  # 秒; 仅 TCP 连接探测, 足够快且不发业务请求
_cache: dict[str, object] = {}


def _host_port(proxy: str) -> tuple[str, int] | None:
    """从代理 URL 解析 (host, port); 解析失败返回 None。"""
    try:
        p = urlparse(proxy if "//" in proxy else "http://" + proxy)
        if not p.hostname or not p.port:
            return None
        return p.hostname, p.port
    except Exception:
        return None


def _alive(proxy: str) -> bool:
    """TCP 连通性探测: 代理端口是否在监听。不做 HTTP 请求, 开销极小。"""
    hp = _host_port(proxy)
    if not hp:
        return False
    try:
        with socket.create_connection(hp, timeout=_PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def _env_proxy() -> str | None:
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(k)
        if v and v not in DEPRECATED_PROXIES:
            return v
    return None


def proxy_url(refresh: bool = False) -> str:
    """返回当前应使用的代理 URL (结果缓存)。

    refresh=True 时放弃缓存重新探测 (网络环境变化后可用)。
    """
    if not refresh and "url" in _cache:
        return str(_cache["url"])

    # 1) 显式逃生口: 无条件信任
    explicit = os.environ.get("MX_PROXY")
    if explicit:
        _cache["url"] = explicit
        return explicit

    # 2) 默认代理优先 (规避沙箱注入的坏环境变量)
    if _alive(DEFAULT_PROXY):
        _cache["url"] = DEFAULT_PROXY
        return DEFAULT_PROXY

    # 3) 环境变量兜底
    env = _env_proxy()
    if env and _alive(env):
        _cache["url"] = env
        return env

    # 4) 全不可用 (离线) -> 仍返回默认值, 由调用方自行优雅降级
    _cache["url"] = DEFAULT_PROXY
    return DEFAULT_PROXY


def reset_cache() -> None:
    """清空解析缓存 (测试或网络环境切换后用)。"""
    _cache.clear()


def proxy_dict() -> dict[str, str]:
    """requests 库用: {"http": url, "https": url}。"""
    u = proxy_url()
    return {"http": u, "https": u}


def proxy_opener() -> urllib.request.OpenerDirector:
    """urllib 用: 已装好 ProxyHandler 的 opener。"""
    u = proxy_url()
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": u, "https": u}))


def curl_proxy_args() -> list[str]:
    """subprocess 调 curl 用: ["-x", <url>] (代理不可用时返回空列表, 即直连)。"""
    u = proxy_url()
    return ["-x", u] if u else []


def apply_env(force: bool = False) -> str:
    """把解析结果写回进程环境变量, 供只认环境变量的子进程/curl 使用。

    force=False (默认) 用 setdefault 语义: **不覆盖**已有的有效环境变量。
    历史上 ``sync_all_panels.py`` 用 ``os.environ[...] = ...`` 强制覆盖,
    会盖掉用户/CI 已配好的代理, 属 bug; 统一走本函数即可。

    返回实际使用的代理 URL。
    """
    u = proxy_url()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if force or not os.environ.get(k):
            os.environ[k] = u
    return u


if __name__ == "__main__":
    print("resolved proxy :", proxy_url())
    print("alive(default) :", _alive(DEFAULT_PROXY))
    print("env proxy      :", _env_proxy())
    print("curl args      :", curl_proxy_args())
