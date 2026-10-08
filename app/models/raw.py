from pydantic import BaseModel, ConfigDict
from typing import Optional, Any

class RawListing(BaseModel):
    """Raw extraction model straight from the source."""
    scrape_run_id: str
    source: str
    listing_url: str
    
    # Everything else is Optional since it's raw and dirty
    source_property_id: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    price_raw: Optional[str] = None
    bedrooms_raw: Optional[str] = None
    bathrooms_raw: Optional[str] = None
    sqft_raw: Optional[str] = None
    lot_size_raw: Optional[str] = None
    year_built_raw: Optional[str] = None
    property_type: Optional[str] = None
    status: Optional[str] = None
    image_url: Optional[str] = None
    
    # To catch additional dynamic fields from JSON
    extra_data: Optional[dict[str, Any]] = None
    
    model_config = ConfigDict(extra='allow')
