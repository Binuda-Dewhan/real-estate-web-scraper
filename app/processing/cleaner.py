import re
from typing import Dict, Any, Tuple
from app.models.raw import RawListing
from app.models.property import PropertyMasterBase, PropertyObservation
from datetime import datetime, timezone
from app.logger import logger

class DataCleaner:
    @staticmethod
    def clean_price(price_raw: str) -> float | None:
        if not price_raw:
            return None
        cleaned = re.sub(r'[^\d.]', '', str(price_raw))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
            
    @staticmethod
    def clean_number(val: str) -> float | None:
        if not val:
            return None
        cleaned = re.sub(r'[^\d.]', '', str(val))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    @staticmethod
    def clean_lot_size(val: str) -> float | None:
        if not val:
            return None
        val_lower = str(val).lower()
        num = DataCleaner.clean_number(val_lower)
        if num is None:
            return None
            
        if 'acre' in val_lower:
            return num * 43560.0
        return num

    @staticmethod
    def clean_status(val: str) -> str | None:
        if not val:
            return None
        val_upper = str(val).upper().replace(' ', '_')
        if 'PENDING' in val_upper:
            return 'PENDING'
        if 'SOLD' in val_upper:
            return 'SOLD'
        if 'FOR_SALE' in val_upper or 'ACTIVE' in val_upper:
            return 'FOR_SALE'
        return val_upper

    @staticmethod
    def clean_property_type(val: str) -> str | None:
        if not val:
            return None
        val_upper = str(val).upper()
        if 'SINGLEFAMILY' in val_upper or 'HOUSE' in val_upper or 'RESIDENCE' in val_upper:
            return 'SINGLE_FAMILY'
        if 'CONDO' in val_upper or 'APARTMENT' in val_upper:
            return 'CONDO'
        if 'MULTI' in val_upper:
            return 'MULTI_FAMILY'
        return val_upper

    @staticmethod
    def clean_listing(raw: RawListing) -> Tuple[PropertyMasterBase, PropertyObservation]:
        """
        Takes a RawListing model, cleans/normalizes the data, 
        and splits it into PropertyMasterBase and PropertyObservation models.
        Raises ValueError if validation fails (e.g. missing required source IDs).
        """
        if not raw.source or not raw.source_property_id:
            raise ValueError("Missing required source or source_property_id")
            
        property_id = f"{raw.source.upper()}-{raw.source_property_id}"
        
        price = DataCleaner.clean_price(raw.price_raw)
        bedrooms = DataCleaner.clean_number(raw.bedrooms_raw)
        bathrooms = DataCleaner.clean_number(raw.bathrooms_raw)
        sqft = DataCleaner.clean_number(raw.sqft_raw)
        lot_size = DataCleaner.clean_lot_size(raw.lot_size_raw)
        
        try:
            year_built = int(DataCleaner.clean_number(raw.year_built_raw)) if raw.year_built_raw else None
        except (ValueError, TypeError):
            year_built = None
            
        status = DataCleaner.clean_status(raw.status)
        prop_type = DataCleaner.clean_property_type(raw.property_type)
        
        price_per_sqft = None
        if price is not None and sqft is not None and sqft > 0:
            price_per_sqft = round(price / sqft, 2)
            
        image_url = getattr(raw, 'image_url', None)
        if not image_url and raw.model_extra:
            image_url = raw.model_extra.get('image_url')
            
        master = PropertyMasterBase(
            property_id=property_id,
            source=raw.source,
            source_property_id=raw.source_property_id,
            address=raw.address.strip() if raw.address else None,
            city=raw.city.strip() if raw.city else None,
            state=raw.state.strip() if raw.state else None,
            zip_code=raw.zip_code.strip() if raw.zip_code else None,
            property_type=prop_type,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sqft=sqft,
            lot_size=lot_size,
            year_built=year_built
        )
        
        obs = PropertyObservation(
            property_id=property_id,
            source=raw.source,
            observed_at=datetime.now(timezone.utc),
            price=price,
            price_per_sqft=price_per_sqft,
            status=status,
            listing_url=raw.listing_url,
            image_url=image_url,
            scrape_run_id=raw.scrape_run_id
        )
        
        return master, obs
