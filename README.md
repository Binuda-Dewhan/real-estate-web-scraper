# Real Estate Property Data & Market Intelligence System

This project is an end-to-end property data collection and market intelligence pipeline that produces clean, structured and analysis-ready real estate data. 

## Phase 1: Foundation & Data Layer
The foundation is built using Python, Pydantic for validation, and SQLite via SQLAlchemy for the persistence layer.

### Setup
1. Create virtual environment: `python -m venv venv`
2. Activate: `.\venv\Scripts\activate` (Windows)
3. Install dependencies: `pip install -r requirements.txt`

### Tests
Run tests via `pytest`:
```bash
pytest tests/
```
