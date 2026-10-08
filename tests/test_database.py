import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database.db import Base
from app.database.schema import PropertyModel, ObservationModel
from app.database.repository import PropertyRepository
from app.models.property import PropertyMasterBase, PropertyObservation

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_pydantic_validation():
    # Valid data
    valid_data = {
        "property_id": "ZIL-1",
        "source": "Zillow",
        "source_property_id": "1",
        "bedrooms": 3
    }
    prop = PropertyMasterBase(**valid_data)
    assert prop.bedrooms == 3.0

def test_upsert_property(db_session):
    repo = PropertyRepository(db_session)
    prop_data = {
        "property_id": "ZIL-12345",
        "source": "Zillow",
        "source_property_id": "12345",
        "address": "123 Main St",
        "city": "Atlanta",
        "state": "GA",
        "zip_code": "30303",
        "bedrooms": 3.0,
        "bathrooms": 2.5
    }
    
    # Test insert
    prop = repo.upsert_property(prop_data)
    assert prop.property_id == "ZIL-12345"
    assert prop.address == "123 Main St"
    assert prop.first_observed_at is not None
    
    # Test update
    update_data = {
        "property_id": "ZIL-12345",
        "bedrooms": 4.0 # Renovation!
    }
    updated_prop = repo.upsert_property(update_data)
    assert updated_prop.bedrooms == 4.0
    assert updated_prop.address == "123 Main St" # Unchanged
    assert updated_prop.last_updated_at >= updated_prop.first_observed_at

def test_add_observation(db_session):
    repo = PropertyRepository(db_session)
    # Create parent property first to satisfy FK constraint
    prop_data = {
        "property_id": "ZIL-12345",
        "source": "Zillow",
        "source_property_id": "12345"
    }
    repo.upsert_property(prop_data)
    
    obs_data = {
        "property_id": "ZIL-12345",
        "source": "Zillow",
        "observed_at": datetime.now(timezone.utc),
        "price": 500000.0,
        "status": "For Sale",
        "scrape_run_id": "run-001"
    }
    
    # Validation
    pydantic_obs = PropertyObservation(**obs_data)
    assert pydantic_obs.price == 500000.0
    
    # Insert
    obs = repo.add_observation(obs_data)
    assert obs.observation_id is not None
    assert obs.price == 500000.0
