from dataclasses import dataclass
from typing import Any

from camoufox.async_api import AsyncCamoufox  

from proxy_menager import ProxyConfig, ProxyManager


@dataclass(frozen=True)
class CamoufoxBrowserConfig:

    headless: bool = False
    humanize: bool | float = 1.5
    timeout: int = 60_000
    slow_mo: int = 50
    browser_hold_ms: int = 0
    max_concurrent_browsers: int = 1
    ensure_browser: bool = True
    executable_path: str | None = None
    geoip: bool = False
    debug: bool = False
    proxy: str | ProxyConfig | None = None
    proxy_scheme: str = "socks5"

    @property
    def proxy_options(self) -> dict[str, Any] | None:
        return ProxyManager.to_playwright_proxy(
            self.proxy,
            default_scheme=self.proxy_scheme,
        )

    @property
    def launch_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "headless": self.headless,
            "humanize": self.humanize,
            "geoip": self.geoip,
            "slow_mo": self.slow_mo,
            "timeout": self.timeout,
            "debug": self.debug,
        }

        proxy = self.proxy_options
        if proxy is not None:
            options["proxy"] = proxy

        if self.executable_path:
            options["executable_path"] = self.executable_path

        return options


DEFAULT_CAMOUFOX_CONFIG = CamoufoxBrowserConfig()


def camoufox_browser(config: CamoufoxBrowserConfig = DEFAULT_CAMOUFOX_CONFIG):
    return AsyncCamoufox(**config.launch_options)
