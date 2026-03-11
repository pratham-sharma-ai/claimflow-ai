"""
Precedent Scraper for ClaimFlow AI.

Scrapes insurance-related rulings and articles from:
- Livemint
- Economic Times
- IRDAI circulars
- Insurance Ombudsman decisions
"""

import re
import json
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..llm.gemini_client import GeminiClient
from ..utils.logger import get_logger
from ..utils.config import get_project_root

logger = get_logger("claimflow.scraper")


@dataclass
class Precedent:
    """Represents a scraped precedent/ruling."""
    id: str
    source: str
    url: str
    title: str
    content: str
    summary: str
    key_ruling: str
    applicable_to: list[str]
    date_scraped: str
    date_published: Optional[str] = None
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Precedent":
        return cls(**data)


class PrecedentScraper:
    """
    Scrapes and processes insurance precedents from various sources.

    Uses httpx for HTTP requests and BeautifulSoup for parsing.
    Gemini is used to summarize and extract key rulings.
    """

    SOURCES = {
        "livemint": {
            "base_url": "https://www.livemint.com",
            "search_urls": [
                "/search?q=insurance+claim+rejected",
                "/search?q=irdai+ombudsman+ruling",
                "/search?q=health+insurance+claim+denied",
            ],
            "article_selector": "article a, .listingNew a",
            "title_selector": "h1",
            "content_selector": "article, .mainContent, .contentSec",
        },
        "economictimes": {
            "base_url": "https://economictimes.indiatimes.com",
            "search_urls": [
                "/wealth/insure/health-insurance",
                "/topic/insurance-claim",
            ],
            "article_selector": ".eachStory a, article a",
            "title_selector": "h1",
            "content_selector": "article, .artText, .Normal",
        },
    }

    def __init__(
        self,
        llm_client: GeminiClient | None = None,
        output_dir: Path | None = None,
    ):
        """
        Initialize scraper.

        Args:
            llm_client: Gemini client for summarization.
            output_dir: Directory to save scraped precedents.
        """
        self.llm_client = llm_client
        self.output_dir = output_dir or get_project_root() / "data" / "precedents"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self._scraped_urls: set[str] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        """Load already scraped URLs to avoid duplicates."""
        for file in self.output_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text())
                if isinstance(data, list):
                    for item in data:
                        self._scraped_urls.add(item.get("url", ""))
                else:
                    self._scraped_urls.add(data.get("url", ""))
            except Exception:
                continue

    async def scrape_source(
        self,
        source_name: str,
        max_articles: int = 20,
    ) -> list[Precedent]:
        """
        Scrape precedents from a single source.

        Args:
            source_name: Name of source (livemint, economictimes).
            max_articles: Maximum articles to scrape.

        Returns:
            List of scraped Precedent objects.
        """
        if source_name not in self.SOURCES:
            raise ValueError(f"Unknown source: {source_name}")

        source = self.SOURCES[source_name]
        base_url = source["base_url"]
        precedents = []

        # Get article URLs from search pages
        article_urls = []
        for search_path in source["search_urls"]:
            try:
                urls = await self._get_article_urls(
                    urljoin(base_url, search_path),
                    source["article_selector"],
                    base_url,
                )
                article_urls.extend(urls)
            except Exception as e:
                logger.warning(f"Failed to get articles from {search_path}: {e}")

        # Deduplicate and limit
        article_urls = list(set(article_urls) - self._scraped_urls)[:max_articles]
        logger.info(f"Found {len(article_urls)} new articles from {source_name}")

        # Scrape each article
        for url in article_urls:
            try:
                precedent = await self._scrape_article(
                    url,
                    source_name,
                    source["title_selector"],
                    source["content_selector"],
                )
                if precedent:
                    precedents.append(precedent)
                    self._scraped_urls.add(url)
            except Exception as e:
                logger.warning(f"Failed to scrape {url}: {e}")

            # Rate limiting
            await asyncio.sleep(1)

        return precedents

    async def scrape_all(self, max_per_source: int = 20) -> list[Precedent]:
        """
        Scrape from all configured sources.

        Args:
            max_per_source: Maximum articles per source.

        Returns:
            All scraped precedents.
        """
        all_precedents = []
        for source_name in self.SOURCES:
            try:
                precedents = await self.scrape_source(source_name, max_per_source)
                all_precedents.extend(precedents)
                logger.info(f"Scraped {len(precedents)} from {source_name}")
            except Exception as e:
                logger.error(f"Failed to scrape {source_name}: {e}")

        # Save all precedents
        self._save_precedents(all_precedents)
        return all_precedents

    async def scrape_url(self, url: str) -> Precedent | None:
        """
        Scrape a specific URL.

        Args:
            url: Full URL to scrape.

        Returns:
            Precedent object or None.
        """
        return await self._scrape_article(url, "custom", "h1", "article, main, .content")

    async def _get_article_urls(
        self,
        search_url: str,
        selector: str,
        base_url: str,
    ) -> list[str]:
        """Extract article URLs from a search/listing page."""
        response = await self._client.get(search_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        links = soup.select(selector)

        urls = []
        for link in links:
            href = link.get("href", "")
            if href:
                full_url = urljoin(base_url, href)
                # Filter for article-like URLs
                if any(x in full_url for x in ["/news/", "/article/", "/story/", "/wealth/"]):
                    urls.append(full_url)

        return urls

    async def _scrape_article(
        self,
        url: str,
        source: str,
        title_selector: str,
        content_selector: str,
    ) -> Precedent | None:
        """Scrape a single article."""
        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Request failed for {url}: {e}")
            return None

        soup = BeautifulSoup(response.text, "lxml")

        # Extract title
        title_elem = soup.select_one(title_selector)
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"

        # Extract content
        content_elem = soup.select_one(content_selector)
        if not content_elem:
            logger.warning(f"No content found at {url}")
            return None

        # Get text content
        content = content_elem.get_text(separator="\n", strip=True)

        # Filter for relevant content
        if not self._is_relevant(title, content):
            logger.debug(f"Skipping irrelevant article: {title[:50]}")
            return None

        # Extract/generate summary and key ruling
        summary, key_ruling, tags = await self._extract_insights(title, content)

        precedent_id = f"{source}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(url) % 10000}"

        return Precedent(
            id=precedent_id,
            source=source,
            url=url,
            title=title,
            content=content[:5000],  # Limit content size
            summary=summary,
            key_ruling=key_ruling,
            applicable_to=tags,
            date_scraped=datetime.now().isoformat(),
        )

    def _is_relevant(self, title: str, content: str) -> bool:
        """Check if article is relevant to insurance claims."""
        text = (title + " " + content).lower()
        keywords = [
            "insurance claim",
            "claim rejected",
            "claim denied",
            "ombudsman",
            "irdai",
            "pre-existing",
            "non-disclosure",
            "health insurance",
            "claim settlement",
        ]
        return any(kw in text for kw in keywords)

    async def _extract_insights(
        self,
        title: str,
        content: str,
    ) -> tuple[str, str, list[str]]:
        """Extract summary, key ruling, and tags using LLM."""
        if not self.llm_client:
            # Fallback: simple extraction
            summary = content[:300] + "..."
            key_ruling = "See full article for details"
            tags = ["insurance", "claim"]
            return summary, key_ruling, tags

        prompt = f"""Analyze this insurance-related article and extract:

TITLE: {title}

CONTENT (truncated):
{content[:3000]}

Respond in JSON format:
{{
    "summary": "2-3 sentence summary of the article",
    "key_ruling": "The main precedent or ruling that claimants can cite (1 sentence)",
    "applicable_to": ["list", "of", "relevant", "tags"]
}}

Tags should include relevant categories like: non-disclosure, pre-existing, unrelated-condition,
ombudsman-ruling, irdai-guideline, claim-settlement, documentation, etc."""

        try:
            response = self.llm_client.generate(
                prompt=prompt,
                model=self.llm_client.MODELS["fast"],
                temperature=0.1,
            )

            # Parse JSON
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                cleaned = re.sub(r'```$', '', cleaned)

            data = json.loads(cleaned)
            return (
                data.get("summary", ""),
                data.get("key_ruling", ""),
                data.get("applicable_to", []),
            )
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
            return content[:300] + "...", "See article", ["insurance"]

    def _save_precedents(self, precedents: list[Precedent]) -> None:
        """Save precedents to JSON file."""
        if not precedents:
            return

        filename = f"precedents_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.output_dir / filename

        data = [p.to_dict() for p in precedents]
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"Saved {len(precedents)} precedents to {filepath}")

    def load_all_precedents(self) -> list[Precedent]:
        """Load all saved precedents."""
        precedents = []
        for file in self.output_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text())
                if isinstance(data, list):
                    precedents.extend([Precedent.from_dict(d) for d in data])
                else:
                    precedents.append(Precedent.from_dict(data))
            except Exception as e:
                logger.warning(f"Failed to load {file}: {e}")
        return precedents

    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
