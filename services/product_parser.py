from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from playwright.async_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from core.browser_config import (
    DEFAULT_CAMOUFOX_CONFIG,
    CamoufoxBrowserConfig,
    camoufox_browser,
)
from core.browser_runtime import ensure_camoufox_browser
from core.logger import get_logger


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
            ".catalog-products.view-simple[data-catalog-products]",
            ".catalog-products.view-simple[data-catalog-products] .catalog-product[data-id='product']",
            ".catalog-products[data-catalog-products]",
            ".catalog-products[data-catalog-products] .catalog-product",
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
            "[data-meta-name='ProductListLayout']",
            "[data-meta-name='ProductVerticalSnippet']",
            "[data-meta-name='SnippetProductVerticalLayout']",
            "[data-meta-name='ProductCardLayout']",
            "[data-meta-name='Snippet__title']",
            ".product-card",
        ),
    ),
    ShopConfig(
        name="М.Видео",
        home_url="https://www.mvideo.ru/",
        search_url="https://www.mvideo.ru/product-list-page?q={query}",
        search_selectors=(
            "input[name='search']",
            "input[name='q']",
            "input[type='search']",
            "input[placeholder*='Поиск']",
            "input[placeholder*='поиск']",
        ),
        result_selectors=(
            ".products-list a[mvid-product-card]",
            "a[mvid-product-card]",
            "[data-testid='product-card']",
            "[data-test-id='product-card']",
            ".product-card",
            ".product-cards-layout",
            "mvid-plp-product-card",
        ),
    ),
)


async def search_all_shops(
    query: str,
    browser_config: CamoufoxBrowserConfig = DEFAULT_CAMOUFOX_CONFIG,
) -> SearchSummary:
    query = query.strip()
    if not query:
        raise ValueError("Введите название техники для поиска")

    if browser_config.ensure_browser:
        ensure_camoufox_browser()

    logger.info("Запускаю параллельный поиск: %s", query)
    semaphore = asyncio.Semaphore(max(1, browser_config.max_concurrent_browsers))

    async def limited_search(shop: ShopConfig) -> ShopResult:
        async with semaphore:
            return await _search_shop(shop, query, browser_config)

    tasks = [
        limited_search(shop)
        for shop in SHOPS
    ]
    results = await asyncio.gather(*tasks)

    return SearchSummary(query=query, results=list(results))


async def _search_shop(
    shop: ShopConfig,
    query: str,
    browser_config: CamoufoxBrowserConfig,
) -> ShopResult:
    try:
        logger.info("[%s] Открываю Camoufox", shop.name)
        async with camoufox_browser(browser_config) as browser:
            page = await browser.new_page()
            page.set_default_timeout(browser_config.timeout)
            page.set_default_navigation_timeout(browser_config.timeout)
            await _open_search_page(page, shop, query)
            await _wait_for_results(page, shop)

            candidates = await _extract_candidates(page, shop.name, query)
            if not candidates:
                logger.warning("[%s] Товары с ценой не найдены", shop.name)
                result = ShopResult(shop=shop.name, error="Товары с ценой не найдены")
            else:
                best = _choose_best_candidate(candidates, query)
                logger.info(
                    "[%s] Лучший оффер: %s за %s",
                    shop.name,
                    best.title,
                    best.formatted_price,
                )
                result = ShopResult(shop=shop.name, offer=best)

            if not browser_config.headless and browser_config.browser_hold_ms > 0:
                logger.info(
                    "[%s] Оставляю Camoufox открытым на %.1f сек.",
                    shop.name,
                    browser_config.browser_hold_ms / 1000,
                )
                await asyncio.sleep(browser_config.browser_hold_ms / 1000)

            return result
    except PlaywrightTimeoutError:
        logger.warning("[%s] Сайт долго не отвечает", shop.name)
        return ShopResult(shop=shop.name, error="Сайт долго не отвечает")
    except PlaywrightError as exc:
        logger.error("[%s] Ошибка Camoufox/Playwright: %s", shop.name, exc)
        return ShopResult(shop=shop.name, error=f"Ошибка Camoufox: {exc}")
    except Exception as exc:
        logger.exception("[%s] Неожиданная ошибка", shop.name)
        return ShopResult(shop=shop.name, error=f"Ошибка: {exc}")


