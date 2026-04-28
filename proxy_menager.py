from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks4", "socks5"}


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    scheme: str = "socks5"

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("Хост прокси не может быть пустым")
        if not 1 <= int(self.port) <= 65_535:
            raise ValueError("Порт прокси должен быть от 1 до 65535")
        if self.scheme not in SUPPORTED_PROXY_SCHEMES:
            raise ValueError(f"Неподдерживаемая схема прокси: {self.scheme}")

    @property
    def server(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def to_playwright(self) -> dict[str, Any]:
        proxy: dict[str, Any] = {"server": self.server}
        if self.username:
            proxy["username"] = self.username
        if self.password:
            proxy["password"] = self.password
        return proxy


class ProxyManager:
    """Converts proxy strings to Playwright proxy settings."""

    @staticmethod
    def parse_proxy(proxy_str: str, default_scheme: str = "socks5") -> ProxyConfig:
        value = proxy_str.strip()
        if not value:
            raise ValueError("Прокси не может быть пустым")

        if "://" in value:
            parsed = urlparse(value)
            if parsed.hostname is None or parsed.port is None:
                raise ValueError(f"Неверный формат прокси: {proxy_str}")
            return ProxyConfig(
                host=parsed.hostname,
                port=parsed.port,
                username=parsed.username,
                password=parsed.password,
                scheme=parsed.scheme,
            )

        parts = value.split(":")
        if len(parts) == 2:
            host, port = parts
            return ProxyConfig(host=host, port=int(port), scheme=default_scheme)

        if len(parts) == 4:
            host, port, username, password = parts
            return ProxyConfig(
                host=host,
                port=int(port),
                username=username or None,
                password=password or None,
                scheme=default_scheme,
            )

        raise ValueError(
            "Неверный формат прокси. Используй host:port, "
            "host:port:user:password или scheme://user:password@host:port"
        )

    @classmethod
    def to_playwright_proxy(
        cls,
        proxy: str | ProxyConfig | None,
        default_scheme: str = "socks5",
    ) -> dict[str, Any] | None:
        if proxy is None:
            return None
        if isinstance(proxy, ProxyConfig):
            return proxy.to_playwright()
        return cls.parse_proxy(proxy, default_scheme=default_scheme).to_playwright()

    @classmethod
    def is_valid_proxy(cls, proxy: str | ProxyConfig | None) -> bool:
        try:
            return cls.to_playwright_proxy(proxy) is not None
        except (TypeError, ValueError):
            return False
