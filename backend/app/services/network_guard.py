"""Where a connection may point. A saved host is a place the server will open a network
connection to on an admin's behalf, so it is checked before every use, not only when saved.

Refused: anything that is not a plain host name or IP address (no URLs, no credentials, no
spaces), addresses that reach this machine's own services or cloud metadata (loopback unless
allowed for development, link-local, unspecified, multicast, reserved), and this app's own
database. Every address a name resolves to must pass, not just one.

A name is resolved here and again by the database driver, which opens the connection. A DNS
answer that changes in between is the one gap this cannot close; TLS with certificate checking
(the default, `verify-full`) closes it, because the other machine cannot present a valid
certificate for the name. EXTERNAL_DB_ALLOWED_HOSTS shrinks it further.
"""

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import AppError

HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")
IPV6 = re.compile(r"^[0-9A-Fa-f:.]{2,45}$")

# Addresses where cloud providers answer with credentials for the machine itself.
METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254")
)
METADATA_NAMES = frozenset({"metadata.google.internal", "metadata", "instance-data"})


class TargetNotAllowedError(AppError):
    status_code = 400
    code = "target_not_allowed"


@dataclass(frozen=True, slots=True)
class Target:
    host: str
    port: int
    database: str


def valid_host_syntax(host: str) -> bool:
    return bool(HOST.fullmatch(host) or IPV6.fullmatch(host))


def _unwrap(address: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """An IPv4 address written as IPv6 (::ffff:127.0.0.1) is judged as the IPv4 address."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def judge(address: ipaddress.IPv4Address | ipaddress.IPv6Address, settings: Settings) -> str | None:
    """None when the address may be used, else why not."""
    address = _unwrap(address)
    if address in METADATA_ADDRESSES:
        return "that address belongs to the cloud provider's metadata service"
    # Loopback first: Python also calls ::1 "reserved".
    if address.is_loopback:
        if settings.external_db_allow_loopback:
            return None
        return "this machine itself (localhost) is not allowed"
    if address.is_link_local:
        return "link-local addresses are not allowed"
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        return "that is not an address of a database server"
    if address.is_private and not settings.external_db_allow_private:
        return "addresses on private networks are not allowed"
    return None


async def resolve(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        found = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError:
        raise TargetNotAllowedError("The host name could not be found.") from None
    addresses = set()
    for _family, _type, _proto, _canon, sockaddr in found:
        text = str(sockaddr[0]).split("%", 1)[0]  # an IPv6 scope id is not part of the address
        addresses.add(ipaddress.ip_address(text))
    if not addresses:
        raise TargetNotAllowedError("The host name could not be found.")
    return addresses


async def check_target(target: Target, settings: Settings, ssl_mode: str = "verify-full") -> None:
    """Raises TargetNotAllowedError unless the connection may be opened."""
    host = target.host.strip().lower()
    if not valid_host_syntax(host):
        raise TargetNotAllowedError(
            "The host must be a plain name or IP address (no http://, no user@, no path)."
        )
    if host in METADATA_NAMES or (host.endswith(".internal") and "metadata" in host):
        raise TargetNotAllowedError("That host is not allowed.")
    allowed = [h.strip().lower() for h in settings.external_db_allowed_hosts]
    if allowed and host not in allowed:
        raise TargetNotAllowedError(
            "That host is not on the list of allowed hosts (EXTERNAL_DB_ALLOWED_HOSTS)."
        )

    addresses = await resolve(host, target.port)
    for address in addresses:
        reason = judge(address, settings)
        if reason:
            raise TargetNotAllowedError(f"That host is not allowed: {reason}.")

    if ssl_mode == "disable" and any(_unwrap(a).is_global for a in addresses):
        raise TargetNotAllowedError(
            "An unencrypted connection to a public address is not allowed. Turn SSL on."
        )

    await _refuse_own_database(target, addresses, settings)


async def _refuse_own_database(
    target: Target,
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
    settings: Settings,
) -> None:
    """The app's own database holds accounts, password hashes and every chat: never a source."""
    own = settings.sqlalchemy_url
    if (own.database or "").lower() != target.database.lower():
        return
    if (own.port or 5432) != target.port:
        return
    own_host = (own.host or "localhost").lower()
    if own_host == target.host.strip().lower():
        raise TargetNotAllowedError(
            "That is this app's own database; it can't be used as a source."
        )
    try:
        own_addresses = await resolve(own_host, target.port)
    except TargetNotAllowedError:
        return
    same = {_unwrap(a) for a in addresses} & {_unwrap(a) for a in own_addresses}
    both_loopback = all(_unwrap(a).is_loopback for a in addresses) and all(
        _unwrap(a).is_loopback for a in own_addresses
    )
    if same or both_loopback:
        raise TargetNotAllowedError(
            "That is this app's own database; it can't be used as a source."
        )
