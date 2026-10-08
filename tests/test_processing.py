import pytest
from app.models.raw import RawListing
from app.processing.cleaner import DataCleaner

def test_clean_price():
    assert DataCleaner.clean_price("$525,000") == 525000.0
    assert DataCleaner.clean_price(None) is None
    assert DataCleaner.clean_price("Call for price") is None

def test_clean_lot_size():
    assert DataCleaner.clean_lot_size("0.5 Acres") == 21780.0
    assert DataCleaner.clean_lot_size("5,000 sqft") == 5000.0
    assert DataCleaner.clean_lot_size(None) is None

def test_clean_status():
    assert DataCleaner.clean_status("For sale") == "FOR_SALE"
    assert DataCleaner.clean_status("Pending") == "PENDING"
    assert DataCleaner.clean_status("Sold") == "SOLD"

def test_clean_property_type():
    assert DataCleaner.clean_property_type("SingleFamilyResidence") == "SINGLE_FAMILY"
    assert DataCleaner.clean_property_type("Condo") == "CONDO"
    
def test_clean_listing_valid():
    raw = RawListing(
        scrape_run_id="run_1",
        source="Zillow",
        listing_url="http://zillow.com/1",
        source_property_id="12345",
        price_raw="$525,000",
        bedrooms_raw="4 bd",
        bathrooms_raw="3.5 ba",
        sqft_raw="2,000 sqft",
        lot_size_raw="0.5 Acres",
        year_built_raw="Built in 2005",
        status="For sale",
        property_type="SingleFamilyResidence",
        address=" 123 Main St "
    )
    master, obs = DataCleaner.clean_listing(raw)
    
    assert master.property_id == "ZILLOW-12345"
    assert master.bedrooms == 4.0
    assert master.bathrooms == 3.5
    assert master.sqft == 2000.0
    assert master.lot_size == 21780.0
    assert master.year_built == 2005
    assert master.address == "123 Main St"
    
    assert obs.price == 525000.0
    assert obs.price_per_sqft == 262.5
    assert obs.status == "FOR_SALE"

def test_clean_listing_missing_values():
    raw = RawListing(
        scrape_run_id="run_1",
        source="Zillow",
        listing_url="http://zillow.com/1",
        source_property_id="12345"
    )
    master, obs = DataCleaner.clean_listing(raw)
    
    assert master.bedrooms is None
    assert obs.price is None
    assert obs.price_per_sqft is None

def test_clean_listing_invalid():
    raw = RawListing(
        scrape_run_id="run_1",
        source="Zillow",
        listing_url="http://zillow.com/1"
    )
    # raw listing source_property_id defaults to None
    with pytest.raises(ValueError):
        DataCleaner.clean_listing(raw)