async def _open_search_page(
    page: Page,
    shop: ShopConfig,
    query: str,
) -> None:
    search_url = shop.search_url.format(query=quote_plus(query))
    logger.info("[%s] Открываю страницу поиска: %s", shop.name, search_url)
    try:
        await page.goto(search_url, wait_until="commit", timeout=45_000)
    except PlaywrightTimeoutError:
        logger.warning("[%s] Навигация долго не завершается, пробую текущий DOM", shop.name)

    if shop.name == "DNS":
        await _wait_for_dns_page_ready(page)
        return

    if shop.name == "Citilink":
        await _wait_for_citilink_page_ready(page)
        return

    if shop.name == "М.Видео":
        await _wait_for_mvideo_page_ready(page)
        return

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except PlaywrightTimeoutError:
        pass

    try:
        await page.wait_for_load_state("load", timeout=10_000)
    except PlaywrightTimeoutError:
        pass


async def _wait_for_citilink_page_ready(page: Page) -> None:
    for state, timeout in (("domcontentloaded", 20_000), ("load", 15_000)):
        try:
            await page.wait_for_load_state(state, timeout=timeout)
        except PlaywrightTimeoutError:
            pass

    try:
        await page.locator("[data-meta-name='ProductListLayout']").first.wait_for(
            state="attached",
            timeout=30_000,
        )
        await page.locator("[data-meta-name='ProductVerticalSnippet']").first.wait_for(
            state="attached",
            timeout=30_000,
        )
        await page.locator("[data-meta-name='Snippet__title']").first.wait_for(
            state="attached",
            timeout=20_000,
        )
        await page.locator("[data-meta-name='Snippet__price']").first.wait_for(
            state="attached",
            timeout=20_000,
        )
    except PlaywrightTimeoutError:
        await page.wait_for_timeout(4_000)


async def _wait_for_mvideo_page_ready(page: Page) -> None:
    for state, timeout in (("domcontentloaded", 20_000), ("load", 15_000)):
        try:
            await page.wait_for_load_state(state, timeout=timeout)
        except PlaywrightTimeoutError:
            pass

    selectors = (
        ".products-list a[mvid-product-card]",
        "a[mvid-product-card]",
        "[data-testid='product-card']",
        "[data-test-id='product-card']",
        ".product-card",
        "mvid-plp-product-card",
        "a[href*='/products/']",
    )
    for selector in selectors:
        try:
            await page.locator(selector).first.wait_for(state="attached", timeout=12_000)
            return
        except PlaywrightTimeoutError:
            continue

    await page.wait_for_timeout(4_000)


async def _wait_for_dns_page_ready(page: Page) -> None:
    for state, timeout in (("domcontentloaded", 15_000), ("load", 10_000)):
        try:
            await page.wait_for_load_state(state, timeout=timeout)
        except PlaywrightTimeoutError:
            pass

    try:
        await page.locator(
            ".catalog-products.view-simple[data-catalog-products] "
            ".catalog-product[data-id='product']"
        ).first.wait_for(state="attached", timeout=25_000)
        await page.locator(
            ".catalog-products.view-simple[data-catalog-products] "
            ".catalog-product[data-id='product'] .product-buy__price"
        ).first.wait_for(state="attached", timeout=25_000)
    except PlaywrightTimeoutError:
        await page.wait_for_timeout(3_000)


async def _wait_for_results(page: Page, shop: ShopConfig) -> None:
    for selector in shop.result_selectors:
        try:
            await page.locator(selector).first.wait_for(state="attached", timeout=8_000)
            if shop.name == "DNS":
                await _wait_for_dns_product_block(page)
            if shop.name == "М.Видео":
                await _wait_for_mvideo_product_block(page)
            return
        except PlaywrightTimeoutError:
            continue

    await page.wait_for_timeout(2_000)


async def _wait_for_dns_product_block(page: Page) -> None:
    try:
        await page.locator(
            ".catalog-products.view-simple[data-catalog-products] "
            ".catalog-product[data-id='product'] .product-buy__price"
        ).first.wait_for(state="attached", timeout=10_000)
    except PlaywrightTimeoutError:
        await page.wait_for_timeout(1_500)


