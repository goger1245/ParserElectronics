from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from playwright.async_api import (
    Browser,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from browser_config import DEFAULT_FIREFOX_CONFIG, FirefoxBrowserConfig
from logger import get_logger


logger = get_logger(__name__)
PRICE_RE = re.compile(r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:₽|руб\.?|р\.)", re.I)


@dataclass(frozen=True)
class ShopConfig:
    name: str
    home_url: str
    search_url: str
    search_selectors: tuple[str, ...]
    result_selectors: tuple[str, ...]


@dataclass(frozen=True)
class ProductOffer:
    shop: str
    title: str
    price: int
    raw_price: str
    url: str

    @property
    def formatted_price(self) -> str:
        return f"{self.price:,}".replace(",", " ") + " ₽"


@dataclass(frozen=True)
class ShopResult:
    shop: str
    offer: ProductOffer | None = None
    error: str | None = None


@dataclass(frozen=True)
class SearchSummary:
    query: str
    results: list[ShopResult]

    @property
    def best_offer(self) -> ProductOffer | None:
        offers = [result.offer for result in self.results if result.offer is not None]
        if not offers:
            return None
        return min(offers, key=lambda offer: offer.price)


SHOPS: tuple[ShopConfig, ...] = (
    ShopConfig(
        name="DNS",
        home_url="https://www.dns-shop.ru/",
        search_url="https://www.dns-shop.ru/search/?q={query}",
        search_selectors=(
            "input[name='q']",
            "input[type='search']",
            "input[placeholder*='Поиск']",
            "input[placeholder*='поиск']",
        ),
        result_selectors=(
            ".catalog-product",
            ".catalog-product__name",
            "[data-id='product']",
        ),
    ),
    ShopConfig(
        name="Citilink",
        home_url="https://www.citilink.ru/",
        search_url="https://www.citilink.ru/search/?text={query}",
        search_selectors=(
            "input[name='text']",
            "input[type='search']",
            "input[placeholder*='Поиск']",
            "input[placeholder*='поиск']",
        ),
        result_selectors=(
            "[data-meta-name='ProductCardLayout']",
            "[data-meta-name='Snippet__title']",
            ".product-card",
        ),
    ),
    ShopConfig(
        name="OnlineTrade",
        home_url="https://www.onlinetrade.ru/",
        search_url="https://www.onlinetrade.ru/sitesearch.html?query={query}",
        search_selectors=(
            "input[name='query']",
            "input[type='search']",
            "input[placeholder*='Поиск']",
            "input[placeholder*='поиск']",
        ),
        result_selectors=(
            ".indexGoods__item",
            ".catalog__displayedItem",
            ".catalogItem",
        ),
    ),
)


async def search_all_shops(
    query: str,
    browser_config: FirefoxBrowserConfig = DEFAULT_FIREFOX_CONFIG,
) -> SearchSummary:
    query = query.strip()
    if not query:
        raise ValueError("Введите название техники для поиска")

    logger.info("Запускаю параллельный поиск: %s", query)
    async with async_playwright() as playwright:
        tasks = [
            _search_shop(playwright.firefox, shop, query, browser_config)
            for shop in SHOPS
        ]
        results = await asyncio.gather(*tasks)

    return SearchSummary(query=query, results=list(results))


async def _search_shop(
    firefox,
    shop: ShopConfig,
    query: str,
    browser_config: FirefoxBrowserConfig,
) -> ShopResult:
    browser: Browser | None = None
    try:
        logger.info("[%s] Открываю Firefox", shop.name)
        browser = await firefox.launch(**browser_config.launch_options)
        context = await browser.new_context(**browser_config.context_options)
        page = await context.new_page()
        page.set_default_timeout(browser_config.timeout)
        await _open_search_page(page, shop, query)
        await _wait_for_results(page, shop)

        candidates = await _extract_candidates(page, shop.name, query)
        if not candidates:
            logger.warning("[%s] Товары с ценой не найдены", shop.name)
            return ShopResult(shop=shop.name, error="Товары с ценой не найдены")

        best = _choose_best_candidate(candidates, query)
        logger.info("[%s] Лучший оффер: %s за %s", shop.name, best.title, best.formatted_price)
        return ShopResult(shop=shop.name, offer=best)
    except PlaywrightTimeoutError:
        logger.warning("[%s] Сайт долго не отвечает", shop.name)
        return ShopResult(shop=shop.name, error="Сайт долго не отвечает")
    except PlaywrightError as exc:
        logger.error("[%s] Ошибка Playwright: %s", shop.name, exc)
        return ShopResult(shop=shop.name, error=f"Ошибка Playwright: {exc}")
    except Exception as exc:
        logger.exception("[%s] Неожиданная ошибка", shop.name)
        return ShopResult(shop=shop.name, error=f"Ошибка: {exc}")
    finally:
        if browser is not None:
            await browser.close()


async def _open_search_page(page: Page, shop: ShopConfig, query: str) -> None:
    await page.goto(shop.home_url, wait_until="domcontentloaded")

    for selector in shop.search_selectors:
        field = page.locator(selector).first
        try:
            await field.wait_for(state="visible", timeout=5_000)
            await field.fill(query)
            await field.press("Enter")
            break
        except PlaywrightTimeoutError:
            continue
        except PlaywrightError:
            continue
    else:
        await page.goto(shop.search_url.format(query=quote_plus(query)), wait_until="domcontentloaded")

    try:
        await page.wait_for_load_state("networkidle", timeout=12_000)
    except PlaywrightTimeoutError:
        pass


async def _wait_for_results(page: Page, shop: ShopConfig) -> None:
    for selector in shop.result_selectors:
        try:
            await page.locator(selector).first.wait_for(state="attached", timeout=8_000)
            return
        except PlaywrightTimeoutError:
            continue

    await page.wait_for_timeout(2_000)


async def _extract_candidates(page: Page, shop_name: str, query: str) -> list[ProductOffer]:
    raw_candidates = await page.evaluate(
        """
        ({ query }) => {
            const priceRe = /\\d[\\d\\s\\u00a0]*(?:[.,]\\d{1,2})?\\s*(?:₽|руб\\.?|р\\.)/i;
            const words = query.toLowerCase().split(/\\s+/).filter((word) => word.length > 2);

            const isVisible = (node) => {
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== "hidden"
                    && style.display !== "none"
                    && rect.width > 0
                    && rect.height > 0;
            };

            const scoreTitle = (title) => {
                const lower = title.toLowerCase();
                return words.reduce((score, word) => score + (lower.includes(word) ? 1 : 0), 0);
            };

            const containers = Array.from(document.querySelectorAll("article, li, div"))
                .filter((node) => {
                    const text = node.innerText || "";
                    const linkCount = node.querySelectorAll("a[href]").length;
                    return isVisible(node)
                        && text.length >= 30
                        && text.length <= 2500
                        && linkCount > 0
                        && linkCount <= 20
                        && priceRe.test(text);
                })
                .slice(0, 400);

            const candidates = [];
            const seen = new Set();

            for (const container of containers) {
                const links = Array.from(container.querySelectorAll("a[href]"))
                    .filter((link) => isVisible(link))
                    .map((link) => ({
                        title: (link.innerText || link.textContent || "").trim().replace(/\\s+/g, " "),
                        url: link.href,
                    }))
                    .filter((link) => link.title.length >= 5 && link.title.length <= 220);

                if (!links.length) {
                    continue;
                }

                links.sort((left, right) => scoreTitle(right.title) - scoreTitle(left.title));
                const link = links[0];
                const priceMatch = (container.innerText || "").match(priceRe);

                if (!priceMatch) {
                    continue;
                }

                const key = `${link.url}|${priceMatch[0]}|${link.title}`;
                if (seen.has(key)) {
                    continue;
                }
                seen.add(key);

                candidates.push({
                    title: link.title,
                    raw_price: priceMatch[0].trim(),
                    url: link.url,
                    score: scoreTitle(link.title),
                });
            }

            return candidates.slice(0, 80);
        }
        """,
        {"query": query},
    )

    offers: list[ProductOffer] = []
    for candidate in raw_candidates:
        price = _parse_price(candidate.get("raw_price", ""))
        title = str(candidate.get("title", "")).strip()
        url = str(candidate.get("url", "")).strip()
        if price is None or not title or not url:
            continue
        offers.append(
            ProductOffer(
                shop=shop_name,
                title=title,
                price=price,
                raw_price=str(candidate.get("raw_price", "")).strip(),
                url=url,
            )
        )
    return offers


def _choose_best_candidate(candidates: list[ProductOffer], query: str) -> ProductOffer:
    words = [word.lower() for word in query.split() if len(word) > 2]

    def score(offer: ProductOffer) -> tuple[int, int]:
        title = offer.title.lower()
        matched_words = sum(1 for word in words if word in title)
        return matched_words, -offer.price

    matched = [offer for offer in candidates if score(offer)[0] > 0]
    pool = matched or candidates
    return min(pool, key=lambda offer: offer.price)


def _parse_price(raw_price: str) -> int | None:
    match = PRICE_RE.search(raw_price)
    if not match:
        return None

    digits = re.sub(r"\D", "", match.group(0))
    if not digits:
        return None
    return int(digits)
