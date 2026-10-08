from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database.db import Base

class PropertyModel(Base):
    __tablename__ = "properties"

    property_id = Column(String, primary_key=True, index=True)
    source = Column(String)
    source_property_id = Column(String)
    address = Column(String)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)
    property_type = Column(String)
    bedrooms = Column(Float)
    bathrooms = Column(Float)
    sqft = Column(Float)
    lot_size = Column(Float)
    year_built = Column(Integer)
    official_listing_date = Column(DateTime)
    first_observed_at = Column(DateTime)
    last_updated_at = Column(DateTime)
    
    observations = relationship("ObservationModel", back_populates="property", cascade="all, delete-orphan")

class ObservationModel(Base):
    __tablename__ = "observations"

    observation_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    property_id = Column(String, ForeignKey("properties.property_id"), index=True)
    source = Column(String)
    observed_at = Column(DateTime)
    price = Column(Float)
    price_per_sqft = Column(Float)
    status = Column(String)
    listing_url = Column(String)
    image_url = Column(String)
    scrape_run_id = Column(String)
    
    property = relationship("PropertyModel", back_populates="observations")
