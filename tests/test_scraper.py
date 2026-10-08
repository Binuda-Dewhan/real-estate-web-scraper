import pytest
from app.scraper.zillow import ZillowScraper
from unittest.mock import MagicMock, patch
import os

def test_scraper_initialization():
    scraper = ZillowScraper(headless=True)
    assert scraper.headless is True
    assert scraper.scrape_run_id is not None
    assert scraper.scrape_run_id.startswith("run_")

@patch('app.scraper.zillow.sync_playwright')
def test_scraper_search_mocked(mock_sync_playwright):
    # Setup mock playwright
    mock_playwright = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()
    
    mock_sync_playwright.return_value.start.return_value = mock_playwright
    mock_playwright.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page
    
    # Mock search page response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.title.return_value = "Real Estate & Homes For Sale"
    mock_page.url = "https://www.zillow.com/homes/Atlanta,-GA_rb/"
    
    # Mock Next Data script finding
    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_locator.is_visible.return_value = False
    # Returns 2 URLs
    mock_locator.inner_text.return_value = '{"props": {"pageProps": {"searchPageState": {"cat1": {"searchResults": {"listResults": [{"detailUrl": "/homedetails/1_zpid/"}, {"detailUrl": "/homedetails/2_zpid/"}]}}}}}}'
    mock_page.locator.return_value = mock_locator

    scraper = ZillowScraper(headless=True)
    scraper.setup()
    
    # Patch extract_property_details to isolate failure and avoid complex nested mock
    with patch.object(scraper, 'extract_property_details') as mock_extract:
        mock_extract.side_effect = [{"property_id": "1"}, {"property_id": "2"}]
        
        results = scraper.search("Atlanta, GA", max_listings=2)
        
        assert mock_page.goto.called
        assert len(results) == 2
        assert mock_extract.call_count == 2
        
        # Test Checkpointing
        assert os.path.exists(scraper.checkpoint_file)
    
    scraper.teardown()
    
    if os.path.exists(scraper.checkpoint_file):
        os.remove(scraper.checkpoint_file)

@patch('app.scraper.zillow.sync_playwright')
def test_extract_property_details_json_ld(mock_sync_playwright):
    scraper = ZillowScraper(headless=True)
    scraper.page = MagicMock()
    scraper.page.title.return_value = "Property Details"
    scraper.page.url = "https://www.zillow.com/homedetails/12345_zpid/"
    
    # Mock JSON-LD
    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_locator.is_visible.return_value = False
    mock_locator.first.inner_text.return_value = '{"@type": "SingleFamilyResidence", "address": {"streetAddress": "123 Main St", "addressLocality": "Atlanta", "addressRegion": "GA", "postalCode": "30303"}, "numberOfRooms": 4, "floorSize": {"value": 2000}, "image": "http://img.url"}'
    
    # Need to handle the fallback locators that return 0 count
    def side_effect(selector):
        if 'application/ld+json' in selector:
            return mock_locator
        empty_locator = MagicMock()
        empty_locator.count.return_value = 0
        empty_locator.is_visible.return_value = False
        return empty_locator
        
    scraper.page.locator.side_effect = side_effect
    
    details = scraper.extract_property_details("https://www.zillow.com/homedetails/12345_zpid/")
    
    assert details["address"] == "123 Main St"
    assert details["city"] == "Atlanta"
    assert details["state"] == "GA"
    assert details["zip_code"] == "30303"
    assert details["bedrooms_raw"] == "4"
    assert details["sqft_raw"] == "2000"
    assert details["image_url"] == "http://img.url"

@patch('app.scraper.zillow.sync_playwright')
def test_scraper_captcha_handling(mock_sync_playwright):
    mock_playwright = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()
    
    mock_sync_playwright.return_value.start.return_value = mock_playwright
    mock_playwright.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page
    
    # Simulate a CAPTCHA response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.title.return_value = "Robot or human?"
    mock_page.url = "https://www.zillow.com/captcha"
    
    scraper = ZillowScraper(headless=True)
    scraper.setup()
    
    results = scraper.search("Atlanta, GA", max_listings=10)
    
    # Should gracefully return empty list without throwing errors or bypassing
    assert results == []
    
    scraper.teardown()
