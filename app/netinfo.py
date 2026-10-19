"""探测本机对外的局域网 IPv4 地址。

只做一次路由查询，不向外部发送任何数据，也不读取网卡清单。
"""

from __future__ import annotations

import socket


def lan_address() -> str:
    """返回默认路由的出口地址；取不到时返回空字符串。

    UDP connect 不会真正发包，只是让内核选出路由，因此离线也能工作。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        address = sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()
    # 排除回环与 IPv4 链路本地地址（169.254/16，通常是没拿到 DHCP 时的自分配地址）。
    if not address or address.startswith(("127.", "169.254.")):
        return ""
    return address
