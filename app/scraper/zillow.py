import json
import uuid
import re
import os
import time
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
    - Relies on publicly rendered DOM or JSON-LD embedded in __NEXT_DATA__
    - Extracts all data from the search results page (avoids 403s on detail pages)
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
            
        # Zillow specific block check
        try:
            if self.page.locator("text='Press and hold'").is_visible(timeout=1000):
                return True
        except PlaywrightTimeoutError:
            pass
            
        return False

    def _extract_from_list_result(self, item: dict) -> Optional[Dict]:
        """
        Extracts a raw listing dict from a single Zillow search list result item.
        All data comes from the __NEXT_DATA__ JSON embedded in the search page.
        This avoids navigating to individual property pages which trigger 403 blocks.
        """
        try:
            # Extract zpid (Zillow's property ID)
            zpid = item.get("zpid")
            if not zpid:
                return None

            source_property_id = str(zpid)
            detail_url = item.get("detailUrl", "")
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.zillow.com{detail_url}"

            # Address fields
            address = item.get("address", "")
            
            # Zillow often nests address details
            address_parts = {}
            if "addressStreet" in item:
                address_parts["address"] = item.get("addressStreet")
                address_parts["city"] = item.get("addressCity")
                address_parts["state"] = item.get("addressState")
                address_parts["zip_code"] = item.get("addressZipcode")
            elif address:
                # Try to parse from combined address string
                address_parts["address"] = address

            # Price — comes as a formatted string e.g. "$850,000" or raw int
            price_raw = None
            if "price" in item:
                price_val = item["price"]
                if isinstance(price_val, (int, float)):
                    price_raw = str(price_val)
                elif isinstance(price_val, str):
                    price_raw = price_val
            elif "unformattedPrice" in item:
                price_raw = str(item["unformattedPrice"])

            # Bedrooms / bathrooms
            bedrooms_raw = str(item["beds"]) if item.get("beds") is not None else None
            bathrooms_raw = str(item["baths"]) if item.get("baths") is not None else None

            # Square footage
            sqft_raw = None
            if item.get("area") is not None:
                sqft_raw = str(item["area"])
            elif item.get("livingArea") is not None:
                sqft_raw = str(item["livingArea"])

            # Status
            status_raw = item.get("statusType") or item.get("homeStatus") or item.get("statusText")

            # Property type
            prop_type_raw = item.get("homeType") or item.get("propertyType")

            # Image — may be list or string
            image = item.get("imgSrc") or item.get("image")
            if isinstance(image, list):
                image = image[0] if image else None

            raw = {
                "source": "Zillow",
                "source_property_id": source_property_id,
                "listing_url": detail_url,
                "scrape_run_id": self.scrape_run_id,
                "price_raw": price_raw,
                "bedrooms_raw": bedrooms_raw,
                "bathrooms_raw": bathrooms_raw,
                "sqft_raw": sqft_raw,
                "status": status_raw,
                "property_type": prop_type_raw,
                "image_url": image,
            }
            raw.update(address_parts)
            return raw

        except Exception as e:
            logger.error(f"Error parsing list result item: {e}")
            return None

    def search(self, location: str, filters: Optional[Dict] = None, max_listings: int = 100) -> List[Dict]:
        """
        Navigates to search results and extracts raw listing data directly from
        the embedded __NEXT_DATA__ JSON on the search page.
        Fails gracefully if blocked.
        """
        logger.info(f"Searching Zillow for '{location}'. Max listings: {max_listings}")
        raw_listings = []
        current_page = self._load_checkpoint(location)
        logger.info(f"Starting at page {current_page}")
        
        while len(raw_listings) < max_listings:
            try:
                page_suffix = f"/{current_page}_p/" if current_page > 1 else "/"
                search_url = f"https://www.zillow.com/homes/{location.replace(' ', '-')}_rb{page_suffix}"
                
                logger.info(f"Navigating to {search_url}")
                
                # Retry logic
                max_retries = 3
                response = None
                for attempt in range(max_retries):
                    try:
                        response = self.page.goto(search_url, wait_until="domcontentloaded")
                        break
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

                # ----------------------------------------------------------------
                # PRIMARY: Extract all listing data from __NEXT_DATA__ on the
                # search results page. This avoids visiting individual property
                # pages (which trigger 403 blocks).
                # ----------------------------------------------------------------
                page_found_results = False
                next_data_script = self.page.locator("script#__NEXT_DATA__")
                if next_data_script.count() > 0:
                    try:
                        json_text = next_data_script.inner_text()
                        data = json.loads(json_text)
                        logger.info("Successfully extracted Next.js embedded data.")

                        # Traverse into search results
                        search_page_state = (
                            data.get("props", {})
                                .get("pageProps", {})
                                .get("searchPageState", {})
                        )

                        # Try primary path: cat1 → searchResults → listResults
                        list_results = (
                            search_page_state
                            .get("cat1", {})
                            .get("searchResults", {})
                            .get("listResults", [])
                        )

                        # Fallback path: mapResults
                        if not list_results:
                            list_results = (
                                search_page_state
                                .get("cat1", {})
                                .get("searchResults", {})
                                .get("mapResults", [])
                            )

                        if list_results:
                            logger.info(f"Found {len(list_results)} listings in embedded data.")
                            page_found_results = True
                            for item in list_results:
                                if len(raw_listings) >= max_listings:
                                    break
                                extracted = self._extract_from_list_result(item)
                                if extracted:
                                    raw_listings.append(extracted)
                                    logger.info(f"Extracted: {extracted.get('listing_url', 'unknown URL')}")
                        else:
                            logger.warning("Found __NEXT_DATA__ but no listResults or mapResults found.")
                    except json.JSONDecodeError:
                        logger.warning("Found __NEXT_DATA__ but failed to parse JSON.")
                else:
                    logger.info("No __NEXT_DATA__ found, falling back to DOM link extraction.")
                    # Fallback: collect hrefs from DOM (no detail page visits — just URLs logged)
                    links = self.page.locator('article a[href*="/homedetails/"]').all()
                    for link in links:
                        href = link.get_attribute("href")
                        if href:
                            logger.info(f"DOM fallback found listing href: {href}")

                # Save checkpoint after successful page processing
                self._save_checkpoint(location, current_page)

                # Pacing — be a reasonable client
                time.sleep(1)

                # Check for next page
                next_button = self.page.locator('a[title="Next page"]')
                if next_button.count() == 0 or not next_button.is_visible():
                    logger.info("No more pages found.")
                    break
                    
                current_page += 1
                
            except Exception as e:
                logger.error(f"Error during search: {e}")
                break
                
        logger.info(f"Scraping complete. Total listings collected: {len(raw_listings)}")
        return raw_listings

    def extract_property_details(self, property_url: str) -> Optional[Dict]:
        """
        Extracts detailed information from a single property page.
        NOTE: Zillow frequently returns HTTP 403 on direct detail page visits from
        automated browsers. This method is kept for completeness but the primary
        extraction path uses search page __NEXT_DATA__ instead.
        """
        try:
            response = self.page.goto(property_url, wait_until="domcontentloaded")
            
            if response and response.status in [403, 429]:
                logger.warning(f"Access denied (HTTP {response.status}) at {property_url}")
                return None
                
            if self._is_blocked():
                logger.warning(f"CAPTCHA encountered at {property_url}. Skipping.")
                return None
                
            match = re.search(r'(\d+)_zpid', property_url)
            source_property_id = match.group(1) if match else uuid.uuid4().hex[:10]
                
            raw_data = {
                "source": "Zillow",
                "source_property_id": source_property_id,
                "listing_url": property_url,
                "scrape_run_id": self.scrape_run_id,
            }
            
            # JSON-LD extraction
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
                        
                        raw_data["property_type"] = ld_data.get("@type", "")
                        
                        if "numberOfRooms" in ld_data:
                            raw_data["bedrooms_raw"] = str(ld_data.get("numberOfRooms"))
                            
                        if "floorSize" in ld_data:
                            raw_data["sqft_raw"] = str(ld_data["floorSize"].get("value"))
                            
                        # image may be a list or string — always normalize to string
                        image = ld_data.get("image")
                        if isinstance(image, list):
                            image = image[0] if image else None
                        raw_data["image_url"] = image

                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON-LD.")
            
            # DOM fallback
            try:
                if "price_raw" not in raw_data:
                    price_node = self.page.locator('[data-testid="price"]').first
                    if price_node.is_visible(timeout=1000):
                        raw_data["price_raw"] = price_node.inner_text()
                
                bath_node = self.page.locator('button:has-text("ba")')
                if bath_node.count() > 0:
                    raw_data["bathrooms_raw"] = bath_node.first.inner_text()
                    
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