async def _wait_for_mvideo_product_block(page: Page) -> None:
    for selector in (
        ".products-list a[mvid-product-card]",
        "a[mvid-product-card]",
        "[data-testid='product-card']",
        "[data-test-id='product-card']",
        ".product-card",
        "mvid-plp-product-card",
    ):
        try:
            await page.locator(selector).first.wait_for(state="attached", timeout=10_000)
            return
        except PlaywrightTimeoutError:
            continue

    await page.wait_for_timeout(1_500)


async def _extract_candidates(page: Page, shop_name: str, query: str) -> list[ProductOffer]:
    if shop_name == "DNS":
        offers = _raw_candidates_to_offers(
            await _extract_dns_candidates(page, query),
            shop_name,
        )
        if offers:
            return offers

    if shop_name == "Citilink":
        offers = _raw_candidates_to_offers(
            await _extract_citilink_candidates(page, query),
            shop_name,
        )
        if offers:
            return offers

    if shop_name == "М.Видео":
        return _raw_candidates_to_offers(
            await _extract_mvideo_candidates(page, query),
            shop_name,
        )

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

    return _raw_candidates_to_offers(raw_candidates, shop_name)


async def _extract_dns_candidates(page: Page, query: str) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        ({ query }) => {
            const words = query.toLowerCase().split(/\\s+/).filter((word) => word.length > 2);

            const scoreTitle = (title) => {
                const lower = title.toLowerCase();
                return words.reduce((score, word) => score + (lower.includes(word) ? 1 : 0), 0);
            };

            const normalizeText = (value) => (value || "").trim().replace(/\\s+/g, " ");
            const productList = document.querySelector(
                ".catalog-products.view-simple[data-catalog-products]"
            ) || document.querySelector(".catalog-products[data-catalog-products]");

            if (!productList) {
                return [];
            }

            const cards = Array.from(productList.querySelectorAll(
                ".catalog-product[data-id='product']"
            ));
            const candidates = [];
            const seen = new Set();

            for (const card of cards) {
                const titleLink = card.querySelector(".catalog-product__name[href]");
                const title = normalizeText(titleLink?.textContent || titleLink?.getAttribute("title"));
                const visiblePrice = normalizeText(card.querySelector(".product-buy__price")?.textContent);
                const dataPrice = card.querySelector(".delivery-info-widget[data-price]")?.getAttribute("data-price");
                const rawPrice = visiblePrice || (dataPrice ? `${dataPrice} ₽` : "");
                const url = titleLink?.href
                    || card.querySelector(".catalog-product__image-link[href]")?.href
                    || card.querySelector("a[href]")?.href;

                if (!title || !rawPrice || !url) {
                    continue;
                }

                const key = `${url}|${rawPrice}|${title}`;
                if (seen.has(key)) {
                    continue;
                }
                seen.add(key);

                candidates.push({
                    title,
                    raw_price: rawPrice,
                    url,
                    score: scoreTitle(title),
                });
            }

            candidates.sort((left, right) => right.score - left.score);
            return candidates.slice(0, 80);
        }
        """,
        {"query": query},
    )


async def _extract_citilink_candidates(page: Page, query: str) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        ({ query }) => {
            const words = query.toLowerCase().split(/\\s+/).filter((word) => word.length > 2);

            const scoreTitle = (title) => {
                const lower = title.toLowerCase();
                return words.reduce((score, word) => score + (lower.includes(word) ? 1 : 0), 0);
            };

            const normalizeText = (value) => (value || "").trim().replace(/\\s+/g, " ");
            const cards = Array.from(document.querySelectorAll(
                "[data-meta-name='ProductVerticalSnippet'], "
                + "[data-meta-name='SnippetProductVerticalLayout']"
            ));
            const candidates = [];
            const seen = new Set();

            for (const card of cards) {
                const titleLink = card.querySelector("[data-meta-name='Snippet__title']");
                const title = normalizeText(titleLink?.textContent || titleLink?.getAttribute("title"));
                const priceNode = card.querySelector(
                    "[data-meta-name='Snippet__price'] [data-meta-price], "
                    + "[data-meta-name='Snippet__price']"
                );
                const rawPrice = priceNode?.getAttribute("data-meta-price")
                    || normalizeText(priceNode?.textContent);
                const url = titleLink?.href
                    || card.querySelector("a[title][href]")?.href
                    || card.querySelector("a[href]")?.href;

                if (!title || !rawPrice || !url) {
                    continue;
                }

                const key = `${url}|${rawPrice}|${title}`;
                if (seen.has(key)) {
                    continue;
                }
                seen.add(key);

                candidates.push({
                    title,
                    raw_price: `${rawPrice} ₽`,
                    url,
                    score: scoreTitle(title),
                });
            }

            candidates.sort((left, right) => right.score - left.score);
            return candidates.slice(0, 80);
        }
        """,
        {"query": query},
    )


