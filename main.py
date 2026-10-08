import argparse
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.schema import Base
from app.database.repository import PropertyRepository
from app.scraper.zillow import ZillowScraper
from app.processing.pipeline import ProcessingPipeline
from app.analysis.engine import AnalysisEngine
from app.analysis.exporter import DataExporter
from app.logger import logger
from app.config import settings

def setup_db(db_path: str):
    """Initializes the database if it doesn't exist."""
    # Ensure directory exists for sqlite files
    if db_path.startswith("sqlite:///"):
        path = db_path.replace('sqlite:///', '')
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            
    engine = create_engine(db_path)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

def run_scraper(location: str, max_listings: int, headless: bool = True) -> list:
    logger.info(f"Starting scraper for {location} (Max: {max_listings})")
    scraper = ZillowScraper(headless=headless)
    scraper.setup()
    try:
        raw_data = scraper.search(location=location, max_listings=max_listings)
    finally:
        scraper.teardown()
    return raw_data

def run_pipeline(raw_data: list, session):
    logger.info("Starting processing pipeline")
    repo = PropertyRepository(session)
    pipeline = ProcessingPipeline(repo)
    success = pipeline.process_raw_listings(raw_data)
    logger.info(f"Pipeline finished. Processed {success} listings.")

def run_exports(db_path: str):
    logger.info("Running market analysis and generating exports")
    # Clean db path for sqlalchemy
    clean_path = db_path.replace('sqlite:///', '')
    
    engine = AnalysisEngine(clean_path)
    engine.load_data()
    
    exporter = DataExporter(engine, output_dir="data/exports")
    exporter.export_csv()
    exporter.export_json()
    exporter.export_excel("market_report.xlsx")
    
    logger.info("Exports generated successfully in data/exports/")

def main():
    parser = argparse.ArgumentParser(description="Real Estate Market Intelligence Pipeline")
    parser.add_argument("--scrape", action="store_true", help="Run the Zillow scraper")
    parser.add_argument("--location", type=str, default="Austin, TX", help="Location to scrape")
    parser.add_argument("--max-listings", type=int, default=10, help="Maximum number of listings to scrape")
    parser.add_argument("--visible", action="store_true", help="Run scraper in non-headless mode (visible browser)")
    parser.add_argument("--analyze", action="store_true", help="Run analysis and generate exports")
    
    args = parser.parse_args()
    
    if not args.scrape and not args.analyze:
        parser.print_help()
        return

    # Initialize DB
    session = setup_db(settings.db_path)
    
    try:
        if args.scrape:
            raw_data = run_scraper(
                location=args.location, 
                max_listings=args.max_listings, 
                headless=not args.visible
            )
            if raw_data:
                run_pipeline(raw_data, session)
            else:
                logger.warning("No data returned from scraper.")
                
        if args.analyze:
            run_exports(settings.db_path)
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    main()
