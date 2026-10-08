from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class BaseScraper(ABC):
    """Abstract base class for property scrapers."""
    
    @abstractmethod
    def setup(self):
        """Initialize the scraper (e.g., launch browser)."""
        pass
        
    @abstractmethod
    def teardown(self):
        """Clean up resources (e.g., close browser)."""
        pass
        
    @abstractmethod
    def search(self, location: str, filters: Optional[Dict] = None, max_listings: int = 100) -> List[Dict]:
        """
        Search for listings and return raw property data.
        
        Args:
            location: The location to search (e.g., 'Atlanta, GA').
            filters: Additional search filters (e.g., bedrooms).
            max_listings: Maximum number of listings to retrieve.
            
        Returns:
            A list of dictionaries representing raw listing data.
        """
        pass
