"""Normalize proxy settings for Playwright and requests."""

from urllib.parse import quote


def _split_proxy_text(value, default_scheme="http"):
    raw = str(value or "").strip()
    if not raw:
        return None

    if "://" in raw:
        scheme, authority = raw.split("://", 1)
    else:
        scheme, authority = default_scheme, raw
    scheme = scheme.lower().strip()

    username = ""
    password = ""
    if "@" in authority:
        userinfo, authority = authority.rsplit("@", 1)
        if ":" in userinfo:
            username, password = userinfo.split(":", 1)
        else:
            username = userinfo
    else:
        parts = authority.split(":", 3)
        if len(parts) == 4 and parts[1].isdigit():
            authority, username, password = (
                f"{parts[0]}:{parts[1]}",
                parts[2],
                parts[3],
            )

    if ":" not in authority:
        raise ValueError("代理地址必须包含 host:port")
    host, port = authority.rsplit(":", 1)
    if not host or not port.isdigit():
        raise ValueError("代理地址的 host 或 port 无效")

    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
    }


def parse_proxy(proxy, default_scheme="http"):
    """Parse string or structured proxy settings into normalized fields."""
    if not proxy:
        return None
    if isinstance(proxy, dict):
        parsed = _split_proxy_text(
            proxy.get("server", ""),
            default_scheme=default_scheme,
        )
        if parsed is None:
            return None
        parsed["username"] = str(
            proxy.get("username", parsed["username"])
        ).strip()
        parsed["password"] = str(
            proxy.get("password", parsed["password"])
        )
        return parsed
    return _split_proxy_text(proxy, default_scheme=default_scheme)


def build_playwright_proxy(proxy):
    parsed = parse_proxy(proxy, default_scheme="http")
    if parsed is None:
        return None
    scheme = "socks5" if parsed["scheme"] in ("socks5", "socks5h") else parsed["scheme"]
    server = f'{scheme}://{parsed["host"]}:{parsed["port"]}'
    result = {"server": server, "bypass": "localhost"}
    if scheme == "socks5" and parsed["username"]:
        # Chromium rejects Playwright's separate username/password fields
        # for SOCKS5. Embedding userinfo lets the browser start the proxy.
        user = quote(parsed["username"], safe="")
        password = quote(parsed["password"], safe="")
        result["server"] = (
            f"socks5://{user}:{password}@"
            f'{parsed["host"]}:{parsed["port"]}'
        )
    else:
        if parsed["username"]:
            result["username"] = parsed["username"]
        if parsed["password"]:
            result["password"] = parsed["password"]
    return result


def build_requests_proxy(proxy):
    parsed = parse_proxy(proxy, default_scheme="http")
    if parsed is None:
        return None
    scheme = "socks5h" if parsed["scheme"] in ("socks5", "socks5h") else parsed["scheme"]
    auth = ""
    if parsed["username"]:
        auth = quote(parsed["username"], safe="")
        if parsed["password"]:
            auth += ":" + quote(parsed["password"], safe="")
        auth += "@"
    return f'{scheme}://{auth}{parsed["host"]}:{parsed["port"]}'
