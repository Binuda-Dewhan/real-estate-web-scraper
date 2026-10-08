# Real Estate Property Data & Market Intelligence System

This project is an end-to-end property data collection and market intelligence pipeline that produces clean, structured and analysis-ready real estate data.

## Architecture

The system is built sequentially across 4 distinct processing layers:
1. **Scraper (Playwright)**: Extracts real estate listings via headless browsers, capturing both JSON-LD structured data and standard DOM text as fallback.
2. **Processing Pipeline (Pydantic)**: Cleans, sanitizes, and normalizes scraped properties into strictly-typed models.
3. **Database (SQLite + SQLAlchemy)**: Persists data into a `Property Master` table (current state) and an `Observation` table (historical tracker). Deduplication logic strictly prevents duplicate entries.
4. **Analysis & Export (Pandas + OpenPyXL)**: Calculates high-level market metrics, compares properties, and aggregates price drops natively through pandas without modifying the SQL source of truth. Outputs are available as `.csv`, `.json`, and a fully structured `.xlsx` workbook.

## Setup Instructions

1. Ensure Python 3.10+ is installed.
2. Clone the repository and navigate to the project directory.
3. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
4. Activate the virtual environment:
   * Windows: `.\venv\Scripts\activate`
   * macOS/Linux: `source venv/bin/activate`
5. Install all dependencies:
   ```bash
   pip install -r requirements.txt
   ```
6. Install Playwright browsers:
   ```bash
   playwright install chromium
   ```

## Usage Instructions

The entire system is orchestrated via `main.py`.

### 1. Scrape & Process Data
To scrape properties in a specific location and immediately save them to the SQLite database:
```bash
python main.py --scrape --location "Austin, TX" --max-listings 20
```
*(You can also use `--visible` to run the browser headfully to observe the behavior).*

### 2. Generate Market Analysis & Exports
To load the database, analyze the latest metrics (including historical price tracking), and generate clean exports in the `data/exports/` directory:
```bash
python main.py --analyze
```

### 3. Run Everything End-to-End
```bash
python main.py --scrape --location "Seattle, WA" --max-listings 50 --analyze
```

## Example Outputs

When running `--analyze`, the following files will be automatically generated inside `data/exports/`:
* `market_report.xlsx` (Professional multi-sheet Excel workbook containing Properties, Observations, Zip Analysis, and Price Reductions)
* `properties.csv` & `observations.csv`
* `market_summary.csv` & `price_history.csv`
* `analysis_results.json` (Structured JSON tree of insights and summaries)

## Known Limitations & Responsible Scraping

- **No Undocumented APIs**: This scraper exclusively targets publicly rendered DOM and JSON-LD structured tags to respect standard boundaries without reverse-engineering internal APIs.
- **Anti-Bot Defenses**: Zillow utilizes aggressive Cloudflare and Captcha bot-protection. This project operates *without* stealth plugins, proxy rotation, or intentional evasion bypasses. If a CAPTCHA is encountered, the script will gracefully log a block message and save a checkpoint, terminating cleanly instead of infinitely crashing.
- **HTML Volatility**: The scraper relies on Next.js `__NEXT_DATA__` hydration scripts. If Zillow significantly redesigns their layout payload, `app/scraper/zillow.py` traversal paths may require updates.

## Testing

The system is rigorously tested across all logic boundaries using `pytest`.
```bash
pytest tests/
```
