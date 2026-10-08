import os
import json
import pandas as pd
from typing import Dict, Any
from app.analysis.engine import AnalysisEngine

class DataExporter:
    def __init__(self, engine: AnalysisEngine, output_dir: str = "data/exports"):
        self.engine = engine
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def export_csv(self):
        """Exports core datasets and analysis results to CSV."""
        if not self.engine.df_properties.empty:
            self.engine.df_properties.to_csv(os.path.join(self.output_dir, "properties.csv"), index=False)
            
        if not self.engine.df_observations.empty:
            self.engine.df_observations.to_csv(os.path.join(self.output_dir, "observations.csv"), index=False)
            
        loc_stats = self.engine.analyze_by_location()
        if not loc_stats.empty:
            loc_stats.to_csv(os.path.join(self.output_dir, "location_analysis.csv"), index=False)
            
        history = self.engine.calculate_price_history()
        if not history.empty:
            history.to_csv(os.path.join(self.output_dir, "price_history.csv"), index=False)
            
        compare = self.engine.compare_properties()
        if not compare.empty:
            compare.to_csv(os.path.join(self.output_dir, "property_comparison.csv"), index=False)
            
        summary = self.engine.calculate_market_summary()
        if summary:
            flat_summary = self._flatten_summary(summary)
            pd.DataFrame([flat_summary]).to_csv(os.path.join(self.output_dir, "market_summary.csv"), index=False)

    def export_json(self):
        """Exports structured JSON records."""
        data = {
            "market_summary": self.engine.calculate_market_summary(),
            "insights": self.engine.generate_insights()
        }
        
        with open(os.path.join(self.output_dir, "analysis_results.json"), "w") as f:
            json.dump(data, f, indent=4)
            
        if not self.engine.df_properties.empty:
            self.engine.df_properties.to_json(
                os.path.join(self.output_dir, "property_records.json"), 
                orient="records", 
                date_format="iso"
            )
            
        history = self.engine.calculate_price_history()
        if not history.empty:
            history.to_json(
                os.path.join(self.output_dir, "price_history.json"), 
                orient="records", 
                date_format="iso"
            )

    def _flatten_summary(self, summary: Dict) -> Dict:
        flat = {}
        for k, v in summary.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    flat[f"{k}_{sub_k}"] = sub_v
            else:
                flat[k] = v
        return flat

    def export_excel(self, filename: str = "market_report.xlsx"):
        """Creates a professional multi-sheet Excel workbook."""
        file_path = os.path.join(self.output_dir, filename)
        
        if self.engine.df_properties.empty and self.engine.df_observations.empty:
            return
            
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            summary = self.engine.calculate_market_summary()
            if summary:
                flat_summary = self._flatten_summary(summary)
                pd.DataFrame([flat_summary]).to_excel(writer, sheet_name="Market Summary", index=False)
                
            if not self.engine.df_properties.empty:
                prop_df = self.engine.df_properties.copy()
                self._remove_tz(prop_df)
                prop_df.to_excel(writer, sheet_name="Properties", index=False)
                
            if not self.engine.df_observations.empty:
                obs_df = self.engine.df_observations.copy()
                self._remove_tz(obs_df)
                obs_df.to_excel(writer, sheet_name="Observations", index=False)
                
            loc_stats = self.engine.analyze_by_location()
            if not loc_stats.empty:
                loc_stats.to_excel(writer, sheet_name="Location Analysis", index=False)
                
            history = self.engine.calculate_price_history()
            if not history.empty:
                self._remove_tz(history)
                history.to_excel(writer, sheet_name="Price History", index=False)
                
                reductions = history[history['total_change'] < 0]
                if not reductions.empty:
                    reductions.to_excel(writer, sheet_name="Price Reductions", index=False)
                    
            compare = self.engine.compare_properties()
            if not compare.empty:
                self._remove_tz(compare)
                compare.to_excel(writer, sheet_name="Property Comparison", index=False)

    def _remove_tz(self, df: pd.DataFrame):
        for col in df.select_dtypes(include=['datetime64[ns, UTC]', 'datetime64[ns]', 'datetimetz']).columns:
            df[col] = df[col].dt.tz_localize(None)