async def _extract_mvideo_candidates(page: Page, query: str) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        ({ query }) => {
            const words = query.toLowerCase().split(/\\s+/).filter((word) => word.length > 1);
            const normalizedQuery = query.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, "");
            const gpuQuery = /(?:^|\\s)(rtx|gtx|rx)\\s*\\d{3,4}\\b/i.test(query);
            const pcQuery = /(?:систем|компьютер|пк|desktop|pc)/i.test(query);

            const scoreTitle = (title) => {
                const lower = title.toLowerCase();
                return words.reduce((score, word) => score + (lower.includes(word) ? 1 : 0), 0);
            };

            const normalizeText = (value) => (value || "").trim().replace(/\\s+/g, " ");
            const compactText = (value) => value.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, "");
            const matchesQuery = (title) => {
                if (!words.length) {
                    return true;
                }

                const lower = title.toLowerCase();
                const compact = compactText(title);
                const matchedWords = words.filter((word) => {
                    const compactWord = word.replace(/[^a-zа-яё0-9]+/gi, "");
                    return lower.includes(word) || (compactWord && compact.includes(compactWord));
                }).length;

                return matchedWords === words.length
                    || (normalizedQuery.length >= 4 && compact.includes(normalizedQuery));
            };
            const priceRe = /\\d[\\d\\s\\u00a0]*(?:[.,]\\d{1,2})?\\s*(?:₽|руб\\.?|р\\.)/i;
            const cards = Array.from(document.querySelectorAll(
                ".products-list a[mvid-product-card], "
                + "a[mvid-product-card], "
                + "[data-testid='product-card'], "
                + "[data-test-id='product-card'], "
                + ".product-card, "
                + "mvid-plp-product-card, "
                + "div[class*='product-card']"
            ));
            const candidates = [];
            const seen = new Set();

            for (const card of cards) {
                const titleLink = card.matches?.("a[href*='/products/']")
                    ? card
                    : card.querySelector(
                    "a[href*='/products/'][title], "
                    + "a[href*='/products/'][data-testid*='title'], "
                    + "a[href*='/products/']"
                );
                const titleNode = card.querySelector(
                    ".name, "
                    + "[data-testid*='title'], "
                    + "[data-test-id*='title'], "
                    + ".product-title, "
                    + ".product-title__text"
                );
                const title = normalizeText(
                    titleLink?.getAttribute("title")
                    || titleNode?.textContent
                    || titleLink?.textContent
                );
                const priceNode = card.querySelector(
                    ".current-price, "
                    + "[data-testid*='price'], "
                    + "[data-test-id*='price'], "
                    + ".price__main-value, "
                    + ".price, "
                    + "[class*='price']"
                );
                const priceText = normalizeText(priceNode?.textContent);
                const priceMatch = priceText.match(priceRe);
                const url = titleLink?.href
                    || card.querySelector("a[href*='/products/']")?.href;

                if (!title || !priceMatch || !url || !matchesQuery(title)) {
                    continue;
                }

                const key = `${url}|${priceMatch[0]}|${title}`;
                if (seen.has(key)) {
                    continue;
                }
                seen.add(key);

                candidates.push({
                    title,
                    raw_price: priceMatch[0].trim(),
                    url,
                    score: scoreTitle(title),
                    is_video_card: /^\\s*видеокарта\\b/i.test(title),
                });
            }

            const pool = (
                gpuQuery
                && !pcQuery
                && candidates.some((candidate) => candidate.is_video_card)
            )
                ? candidates.filter((candidate) => candidate.is_video_card)
                : candidates;

            pool.sort((left, right) => {
                if (right.score !== left.score) {
                    return right.score - left.score;
                }
                return left.title.length - right.title.length;
            });
            return pool.slice(0, 80);
        }
        """,
        {"query": query},
    )


def _raw_candidates_to_offers(
    raw_candidates: list[dict[str, object]],
    shop_name: str,
) -> list[ProductOffer]:
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

