import json
import uuid
import re
import os
from typing import List, Dict, Optional
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, Page, Browser, Playwright, TimeoutError as PlaywrightTimeoutError
from app.scraper.base import BaseScraper
from app.logger import logger

class ZillowScraper(BaseScraper):
    """
    Playwright-based scraper for Zillow.
    Adheres strictly to responsible scraping practices:
    - No CAPTCHA bypass
    - Relies on publicly rendered DOM or JSON-LD
    - Respects reasonable rate limits/pacing
    """
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.scrape_run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.checkpoint_file = "data/scrape_checkpoint.json"

    def _load_checkpoint(self, location: str) -> int:
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'r') as f:
                    data = json.load(f)
                    if data.get("location") == location:
                        return data.get("current_page", 1)
            except Exception:
                pass
        return 1
        
    def _save_checkpoint(self, location: str, current_page: int):
        os.makedirs(os.path.dirname(self.checkpoint_file), exist_ok=True)
        with open(self.checkpoint_file, 'w') as f:
            json.dump({"location": location, "current_page": current_page}, f)

    def setup(self):
        logger.info(f"Setting up ZillowScraper. Run ID: {self.scrape_run_id}")
        self.playwright = sync_playwright().start()
        # Basic browser config without evasion. No stealth plugins.
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()
        # Reasonable timeout to prevent hanging
        self.page.set_default_timeout(30000)

    def teardown(self):
        logger.info("Tearing down ZillowScraper")
        if self.page:
            self.page.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _is_blocked(self) -> bool:
        """Check if we've been served a CAPTCHA or access denied page."""
        if not self.page:
            return False
        
        title = self.page.title().lower()
        url = self.page.url.lower()
        
        if "captcha" in url or "robot" in title or "access denied" in title:
            return True
            
        # Zillow specific block check (PerimeterX block page often has specific text)
        try:
            if self.page.locator("text='Press and hold'").is_visible(timeout=1000):
                return True
        except PlaywrightTimeoutError:
            pass
            
        return False

    def search(self, location: str, filters: Optional[Dict] = None, max_listings: int = 100) -> List[Dict]:
        """
        Navigates to search results and extracts raw listing data.
        Fails gracefully if blocked.
        """
        logger.info(f"Searching Zillow for '{location}'. Max listings: {max_listings}")
        raw_listings = []
        current_page = self._load_checkpoint(location)
        logger.info(f"Starting at page {current_page}")
        
        while len(raw_listings) < max_listings:
            try:
                # Basic Pagination logic
                page_suffix = f"/{current_page}_p/" if current_page > 1 else "/"
                search_url = f"https://www.zillow.com/homes/{location.replace(' ', '-')}_rb{page_suffix}"
                
                logger.info(f"Navigating to {search_url}")
                
                # Retry logic
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = self.page.goto(search_url, wait_until="domcontentloaded")
                        break # Success
                    except PlaywrightTimeoutError:
                        if attempt == max_retries - 1:
                            logger.error(f"Timeout on {search_url} after {max_retries} attempts.")
                            return raw_listings
                        logger.warning(f"Timeout on {search_url}. Retrying ({attempt + 1}/{max_retries})...")
                
                if response and response.status in [403, 429]:
                    logger.warning(f"Access denied (HTTP {response.status}). Exiting gracefully.")
                    break
                    
                if self._is_blocked():
                    logger.warning("Access denied by Zillow anti-bot (CAPTCHA). Exiting gracefully without bypass.")
                    break
                    
                property_urls = []
                # Extract embedded data to find URLs
                next_data_script = self.page.locator("script#__NEXT_DATA__")
                if next_data_script.count() > 0:
                    try:
                        json_text = next_data_script.inner_text()
                        data = json.loads(json_text)
                        logger.info("Successfully extracted Next.js embedded data.")
                        # MVP Mock Extraction of URLs from __NEXT_DATA__
                        # Note: In real Zillow, this requires deep traversal: data["props"]["pageProps"]["searchPageState"]["cat1"]["searchResults"]["listResults"]
                        list_results = data.get("props", {}).get("pageProps", {}).get("searchPageState", {}).get("cat1", {}).get("searchResults", {}).get("listResults", [])
                        for item in list_results:
                            if "detailUrl" in item:
                                property_urls.append(item["detailUrl"])
                    except json.JSONDecodeError:
                        logger.warning("Found __NEXT_DATA__ but failed to parse JSON.")
                else:
                    logger.info("No __NEXT_DATA__ found, falling back to standard DOM extraction.")
                    # Fallback to standard DOM href extraction
                    links = self.page.locator('article a[href*="/homedetails/"]').all()
                    for link in links:
                        href = link.get_attribute("href")
                        if href and href not in property_urls:
                            property_urls.append(href)
                
                # De-duplicate URLs
                property_urls = list(dict.fromkeys(property_urls))
                
                if not property_urls:
                    logger.warning("No property URLs discovered on this page.")
                
                # Iterate and isolate failures
                for url in property_urls:
                    if len(raw_listings) >= max_listings:
                        break
                    
                    if not url.startswith("http"):
                        url = f"https://www.zillow.com{url}"
                        
                    try:
                        details = self.extract_property_details(url)
                        if details:
                            raw_listings.append(details)
                    except Exception as extraction_err:
                        # Failure isolation: one bad listing doesn't break the scrape
                        logger.error(f"Failed to extract details for {url}: {extraction_err}")
                
                # Save checkpoint after successful page processing
                self._save_checkpoint(location, current_page)
                
                # Check for next page (Pagination condition)
                next_button = self.page.locator('a[title="Next page"]')
                if next_button.count() == 0 or not next_button.is_visible():
                    logger.info("No more pages found.")
                    break
                    
                current_page += 1
                
            except Exception as e:
                logger.error(f"Error during search: {e}")
                break
                
        return raw_listings

    def extract_property_details(self, property_url: str) -> Optional[Dict]:
        """Extracts detailed information from a single property page."""
        try:
            response = self.page.goto(property_url, wait_until="domcontentloaded")
            
            if response and response.status in [403, 429]:
                logger.warning(f"Access denied (HTTP {response.status}) at {property_url}")
                return None
                
            if self._is_blocked():
                logger.warning(f"CAPTCHA encountered at {property_url}. Skipping.")
                return None
                
            # ID extraction from URL
            match = re.search(r'(\d+)_zpid', property_url)
            source_property_id = match.group(1) if match else uuid.uuid4().hex[:10]
                
            raw_data = {
                "source": "Zillow",
                "source_property_id": source_property_id,
                "listing_url": property_url,
                "scrape_run_id": self.scrape_run_id,
            }
            
            # Attempt to extract JSON-LD (Schema.org data) for reliable structural data
            json_ld_script = self.page.locator('script[type="application/ld+json"]')
            if json_ld_script.count() > 0:
                try:
                    ld_data = json.loads(json_ld_script.first.inner_text())
                    if isinstance(ld_data, dict):
                        if "address" in ld_data:
                            raw_data["address"] = ld_data["address"].get("streetAddress")
                            raw_data["city"] = ld_data["address"].get("addressLocality")
                            raw_data["state"] = ld_data["address"].get("addressRegion")
                            raw_data["zip_code"] = ld_data["address"].get("postalCode")
                        
                        raw_data["property_type"] = ld_data.get("@type", "").replace("Residence", "House")
                        
                        if "numberOfRooms" in ld_data:
                            raw_data["bedrooms_raw"] = str(ld_data.get("numberOfRooms"))
                            
                        if "floorSize" in ld_data:
                            raw_data["sqft_raw"] = str(ld_data["floorSize"].get("value"))
                            
                        if "image" in ld_data:
                            raw_data["image_url"] = ld_data.get("image")
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON-LD.")
            
            # Extract DOM details (Fallback or supplementary)
            try:
                if "price_raw" not in raw_data:
                    price_node = self.page.locator('[data-testid="price"]').first
                    if price_node.is_visible(timeout=1000):
                        raw_data["price_raw"] = price_node.inner_text()
                
                # Bathrooms often not in JSON-LD standard
                bath_node = self.page.locator('button:has-text("ba")')
                if bath_node.count() > 0:
                    raw_data["bathrooms_raw"] = bath_node.first.inner_text()
                    
                # Lot size / Year Built usually in facts table
                year_node = self.page.locator('span:has-text("Built in")')
                if year_node.count() > 0:
                    raw_data["year_built_raw"] = year_node.first.inner_text()
                    
                status_node = self.page.locator('span:has-text("For sale"), span:has-text("Pending"), span:has-text("Sold")')
                if status_node.count() > 0:
                    raw_data["status"] = status_node.first.inner_text()
                    
            except PlaywrightTimeoutError:
                pass
                
            return raw_data
            
        except Exception as e:
            logger.error(f"Error extracting details for {property_url}: {e}")
            return None
