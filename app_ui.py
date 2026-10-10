import streamlit as st
import os
import pandas as pd
import traceback

from app.config import settings
from main import setup_db, run_scraper, run_pipeline
from app.analysis.engine import AnalysisEngine
from app.analysis.exporter import DataExporter


# ── Caching ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_engine() -> AnalysisEngine | None:
    clean_path = settings.db_path.replace("sqlite:///", "")
    if not os.path.exists(clean_path):
        return None
    engine = AnalysisEngine(clean_path)
    engine.load_data()
    return engine


def generate_exports(engine: AnalysisEngine):
    os.makedirs("data/exports", exist_ok=True)
    exporter = DataExporter(engine, output_dir="data/exports")
    exporter.export_csv()
    exporter.export_json()
    exporter.export_excel("market_report.xlsx")


# ── Helpers ──────────────────────────────────────────────────────────────────
def fmt_price(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return f"${float(v):,.0f}"


def fmt_sqft(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return f"{float(v):,.0f} sqft"


def build_listings_view(engine: AnalysisEngine) -> pd.DataFrame:
    """Builds a clean, user-friendly property table from compare_properties()."""
    df = engine.compare_properties()
    if df.empty:
        return df

    # Pick & rename only the columns that are meaningful
    col_map = {
        "address": "Address",
        "city": "City",
        "state": "State",
        "zip_code": "ZIP",
        "property_type": "Type",
        "bedrooms": "Beds",
        "bathrooms": "Baths",
        "sqft": "Sqft",
        "price": "Price",
        "price_per_sqft": "Price/Sqft",
        "status": "Status",
        "listing_url": "Listing URL",
    }
    available = {k: v for k, v in col_map.items() if k in df.columns}
    out = df[list(available.keys())].rename(columns=available).copy()

    # Format numeric columns
    if "Price" in out.columns:
        out["Price"] = out["Price"].apply(fmt_price)
    if "Price/Sqft" in out.columns:
        out["Price/Sqft"] = out["Price/Sqft"].apply(fmt_price)
    if "Sqft" in out.columns:
        out["Sqft"] = out["Sqft"].apply(fmt_sqft)
    if "Beds" in out.columns:
        out["Beds"] = out["Beds"].apply(lambda x: str(int(x)) if pd.notnull(x) else "N/A")
    if "Baths" in out.columns:
        out["Baths"] = out["Baths"].apply(lambda x: str(int(x)) if pd.notnull(x) else "N/A")

    return out


def build_price_history_view(engine: AnalysisEngine) -> pd.DataFrame:
    """Merges price history with addresses for readability."""
    hist = engine.calculate_price_history()
    if hist.empty:
        return hist

    if not engine.df_properties.empty:
        addr_df = engine.df_properties[
            ["property_id"] + [c for c in ["address", "city", "zip_code"] if c in engine.df_properties.columns]
        ]
        hist = hist.merge(addr_df, on="property_id", how="left")

    # Reorder: address columns first
    front_cols = [c for c in ["address", "city", "zip_code"] if c in hist.columns]
    back_cols = [c for c in hist.columns if c not in front_cols + ["property_id"]]
    hist = hist[front_cols + back_cols]

    # Format monetary columns
    for col in ["current_price", "previous_price", "total_change", "highest_price", "lowest_price"]:
        if col in hist.columns:
            hist[col] = hist[col].apply(fmt_price)
    if "percentage_change" in hist.columns:
        hist["percentage_change"] = hist["percentage_change"].apply(
            lambda x: f"{x:+.1f}%" if pd.notnull(x) else "N/A"
        )

    col_rename = {
        "address": "Address", "city": "City", "zip_code": "ZIP",
        "current_price": "Current Price", "previous_price": "Prev Price",
        "total_change": "Total Change", "percentage_change": "% Change",
        "highest_price": "Peak Price", "lowest_price": "Low Price",
        "price_changes": "# Observations", "first_observed": "First Seen",
        "latest_observed": "Last Seen",
    }
    hist = hist.rename(columns={k: v for k, v in col_rename.items() if k in hist.columns})
    return hist


def build_status_view(engine: AnalysisEngine) -> pd.DataFrame:
    """Merges status changes with addresses for readability."""
    status = engine.analyze_status_changes()
    if status.empty:
        return status

    if not engine.df_properties.empty:
        addr_df = engine.df_properties[
            ["property_id"] + [c for c in ["address", "city"] if c in engine.df_properties.columns]
        ]
        status = status.merge(addr_df, on="property_id", how="left")

    front = [c for c in ["address", "city"] if c in status.columns]
    status = status[front + [c for c in status.columns if c not in front + ["property_id"]]]
    return status.rename(columns={"address": "Address", "city": "City",
                                   "current_status": "Current Status",
                                   "status_changes": "Status Changes"})


# ── Sidebar ──────────────────────────────────────────────────────────────────
def render_sidebar() -> tuple:
    st.sidebar.header("🔍 Scraper Controls")
    location = st.sidebar.text_input("Location", value="Seattle, WA",
                                      help="e.g. 'Austin, TX' or 'Miami, FL'")
    max_listings = st.sidebar.number_input("Max Listings", min_value=1, max_value=200, value=10, step=1)
    headless = st.sidebar.checkbox("Headless Browser (Hidden)", value=False,
                                    help="Uncheck to see the browser (recommended — Zillow blocks headless mode)")
    run = st.sidebar.button("▶ Run Scraper", type="primary", use_container_width=True)

    st.sidebar.divider()
    # Show last data update time from the DB
    engine = load_engine()
    if engine and not engine.df_properties.empty:
        last_updated = engine.df_properties["last_updated_at"].max()
        st.sidebar.caption(f"📅 Last data update:  \n**{pd.to_datetime(last_updated).strftime('%b %d %Y, %H:%M')}**")
        st.sidebar.caption(f"🏠 {len(engine.df_properties)} properties in database")
    else:
        st.sidebar.caption("ℹ️ No data yet. Run the scraper to get started.")

    return location, max_listings, headless, run


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Real Estate Market Intelligence",
        page_icon="🏠",
        layout="wide",
    )

    st.title("🏠 Real Estate Market Intelligence")

    location, max_listings, headless, run = render_sidebar()

    if run:
        if not location.strip():
            st.sidebar.error("Please enter a valid location.")
        else:
            with st.spinner(f"Scraping '{location}'…  This launches a browser window."):
                try:
                    session = setup_db(settings.db_path)
                    raw_data = run_scraper(location=location, max_listings=max_listings, headless=headless)
                    if raw_data:
                        run_pipeline(raw_data, session)
                        st.sidebar.success(f"✅ Scraped & saved {len(raw_data)} listings!")
                        st.cache_resource.clear()
                        st.rerun()
                    else:
                        st.sidebar.warning(
                            "⚠️ No listings returned. Zillow may be blocking access. "
                            "Make sure 'Headless Browser' is **unchecked** and try again."
                        )
                except Exception as e:
                    st.sidebar.error(f"❌ Error: {e}")
                    st.sidebar.code(traceback.format_exc(), language="python")
                finally:
                    if "session" in locals():
                        session.close()

    # ── Load data ────────────────────────────────────────────────────────────
    engine = load_engine()

    if not engine or engine.df_properties.empty:
        st.info("📭 No properties in the database yet. Use the sidebar to run the scraper.", icon="ℹ️")
        return

    summary = engine.calculate_market_summary()

    # ── KPI Metrics ──────────────────────────────────────────────────────────
    st.header("📊 Market Overview")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Properties Tracked", summary.get("total_properties", 0))
    c2.metric("Average Price", fmt_price(summary.get("average_price")))
    c3.metric("Median Price",  fmt_price(summary.get("median_price")))
    c4.metric("Price Range", f"{fmt_price(summary.get('min_price'))} – {fmt_price(summary.get('max_price'))}")
    c5.metric("Avg Price / Sqft", fmt_price(summary.get("average_price_per_sqft")))

    # ── AI Insights strip ─────────────────────────────────────────────────────
    insights = engine.generate_insights()
    if insights and "message" not in insights:
        with st.expander("💡 Market Insights", expanded=True):
            cols = st.columns(len(insights))
            for i, (key, val) in enumerate(insights.items()):
                label = key.replace("_", " ").title()
                cols[i].markdown(f"**{label}**  \n{val}")

    st.divider()

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs(
        ["🏠 Property Listings", "📍 Location Analysis", "📈 Price History", "📥 Downloads"]
    )

    # ── Tab 1: Listings ───────────────────────────────────────────────────────
    with tab1:
        listings_df = build_listings_view(engine)

        if listings_df.empty:
            st.info("No listings to display.")
        else:
            # Quick filter row
            fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
            with fcol1:
                search = st.text_input("🔍 Search address or city", key="search_listings")
            with fcol2:
                status_opts = ["All"] + sorted(listings_df["Status"].dropna().unique().tolist()) if "Status" in listings_df.columns else ["All"]
                status_filter = st.selectbox("Status", status_opts, key="status_filter")
            with fcol3:
                type_opts = ["All"] + sorted(listings_df["Type"].dropna().unique().tolist()) if "Type" in listings_df.columns else ["All"]
                type_filter = st.selectbox("Property Type", type_opts, key="type_filter")

            filtered = listings_df.copy()
            if search:
                mask = filtered.apply(lambda row: search.lower() in row.astype(str).str.lower().to_string(), axis=1)
                filtered = filtered[mask]
            if status_filter != "All" and "Status" in filtered.columns:
                filtered = filtered[filtered["Status"] == status_filter]
            if type_filter != "All" and "Type" in filtered.columns:
                filtered = filtered[filtered["Type"] == type_filter]

            st.caption(f"Showing {len(filtered)} of {len(listings_df)} properties")

            # Render clickable links
            if "Listing URL" in filtered.columns:
                st.dataframe(
                    filtered,
                    column_config={
                        "Listing URL": st.column_config.LinkColumn("Listing URL", display_text="View on Zillow")
                    },
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.dataframe(filtered, use_container_width=True, hide_index=True)

        # Price distribution chart
        if not engine.df_observations.empty and "price" in engine.df_observations.columns:
            prices = engine.df_observations["price"].dropna()
            if not prices.empty:
                st.subheader("Price Distribution")
                n_bins = min(15, max(3, len(prices.unique())))
                try:
                    counts = pd.cut(prices, bins=n_bins).value_counts().sort_index()
                    chart_df = pd.DataFrame({"Count": counts.values},
                                            index=[f"${int(b.left):,}–${int(b.right):,}" for b in counts.index])
                    st.bar_chart(chart_df)
                except Exception:
                    st.bar_chart(prices.value_counts().sort_index().rename("Count"))

    # ── Tab 2: Location Analysis ──────────────────────────────────────────────
    with tab2:
        st.subheader("Market Statistics by ZIP Code")
        loc_df = engine.analyze_by_location()
        if loc_df.empty:
            st.info("No location data available — ZIP code data may not have been captured for these listings.")
        else:
            # Format monetary columns for display
            display_loc = loc_df.copy()
            for col in ["average_price", "median_price", "min_price", "max_price", "average_price_per_sqft"]:
                if col in display_loc.columns:
                    display_loc[col] = display_loc[col].apply(fmt_price)
            display_loc = display_loc.rename(columns={
                "zip_code": "ZIP Code",
                "property_count": "# Properties",
                "average_price": "Avg Price",
                "median_price": "Median Price",
                "min_price": "Min Price",
                "max_price": "Max Price",
                "average_price_per_sqft": "Avg $/Sqft",
            })
            st.dataframe(display_loc, use_container_width=True, hide_index=True)

    # ── Tab 3: Price History ──────────────────────────────────────────────────
    with tab3:
        hist_view = build_price_history_view(engine)
        if hist_view.empty:
            st.info("No price history available. More data will accumulate as you run the scraper multiple times for the same location.")
        else:
            st.subheader("Price Changes per Property")
            # Highlight properties with price drops
            if "% Change" in hist_view.columns:
                st.caption("Properties with a negative % change have had their price reduced since first observed.")
            st.dataframe(hist_view, use_container_width=True, hide_index=True)

        st.subheader("Status Changes")
        status_view = build_status_view(engine)
        if status_view.empty:
            st.info("No status change history available.")
        else:
            st.dataframe(status_view, use_container_width=True, hide_index=True)

    # ── Tab 4: Downloads ──────────────────────────────────────────────────────
    with tab4:
        st.subheader("Export Data")

        # Re-generate exports fresh on tab visit
        try:
            generate_exports(engine)
        except Exception as e:
            st.warning(f"Could not refresh exports: {e}")

        st.write("Download the latest data from your local database.")

        col1, col2, col3 = st.columns(3)
        with col1:
            try:
                with open("data/exports/market_report.xlsx", "rb") as f:
                    st.download_button(
                        "📊 Excel Market Report", f,
                        file_name="market_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                st.caption("Full multi-sheet report with all data.")
            except FileNotFoundError:
                st.warning("Excel report not available yet.")

        with col2:
            try:
                with open("data/exports/properties.csv", "rb") as f:
                    st.download_button(
                        "🏘️ Properties CSV", f,
                        file_name="properties.csv", mime="text/csv",
                        use_container_width=True,
                    )
                st.caption("One row per unique property.")
            except FileNotFoundError:
                st.info("No CSV yet.")

        with col3:
            try:
                with open("data/exports/observations.csv", "rb") as f:
                    st.download_button(
                        "📋 Observations CSV", f,
                        file_name="observations.csv", mime="text/csv",
                        use_container_width=True,
                    )
                st.caption("Full price/status history per property.")
            except FileNotFoundError:
                st.info("No CSV yet.")


if __name__ == "__main__":
    main()
