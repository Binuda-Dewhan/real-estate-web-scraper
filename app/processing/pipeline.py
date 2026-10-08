from typing import List, Dict
from pydantic import ValidationError
from app.models.raw import RawListing
from app.processing.cleaner import DataCleaner
from app.database.repository import PropertyRepository
from app.logger import logger

class ProcessingPipeline:
    def __init__(self, repository: PropertyRepository):
        self.repository = repository
        self.invalid_records = []

    def process_raw_listings(self, raw_data_list: List[Dict]):
        """Processes a list of raw dictionaries into the database."""
        success_count = 0
        for data in raw_data_list:
            try:
                # 1. Pydantic validation for Raw input
                raw_listing = RawListing(**data)
                
                # 2. Cleaning and normalization
                master_model, obs_model = DataCleaner.clean_listing(raw_listing)
                
                # 3. Database integration
                self.repository.upsert_property(master_model.model_dump())
                self.repository.add_observation(obs_model.model_dump())
                
                success_count += 1
            except ValidationError as ve:
                logger.error(f"Validation error on record: {ve}")
                self.invalid_records.append({"data": data, "error": str(ve)})
            except ValueError as ve:
                logger.error(f"Cleaning error on record: {ve}")
                self.invalid_records.append({"data": data, "error": str(ve)})
            except Exception as e:
                logger.error(f"Unexpected error processing record: {e}")
                self.invalid_records.append({"data": data, "error": str(e)})
                
        logger.info(f"Processed {success_count}/{len(raw_data_list)} listings successfully.")
        return success_count
