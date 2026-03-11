"""Knowledge base module - scraping and vector storage."""

from .scraper import PrecedentScraper
from .vector_store import VectorStore

__all__ = ["PrecedentScraper", "VectorStore"]
