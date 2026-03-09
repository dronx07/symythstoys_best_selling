import asyncio
import json
import math
import random
import re
import logging
from pathlib import Path
from urllib.parse import urljoin
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


class ProductRunner:
    def __init__(self, category_urls, headless=True, min_delay=2, max_delay=5):
        self.category_urls = category_urls
        self.homepage = "https://www.smythstoys.com/fr/fr-fr/"
        self.headless = headless
        self.per_page = 60
        self.browser = None
        self.context = None
        self.playwright = None
        self.product_urls = set()
        self.products = []
        self.args = ["--disable-blink-features=AutomationControlled"]
        self.products_file = Path("products.json")
        self.state_file = Path("category_state.json")
        self.min_delay = min_delay
        self.max_delay = max_delay

    async def start(self):
        logger.info("Starting browser")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless, args=self.args)
        self.context = await self.browser.new_context()
        logger.info("Browser started")

    async def close(self):
        logger.info("Closing browser")
        await self.browser.close()
        await self.playwright.stop()
        logger.info("Browser closed")

    def load_state(self):
        if not self.state_file.exists():
            with open(self.state_file, "w") as f:
                json.dump({"index": 0}, f)
            return 0
        with open(self.state_file) as f:
            return json.load(f).get("index", 0)

    def save_state(self, index):
        with open(self.state_file, "w") as f:
            json.dump({"index": index}, f)
        logger.info(f"Saved state index {index}")

    def load_products(self):
        if not self.products_file.exists():
            return []
        with open(self.products_file, encoding="utf-8") as f:
            return json.load(f)

    def save_products(self, products):
        with open(self.products_file, "w", encoding="utf-8") as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(products)} products to file")

    async def get_total_pages(self, url):
        page = await self.context.new_page()
        await page.goto(url, wait_until="load")
        selector = "div.text-body-30.text-grey-700.whitespace-nowrap.my-5.md\\:my-0"
        await page.wait_for_selector(selector)
        text = await page.locator(selector).inner_text()
        total_products = int(re.search(r"\d+", text.replace(",", "")).group())
        total_pages = math.ceil(total_products / self.per_page)
        await page.close()
        logger.info(f"Category {url} has {total_products} products, {total_pages} pages")
        return total_pages

    def generate_page_urls(self, base_url, total_pages):
        urls = []
        for page in range(1, total_pages + 1):
            count = page * self.per_page
            urls.append((page, f"{base_url}?page={page}&count={count}"))
        logger.info(f"Generated {len(urls)} page URLs for {base_url}")
        return urls

    async def collect_from_page(self, page_number, url):
        page = await self.context.new_page()
        try:
            await page.goto(url, wait_until="load")
            await asyncio.sleep(10)
            await page.wait_for_selector("a.cursor-pointer.flex.flex-col.flex-grow.pb-3")
            locator = page.locator("a.cursor-pointer.flex.flex-col.flex-grow.pb-3")
            hrefs = await locator.evaluate_all("els => els.map(e => e.getAttribute('href'))")
            added = 0
            for h in hrefs:
                if h and "/p/" in h:
                    full_url = urljoin(self.homepage, h)
                    if full_url not in self.product_urls:
                        self.product_urls.add(full_url)
                        added += 1
            logger.info(f"Page {page_number} collected {added} new product URLs")
        except Exception as e:
            logger.error(f"Error collecting page {page_number} {url}: {e}")
        finally:
            await page.close()
            delay = random.uniform(self.min_delay, self.max_delay)
            logger.info(f"Sleeping {delay:.2f}s after page {page_number}")
            await asyncio.sleep(delay)

    async def scrape_product(self, url):
        page = await self.context.new_page()
        try:
            await page.goto(url, wait_until="load")
            #await asyncio.sleep(10)
            name = await page.locator("h1").inner_text()
            price_text = await page.locator("div.flex.flex-wrap.items-start.text-red-400.font-bold.shrink-0.mr-2.ios-price").inner_text()
            price = float(price_text.replace("€", "").replace(",", ".").strip())
            html = await page.content()
            gtin_match = re.search(r"\b\d{13}\b", html)
            gtin = gtin_match.group(0) if gtin_match else ""
            product = {
                "product_name": name.strip(),
                "product_gtin": gtin,
                "supplier_price": price,
                "product_link": url
            }
            self.products.append(product)
            logger.info(f"Scraped product {gtin} from {url}")
        except Exception as e:
            logger.error(f"Error scraping product {url}: {e}")
        finally:
            await page.close()
            delay = random.uniform(self.min_delay, self.max_delay)
            logger.info(f"Sleeping {delay:.2f}s after product {url}")
            await asyncio.sleep(delay)

    async def run(self):
        index = self.load_state()
        if index >= len(self.category_urls):
            logger.info("All categories processed")
            return

        category_url = self.category_urls[index]
        logger.info(f"Processing category index {index}: {category_url}")

        await self.start()

        total_pages = await self.get_total_pages(category_url)
        page_urls = self.generate_page_urls(category_url, total_pages)

        for page_number, page_url in page_urls:
            await self.collect_from_page(page_number, page_url)

        logger.info(f"Total product URLs collected: {len(self.product_urls)}")

        for url in self.product_urls:
            await self.scrape_product(url)

        await self.close()

        existing_products = self.load_products()
        existing_products.extend(self.products)
        self.save_products(existing_products)

        self.save_state(index + 1)

        logger.info(f"Completed category index {index}")


