import os
import pytest
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import create_engine
from app.database.schema import Base, PropertyModel, ObservationModel
from app.database.repository import PropertyRepository
from app.analysis.engine import AnalysisEngine
from app.analysis.exporter import DataExporter
import tempfile

@pytest.fixture
def test_db_path():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, 'test.db')
    
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    repo = PropertyRepository(session)
    now = datetime.now(timezone.utc)
    
    # Property 1 (Complete)
    repo.upsert_property({
        "property_id": "ZILLOW-1",
        "source": "ZILLOW",
        "source_property_id": "1",
        "zip_code": "90210",
        "property_type": "SINGLE_FAMILY",
        "bedrooms": 4.0,
        "sqft": 2000.0,
        "first_observed_at": now
    })
    repo.add_observation({
        "property_id": "ZILLOW-1",
        "source": "ZILLOW",
        "observed_at": now,
        "price": 500000.0,
        "status": "FOR_SALE",
        "scrape_run_id": "run1"
    })
    
    # Property 2 (Missing sqft, different ZIP)
    repo.upsert_property({
        "property_id": "ZILLOW-2",
        "source": "ZILLOW",
        "source_property_id": "2",
        "zip_code": "90211",
        "property_type": "CONDO",
        "bedrooms": 2.0,
        "first_observed_at": now
    })
    repo.add_observation({
        "property_id": "ZILLOW-2",
        "source": "ZILLOW",
        "observed_at": now,
        "price": 300000.0,
        "status": "FOR_SALE",
        "scrape_run_id": "run1"
    })
    
    # Property 3 (Historical changes)
    repo.upsert_property({
        "property_id": "ZILLOW-3",
        "source": "ZILLOW",
        "source_property_id": "3",
        "zip_code": "90210",
        "property_type": "SINGLE_FAMILY",
        "sqft": 1000.0,
        "first_observed_at": now
    })
    repo.add_observation({
        "property_id": "ZILLOW-3",
        "source": "ZILLOW",
        "observed_at": pd.Timestamp('2023-01-01', tz='UTC').to_pydatetime(),
        "price": 400000.0,
        "status": "FOR_SALE",
        "scrape_run_id": "run_old"
    })
    repo.add_observation({
        "property_id": "ZILLOW-3",
        "source": "ZILLOW",
        "observed_at": pd.Timestamp('2023-01-02', tz='UTC').to_pydatetime(),
        "price": 390000.0,
        "status": "PENDING",
        "scrape_run_id": "run_new"
    })
    
    session.close()
    engine.dispose()
    
    yield db_path
    temp_dir.cleanup()

def test_engine_load_data(test_db_path):
    engine = AnalysisEngine(test_db_path)
    engine.load_data()
    assert not engine.df_properties.empty
    assert len(engine.df_properties) == 3
    assert len(engine.df_observations) == 4

def test_market_summary(test_db_path):
    engine = AnalysisEngine(test_db_path)
    engine.load_data()
    
    summary = engine.calculate_market_summary()
    assert summary['total_properties'] == 3
    
    assert summary['average_price'] == pytest.approx(396666.66, 0.1)
    assert summary['max_price'] == 500000.0
    assert summary['min_price'] == 300000.0
    
    assert summary['average_price_per_sqft'] == pytest.approx(320.0, 0.1)
    
    assert summary['count_by_type']['SINGLE_FAMILY'] == 2

def test_location_analysis(test_db_path):
    engine = AnalysisEngine(test_db_path)
    engine.load_data()
    
    loc = engine.analyze_by_location()
    
    assert len(loc) == 2
    zip_90210 = loc[loc['zip_code'] == '90210'].iloc[0]
    assert zip_90210['property_count'] == 2
    assert zip_90210['average_price'] == 445000.0

def test_price_history(test_db_path):
    engine = AnalysisEngine(test_db_path)
    engine.load_data()
    
    history = engine.calculate_price_history()
    
    prop_3 = history[history['property_id'] == 'ZILLOW-3'].iloc[0]
    
    assert prop_3['current_price'] == 390000.0
    assert prop_3['previous_price'] == 400000.0
    assert prop_3['total_change'] == -10000.0
    assert prop_3['percentage_change'] == -2.5
    assert prop_3['highest_price'] == 400000.0
    assert prop_3['price_changes'] == 1

def test_status_changes(test_db_path):
    engine = AnalysisEngine(test_db_path)
    engine.load_data()
    
    status_df = engine.analyze_status_changes()
    prop_3 = status_df[status_df['property_id'] == 'ZILLOW-3'].iloc[0]
    
    assert prop_3['current_status'] == 'PENDING'
    assert prop_3['status_changes'] == 1

def test_empty_database_handling():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, 'empty.db')
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        
        analysis = AnalysisEngine(db_path)
        analysis.load_data()
        
        assert analysis.calculate_market_summary() == {}
        assert analysis.analyze_by_location().empty
        assert analysis.calculate_price_history().empty
        assert analysis.analyze_status_changes().empty

def test_exporter(test_db_path):
    engine = AnalysisEngine(test_db_path)
    engine.load_data()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        exporter = DataExporter(engine, output_dir=temp_dir)
        exporter.export_csv()
        exporter.export_json()
        exporter.export_excel()
        
        assert os.path.exists(os.path.join(temp_dir, 'properties.csv'))
        assert os.path.exists(os.path.join(temp_dir, 'analysis_results.json'))
        assert os.path.exists(os.path.join(temp_dir, 'market_report.xlsx'))
