import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database.schema import Base, PropertyModel, ObservationModel
from app.database.repository import PropertyRepository
from app.processing.pipeline import ProcessingPipeline
import time

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    from sqlalchemy.engine import Engine
    from sqlalchemy import event
    
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def test_pipeline_deduplication(db_session):
    repo = PropertyRepository(db_session)
    pipeline = ProcessingPipeline(repo)
    
    raw_data_1 = {
        "scrape_run_id": "run_1",
        "source": "Zillow",
        "listing_url": "http://zillow.com/1",
        "source_property_id": "123",
        "price_raw": "$525,000",
        "status": "For sale"
    }
    pipeline.process_raw_listings([raw_data_1])
    assert db_session.query(PropertyModel).count() == 1
    assert db_session.query(ObservationModel).count() == 1
    
    time.sleep(0.01)
    
    raw_data_2 = {
        "scrape_run_id": "run_2",
        "source": "Zillow",
        "listing_url": "http://zillow.com/1",
        "source_property_id": "123",
        "price_raw": "$525,000",
        "status": "For sale"
    }
    pipeline.process_raw_listings([raw_data_2])
    assert db_session.query(PropertyModel).count() == 1
    assert db_session.query(ObservationModel).count() == 1
    
    time.sleep(0.01)
    
    raw_data_3 = {
        "scrape_run_id": "run_3",
        "source": "Zillow",
        "listing_url": "http://zillow.com/1",
        "source_property_id": "123",
        "price_raw": "$515,000",
        "status": "For sale"
    }
    pipeline.process_raw_listings([raw_data_3])
    assert db_session.query(PropertyModel).count() == 1
    assert db_session.query(ObservationModel).count() == 2

def test_historical_summary(db_session):
    repo = PropertyRepository(db_session)
    pipeline = ProcessingPipeline(repo)
    
    prices = ["$525,000", "$525,000", "$515,000", "$499,000"]
    for i, p in enumerate(prices):
        pipeline.process_raw_listings([{
            "scrape_run_id": f"run_{i}",
            "source": "Zillow",
            "listing_url": "http://zillow.com/1",
            "source_property_id": "999",
            "price_raw": p,
            "status": "For sale"
        }])
        time.sleep(0.05)
        
    summary = repo.get_historical_summary("ZILLOW-999")
    
    assert summary["current_price"] == 499000.0
    assert summary["previous_price"] == 515000.0
    assert summary["total_change"] == -26000.0
    assert summary["percentage_change"] == -4.95
    assert summary["lowest_price"] == 499000.0
    assert summary["highest_price"] == 525000.0
    assert summary["price_changes"] == 2
