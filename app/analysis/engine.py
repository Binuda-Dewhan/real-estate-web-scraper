import pandas as pd
from typing import Dict, Any, List
from sqlalchemy import create_engine
import numpy as np
import warnings

# Suppress pandas warning about apply returning Series
warnings.filterwarnings("ignore", message=".*returning a Series from apply.*")

class AnalysisEngine:
    def __init__(self, db_path: str):
        self.db_url = f"sqlite:///{db_path}"
        self.engine = create_engine(self.db_url)
        self.df_properties = pd.DataFrame()
        self.df_observations = pd.DataFrame()
        
    def load_data(self):
        """Loads data from SQLite into Pandas DataFrames safely."""
        try:
            with self.engine.connect() as conn:
                self.df_properties = pd.read_sql_table('properties', conn)
                self.df_observations = pd.read_sql_table('observations', conn)
            
            # Free file lock on Windows
            self.engine.dispose()
            
            # Ensure date columns are datetime objects
            if not self.df_observations.empty:
                self.df_observations['observed_at'] = pd.to_datetime(self.df_observations['observed_at'])
            if not self.df_properties.empty:
                self.df_properties['first_observed_at'] = pd.to_datetime(self.df_properties['first_observed_at'])
                self.df_properties['last_updated_at'] = pd.to_datetime(self.df_properties['last_updated_at'])
                if 'official_listing_date' in self.df_properties.columns:
                    self.df_properties['official_listing_date'] = pd.to_datetime(self.df_properties['official_listing_date'])
        except Exception as e:
            # Handle empty tables gracefully
            print(f"Error loading data: {e}")
            self.df_properties = pd.DataFrame()
            self.df_observations = pd.DataFrame()

    def calculate_market_summary(self) -> Dict[str, Any]:
        """Calculates high-level market statistics."""
        if self.df_properties.empty or self.df_observations.empty:
            return {}
            
        latest_obs = self.df_observations.sort_values(['observed_at', 'observation_id']).groupby('property_id').tail(1)
        df_current = pd.merge(self.df_properties, latest_obs, on='property_id', how='inner')
        
        valid_prices = df_current['price'].dropna()
        valid_sqft = df_current[(df_current['price'].notnull()) & (df_current['sqft'] > 0)].copy()
        
        summary = {
            "total_properties": len(self.df_properties),
            "average_price": float(valid_prices.mean()) if not valid_prices.empty else None,
            "median_price": float(valid_prices.median()) if not valid_prices.empty else None,
            "min_price": float(valid_prices.min()) if not valid_prices.empty else None,
            "max_price": float(valid_prices.max()) if not valid_prices.empty else None,
        }
        
        if not valid_sqft.empty:
            valid_sqft['calc_price_per_sqft'] = valid_sqft['price'] / valid_sqft['sqft']
            summary["average_price_per_sqft"] = float(valid_sqft['calc_price_per_sqft'].mean())
            summary["min_price_per_sqft"] = float(valid_sqft['calc_price_per_sqft'].min())
            summary["max_price_per_sqft"] = float(valid_sqft['calc_price_per_sqft'].max())
        else:
            summary["average_price_per_sqft"] = None
            summary["min_price_per_sqft"] = None
            summary["max_price_per_sqft"] = None
            
        if 'property_type' in df_current.columns:
            summary["count_by_type"] = df_current['property_type'].value_counts().to_dict()
        else:
            summary["count_by_type"] = {}
            
        if 'bedrooms' in df_current.columns:
            summary["count_by_bedrooms"] = df_current['bedrooms'].value_counts().to_dict()
        else:
            summary["count_by_bedrooms"] = {}
            
        return summary

    def analyze_by_location(self) -> pd.DataFrame:
        """Analyzes market by ZIP code."""
        if self.df_properties.empty or self.df_observations.empty or 'zip_code' not in self.df_properties.columns:
            return pd.DataFrame()
            
        latest_obs = self.df_observations.sort_values(['observed_at', 'observation_id']).groupby('property_id').tail(1)
        df = pd.merge(self.df_properties, latest_obs, on='property_id', how='inner')
        
        df['price_per_sqft_calc'] = np.where((df['price'].notnull()) & (df['sqft'] > 0), df['price'] / df['sqft'], np.nan)
        
        agg_funcs = {
            'property_id': 'count',
            'price': ['mean', 'median', 'min', 'max'],
            'price_per_sqft_calc': 'mean'
        }
        
        location_stats = df.groupby('zip_code').agg(agg_funcs).reset_index()
        location_stats.columns = ['zip_code', 'property_count', 'average_price', 'median_price', 'min_price', 'max_price', 'average_price_per_sqft']
        return location_stats
        
    def calculate_price_history(self) -> pd.DataFrame:
        """Calculates comprehensive historical price trends per property."""
        if self.df_observations.empty:
            return pd.DataFrame()
            
        df_obs = self.df_observations[self.df_observations['price'].notnull()].copy()
        if df_obs.empty:
            return pd.DataFrame()
            
        df_obs = df_obs.sort_values(['property_id', 'observed_at', 'observation_id'])
        
        def calculate_prop_history(group):
            prices = group['price'].tolist()
            dates = group['observed_at'].tolist()
            
            if len(prices) == 0:
                return pd.Series(dtype='float64')
                
            current_price = prices[-1]
            previous_price = prices[-2] if len(prices) > 1 else None
            
            total_change = current_price - prices[0] if len(prices) > 0 else 0
            change_pct = (total_change / prices[0] * 100) if len(prices) > 0 and prices[0] > 0 else 0
            
            return pd.Series({
                'current_price': current_price,
                'previous_price': previous_price,
                'total_change': total_change,
                'percentage_change': change_pct,
                'highest_price': max(prices),
                'lowest_price': min(prices),
                'price_changes': len(prices) - 1,
                'first_observed': dates[0],
                'latest_observed': dates[-1]
            })
            
        history_df = df_obs.groupby('property_id').apply(calculate_prop_history, include_groups=False).reset_index()
        return history_df

    def analyze_status_changes(self) -> pd.DataFrame:
        if self.df_observations.empty:
            return pd.DataFrame()
            
        df_obs = self.df_observations[self.df_observations['status'].notnull()].copy()
        if df_obs.empty:
            return pd.DataFrame()
            
        df_obs = df_obs.sort_values(['property_id', 'observed_at', 'observation_id'])
        
        def calculate_status_history(group):
            statuses = group['status'].tolist()
            if not statuses:
                return pd.Series({'current_status': None, 'status_changes': 0})
            
            changes = 0
            for i in range(1, len(statuses)):
                if statuses[i] != statuses[i-1]:
                    changes += 1
                    
            return pd.Series({
                'current_status': statuses[-1],
                'status_changes': changes
            })
            
        status_df = df_obs.groupby('property_id').apply(calculate_status_history, include_groups=False).reset_index()
        return status_df

    def compare_properties(self) -> pd.DataFrame:
        """Creates a flattened view for property comparison."""
        if self.df_properties.empty or self.df_observations.empty:
            return pd.DataFrame()
            
        latest_obs = self.df_observations.sort_values(['observed_at', 'observation_id']).groupby('property_id').tail(1)
        df = pd.merge(self.df_properties, latest_obs, on='property_id', how='inner')
        return df

    def generate_insights(self) -> Dict[str, Any]:
        """Generates descriptive string insights."""
        summary = self.calculate_market_summary()
        loc_stats = self.analyze_by_location()
        history_stats = self.calculate_price_history()
        
        insights = {}
        
        if not summary:
            return {"message": "Not enough data for insights."}
            
        if summary.get("count_by_type"):
            most_common_type = max(summary["count_by_type"].items(), key=lambda x: x[1])
            insights["most_common_type"] = f"{most_common_type[0]} ({most_common_type[1]} properties)"
            
        if summary.get("count_by_bedrooms"):
            most_common_beds = max(summary["count_by_bedrooms"].items(), key=lambda x: x[1])
            insights["most_common_bedrooms"] = f"{most_common_beds[0]} beds ({most_common_beds[1]} properties)"
            
        if not loc_stats.empty:
            highest_zip = loc_stats.loc[loc_stats['average_price'].idxmax()]
            lowest_zip = loc_stats.loc[loc_stats['average_price'].idxmin()]
            insights["highest_avg_price_zip"] = f"{highest_zip['zip_code']} (${highest_zip['average_price']:,.2f})"
            insights["lowest_avg_price_zip"] = f"{lowest_zip['zip_code']} (${lowest_zip['average_price']:,.2f})"
            
        if not history_stats.empty:
            reductions = history_stats[history_stats['total_change'] < 0]
            if not reductions.empty:
                max_reduction = reductions.loc[reductions['total_change'].idxmin()]
                insights["largest_price_reduction"] = f"Property {max_reduction['property_id']} dropped by ${abs(max_reduction['total_change']):,.2f}"
                insights["properties_with_reductions"] = len(reductions)
                insights["average_reduction"] = float(reductions['total_change'].mean())
                insights["average_reduction_percentage"] = float(reductions['percentage_change'].mean())
                
        return insights
