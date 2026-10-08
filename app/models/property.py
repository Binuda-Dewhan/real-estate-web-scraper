from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class PropertyMasterBase(BaseModel):
    property_id: str
    source: str
    source_property_id: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    sqft: Optional[float] = None
    lot_size: Optional[float] = None
    year_built: Optional[int] = None
    official_listing_date: Optional[datetime] = None

class PropertyMaster(PropertyMasterBase):
    first_observed_at: datetime
    last_updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PropertyObservation(BaseModel):
    observation_id: Optional[int] = None
    property_id: str
    source: str
    observed_at: datetime
    price: Optional[float] = None
    price_per_sqft: Optional[float] = None
    status: Optional[str] = None
    listing_url: Optional[str] = None
    image_url: Optional[str] = None
    scrape_run_id: str

    model_config = ConfigDict(from_attributes=True)
