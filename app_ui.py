import streamlit as st
import os
import pandas as pd
import traceback
from datetime import datetime

from app.config import settings
from app.logger import logger
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
    val = float(v)
    if val < 0:
        return f"-${abs(val):,.0f}"
    return f"${val:,.0f}"


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

    # If only 1 observation exists, display 'Insufficient History' rather than 0%
    if "percentage_change" in hist.columns:
        hist["percentage_change"] = hist.apply(
            lambda row: f"{row['percentage_change']:+.1f}%"
            if pd.notnull(row.get("percentage_change")) and row.get("price_changes", 0) > 0
            else "Insufficient History",
            axis=1,
        )

    col_rename = {
        "address": "Address", "city": "City", "zip_code": "ZIP",
        "current_price": "Current Price", "previous_price": "Prev Price",
        "total_change": "Total Change", "percentage_change": "% Change",
        "highest_price": "Peak Price", "lowest_price": "Low Price",
        "price_changes": "Price Changes", "first_observed": "First Seen",
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
    headless = st.sidebar.checkbox(
        "Headless Browser (Hidden)", 
        value=False,
        help="Run browser in background. Uncheck to display browser window for visual debugging and observing portal navigation."
    )
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

    # Show preserved notifications across rerun
    if "scrape_notification" in st.session_state:
        notif = st.session_state.pop("scrape_notification")
        level = notif.get("level", "info")
        msg = notif.get("message", "")
        details = notif.get("details")

        if level == "success":
            st.sidebar.success(f"✅ {msg}")
        elif level == "warning":
            st.sidebar.warning(f"⚠️ {msg}")
        elif level == "error":
            st.sidebar.error(f"❌ {msg}")
        else:
            st.sidebar.info(msg)

        if details:
            with st.sidebar.expander("Validation & Processing Notes"):
                st.text(details)

    if run:
        if not location.strip():
            st.sidebar.error("Please enter a valid location.")
        else:
            with st.spinner(f"Scraping '{location}'…  Please wait."):
                session = None
                try:
                    session = setup_db(settings.db_path)
                    raw_data = run_scraper(location=location, max_listings=max_listings, headless=headless)
                    if raw_data:
                        result = run_pipeline(raw_data, session)

                        # Cleanly close session and dispose connection pool
                        bind_engine = session.get_bind()
                        session.close()
                        if bind_engine:
                            bind_engine.dispose()
                        session = None

                        # Clear Streamlit cached engine resource
                        st.cache_resource.clear()

                        # Automatically generate fresh export packages for the updated data
                        fresh_engine = load_engine()
                        if fresh_engine:
                            try:
                                generate_exports(fresh_engine)
                            except Exception as exp_err:
                                logger.warning(f"Could not auto-generate exports: {exp_err}")

                        # Store structured result in session_state to survive rerun
                        if result.failed_count == 0:
                            st.session_state["scrape_notification"] = {
                                "level": "success",
                                "message": f"Collected {result.total_raw} raw listings; all {result.processed_count} verified & saved.",
                                "details": None,
                            }
                        else:
                            details_text = "\n".join([f"• {r.get('error')}" for r in result.invalid_records[:10]])
                            if len(result.invalid_records) > 10:
                                details_text += f"\n... and {len(result.invalid_records) - 10} more."
                            st.session_state["scrape_notification"] = {
                                "level": "warning",
                                "message": f"Collected {result.total_raw} raw listings: {result.processed_count} saved, {result.failed_count} skipped/failed validation.",
                                "details": details_text,
                            }
                        st.rerun()
                    else:
                        st.sidebar.warning(
                            "⚠️ No listings returned. The portal may be restricting access, requiring rate limit pacing, or presenting a verification challenge. "
                            "You can enable visible browser mode to inspect the page visually, or try again later."
                        )
                except Exception as e:
                    logger.error(f"Error during scrape execution: {e}\n{traceback.format_exc()}")
                    st.sidebar.error(f"❌ Scraper error: {str(e)}")
                    with st.sidebar.expander("Diagnostic Traceback"):
                        st.code(traceback.format_exc(), language="python")
                finally:
                    if session:
                        bind_engine = session.get_bind()
                        session.close()
                        if bind_engine:
                            bind_engine.dispose()

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

        # Price distribution chart (using latest observation per property)
        current_df = engine.compare_properties()
        if not current_df.empty and "price" in current_df.columns:
            prices = current_df["price"].dropna()
            if not prices.empty:
                st.subheader("Price Distribution (Current Market)")
                n_bins = min(15, max(3, len(prices.unique())))
                try:
                    counts = pd.cut(prices, bins=n_bins).value_counts().sort_index()
                    chart_df = pd.DataFrame(
                        {"Count": counts.values},
                        index=[f"${int(b.left):,}–${int(b.right):,}" for b in counts.index],
                    )
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
            if "% Change" in hist_view.columns:
                st.caption(
                    "Properties with a negative % change have had their price reduced since first observed. "
                    "Properties observed only once show 'Insufficient History'."
                )
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
        st.write("Download formatted market intelligence reports and datasets.")

        excel_path = "data/exports/market_report.xlsx"
        props_path = "data/exports/properties.csv"
        obs_path = "data/exports/observations.csv"

        # Explicit action to regenerate reports without running on every rerun
        col_gen, col_info = st.columns([1, 2])
        with col_gen:
            if st.button("🔄 Generate / Refresh Reports", type="secondary", use_container_width=True):
                with st.spinner("Generating fresh reports..."):
                    try:
                        generate_exports(engine)
                        st.success("Reports generated successfully!")
                    except Exception as e:
                        st.error(f"Error generating reports: {e}")

        # Check export status and timestamp
        if os.path.exists(excel_path):
            file_mtime = datetime.fromtimestamp(os.path.getmtime(excel_path))
            st.caption(f"📁 Reports last generated: **{file_mtime.strftime('%b %d, %Y at %H:%M:%S')}**")

            # Check if database has newer updates than the exported files
            if not engine.df_properties.empty and "last_updated_at" in engine.df_properties.columns:
                last_db_time = pd.to_datetime(engine.df_properties["last_updated_at"].max())
                if hasattr(last_db_time, "tz") and last_db_time.tz:
                    last_db_time = last_db_time.tz_localize(None)
                if last_db_time > file_mtime:
                    st.warning(
                        "⚠️ Database has newer listings than the current report files. "
                        "Click '🔄 Generate / Refresh Reports' to update your downloads."
                    )
        else:
            st.info("ℹ️ Reports have not been generated yet. Click 'Generate / Refresh Reports' above to create them.")

        col1, col2, col3 = st.columns(3)
        with col1:
            if os.path.exists(excel_path):
                with open(excel_path, "rb") as f:
                    file_bytes = f.read()
                st.download_button(
                    "📊 Excel Market Report",
                    data=file_bytes,
                    file_name="market_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
                st.caption("Full multi-sheet report with all data.")
            else:
                st.button("📊 Excel Market Report", disabled=True, use_container_width=True)
                st.caption("Generate reports to enable download.")

        with col2:
            if os.path.exists(props_path):
                with open(props_path, "rb") as f:
                    file_bytes = f.read()
                st.download_button(
                    "🏘️ Properties CSV",
                    data=file_bytes,
                    file_name="properties.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                st.caption("One row per unique property.")
            else:
                st.button("🏘️ Properties CSV", disabled=True, use_container_width=True)
                st.caption("Generate reports to enable download.")

        with col3:
            if os.path.exists(obs_path):
                with open(obs_path, "rb") as f:
                    file_bytes = f.read()
                st.download_button(
                    "📋 Observations CSV",
                    data=file_bytes,
                    file_name="observations.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                st.caption("Full price/status history per property.")
            else:
                st.button("📋 Observations CSV", disabled=True, use_container_width=True)
                st.caption("Generate reports to enable download.")


if __name__ == "__main__":
    main()

