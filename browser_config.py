from dataclasses import dataclass, field
from typing import Any

from proxy_menager import ProxyConfig, ProxyManager


@dataclass(frozen=True)
class FirefoxBrowserConfig:
    """Settings only: pass these dicts to Playwright when creating the browser."""

    headless: bool = False
    slow_mo: int = 50
    timeout: int = 60_000
    viewport_width: int = 1366
    viewport_height: int = 768
    locale: str = "ru-RU"
    timezone_id: str = "Europe/Moscow"
    proxy: str | ProxyConfig | None = None
    proxy_scheme: str = "socks5"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    )
    extra_http_headers: dict[str, str] = field(
        default_factory=lambda: {
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    @property
    def launch_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "timeout": self.timeout,
            "firefox_user_prefs": {
                "intl.accept_languages": "ru-RU, ru, en-US, en",
                "media.navigator.streams.fake": False,
                "media.navigator.permission.disabled": False,
                "privacy.resistFingerprinting": False,
            },
        }

        proxy = self.proxy_options
        if proxy is not None:
            options["proxy"] = proxy

        return options

    @property
    def proxy_options(self) -> dict[str, Any] | None:
        return ProxyManager.to_playwright_proxy(
            self.proxy,
            default_scheme=self.proxy_scheme,
        )

    @property
    def context_options(self) -> dict[str, Any]:
        return {
            "viewport": {
                "width": self.viewport_width,
                "height": self.viewport_height,
            },
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "user_agent": self.user_agent,
            "extra_http_headers": self.extra_http_headers,
            "java_script_enabled": True,
            "ignore_https_errors": False,
        }


DEFAULT_FIREFOX_CONFIG = FirefoxBrowserConfig()
