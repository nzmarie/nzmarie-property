import asyncio
import random
import logging
from playwright.async_api import async_playwright
from utils.database import db

logger = logging.getLogger(__name__)

class BaseScraper:
    def __init__(self, mode, force_run=False, simulate=False, region="auckland"):
        self.mode = mode
        self.force_run = force_run
        self.simulate = simulate
        self.region = region
        self.browser = None
        self.context = None

    async def init_browser(self, headless=True):
        self.playwright_manager = await async_playwright().start()
        self.browser = await self.playwright_manager.chromium.launch(headless=headless)
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        # Block fonts and videos to speed up scraping, but allow images and CSS
        await self.context.route("**/*.{woff,woff2,ttf,mp4,webm}", 
                                 lambda route: route.abort())
        
        logger.info(f"Browser initialized in {self.mode} mode for region: {self.region} (Resource blocking enabled)")


    async def close_browser(self):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright_manager'):
            await self.playwright_manager.stop()

    async def check_lock(self, task_key):
        if self.simulate:
            logger.info(f"[SIMULATION] Skipping lock check for {task_key}")
            return True

        if self.force_run:
            logger.warning(f"Force run enabled for {task_key}. Skipping lock check.")
            return True

        try:
            sql = "SELECT status FROM scraping_progress WHERE description = %s"
            res = db.query(sql, (task_key,))
            if res and res[0]['status'] == 'ongoing':
                logger.error(f"Task {task_key} is already running. Use --force to override.")
                return False
        except Exception as e:
            logger.warning(f"Database connection failed during lock check for {task_key}: {e}")
        return True

    async def set_status(self, task_key, status):
        sql = """
            UPSERT INTO scraping_progress (description, status, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
        """
        params = (task_key, status)

        if self.simulate:
            logger.info(f"[SIMULATION] Would update progress for {task_key}: {status}")
            return

        try:
            db.execute(sql, params)
        except Exception as e:
            logger.error(f"Failed to update progress status for {task_key}: {e}")

    async def safe_goto(self, page, url, wait_until="domcontentloaded", timeout=90000, retries=3):
        """Navigate to a URL with retries and random delays."""
        for attempt in range(retries):
            try:
                await asyncio.sleep(random.uniform(1.5, 3))
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                return True
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt == retries - 1:
                    return False
                await asyncio.sleep(5)
        return False
