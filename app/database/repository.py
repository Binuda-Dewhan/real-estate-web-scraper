from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone
from app.database.schema import PropertyModel, ObservationModel

class PropertyRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_property(self, property_data: dict) -> PropertyModel:
        """Inserts a new property or updates an existing one."""
        prop_id = property_data.get("property_id")
        existing_prop = self.db.query(PropertyModel).filter(PropertyModel.property_id == prop_id).first()
        
        now = datetime.now(timezone.utc)
        
        if existing_prop:
            # Update only changing fields, ignore None unless explicitly unsetting
            for key, value in property_data.items():
                if hasattr(existing_prop, key) and value is not None:
                    setattr(existing_prop, key, value)
            existing_prop.last_updated_at = now
            db_obj = existing_prop
        else:
            # Insert new
            property_data['first_observed_at'] = now
            property_data['last_updated_at'] = now
            db_obj = PropertyModel(**property_data)
            self.db.add(db_obj)
            
        self.db.commit()
        self.db.refresh(db_obj)
        return db_obj

    def add_observation(self, observation_data: dict) -> ObservationModel:
        """Adds a new observation if price or status changed."""
        prop_id = observation_data.get("property_id")
        latest_obs = (
            self.db.query(ObservationModel)
            .filter(ObservationModel.property_id == prop_id)
            .order_by(ObservationModel.observed_at.desc())
            .first()
        )
        
        if latest_obs:
            same_price = latest_obs.price == observation_data.get("price")
            same_status = latest_obs.status == observation_data.get("status")
            if same_price and same_status:
                # Do not insert duplicate meaningful observation
                return latest_obs
                
        obs = ObservationModel(**observation_data)
        self.db.add(obs)
        self.db.commit()
        self.db.refresh(obs)
        return obs

    def get_historical_summary(self, property_id: str) -> dict:
        observations = (
            self.db.query(ObservationModel)
            .filter(ObservationModel.property_id == property_id)
            .order_by(ObservationModel.observed_at.asc())
            .all()
        )
        
        if not observations:
            return {}
            
        prices = [obs.price for obs in observations if obs.price is not None]
        
        current_price = prices[-1] if prices else None
        previous_price = prices[-2] if len(prices) > 1 else None
        
        total_change = None
        percentage_change = None
        if prices and len(prices) > 0:
            first_price = prices[0]
            if first_price and current_price:
                total_change = current_price - first_price
                percentage_change = round((total_change / first_price) * 100, 2)
        
        return {
            "current_price": current_price,
            "previous_price": previous_price,
            "total_change": total_change,
            "percentage_change": percentage_change,
            "lowest_price": min(prices) if prices else None,
            "highest_price": max(prices) if prices else None,
            "price_changes": max(0, len(prices) - 1),
            "first_observed": observations[0].observed_at,
            "latest_observed": observations[-1].observed_at,
            "current_status": observations[-1].status
        }