async def main():
    category_urls = ['https://www.smythstoys.com//fr/fr-fr/jouets/figurines/c/SM130101', 'https://www.smythstoys.com//fr/fr-fr/jouets/jouets-prescolaires/c/SM130103', 'https://www.smythstoys.com//fr/fr-fr/jouets/poupees-poupons-et-accessoires/c/SM130104', 'https://www.smythstoys.com//fr/fr-fr/jouets/lego-et-construction/c/lego-et-construction', 'https://www.smythstoys.com//fr/fr-fr/jouets/voitures-et-jeux-de-construction/c/SM130102', 'https://www.smythstoys.com//fr/fr-fr/jouets/activites-artistiques-et-musicales/c/SM130105', 'https://www.smythstoys.com//fr/fr-fr/jouets/jeux-de-societe-et-puzzles/c/SM130106', 'https://www.smythstoys.com//fr/fr-fr/bebe/sieges-auto-et-bases/c/SM130802', 'https://www.smythstoys.com//fr/fr-fr/bebe/landaus-poussettes-et-poussettes-cannes/c/SM130805', 'https://www.smythstoys.com//fr/fr-fr/bebe/puericulture-et-nuit/c/SM130803', 'https://www.smythstoys.com//fr/fr-fr/bebe/biberons-et-repas/c/SM130804', 'https://www.smythstoys.com//fr/fr-fr/bebe/jouets-bebe/c/SM130811', 'https://www.smythstoys.com//fr/fr-fr/bebe/bains-et-hygiene-bebe/c/SM130810', 'https://www.smythstoys.com//fr/fr-fr/jeux-dexterieur/trampolines-balancoires-et-maisons/c/trampolines-balancoires-et-maisons', 'https://www.smythstoys.com//fr/fr-fr/jeux-dexterieur/piscines-et-jeux-de-jardin/c/piscines-et-jeux-de-jardin', 'https://www.smythstoys.com//fr/fr-fr/jeux-dexterieur/velos-et-accessoires/c/SM130312', 'https://www.smythstoys.com//fr/fr-fr/jeux-dexterieur/trottinettes-et-skateboards/c/trottinettes-et-skateboards', 'https://www.smythstoys.com//fr/fr-fr/jeux-dexterieur/equipements-de-sport/c/SM130314', 'https://www.smythstoys.com//fr/fr-fr/jeux-dexterieur/porteurs/c/porteurs', 'https://www.smythstoys.com//fr/fr-fr/jeux-video-et-gaming/nintendo-switch/c/SM130401', 'https://www.smythstoys.com//fr/fr-fr/jeux-video-et-gaming/nintendo-switch-2/c/SM130409', 'https://www.smythstoys.com//fr/fr-fr/jeux-video-et-gaming/produits-derives/c/SM130406']
    runner = ProductRunner(category_urls, min_delay=2, max_delay=5)
    await runner.run()


asyncio.run(main())