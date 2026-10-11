from typing import List, Dict, Any
from dataclasses import dataclass, field
from pydantic import ValidationError
from app.models.raw import RawListing
from app.processing.cleaner import DataCleaner
from app.database.repository import PropertyRepository
from app.logger import logger

@dataclass
class ProcessingResult:
    total_raw: int
    processed_count: int
    failed_count: int
    invalid_records: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.processed_count > 0 and self.failed_count == 0

    def __int__(self) -> int:
        return self.processed_count

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, int):
            return self.processed_count == other
        return super().__eq__(other)

class ProcessingPipeline:
    def __init__(self, repository: PropertyRepository):
        self.repository = repository
        self.invalid_records = []

    def process_raw_listings(self, raw_data_list: List[Dict]) -> ProcessingResult:
        """Processes a list of raw dictionaries into the database."""
        success_count = 0
        self.invalid_records = []
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
                
        logger.info(
            f"Processed {success_count}/{len(raw_data_list)} listings successfully. "
            f"Failures: {len(self.invalid_records)}"
        )
        return ProcessingResult(
            total_raw=len(raw_data_list),
            processed_count=success_count,
            failed_count=len(self.invalid_records),
            invalid_records=list(self.invalid_records)
        )
