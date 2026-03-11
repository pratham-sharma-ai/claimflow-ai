"""
Vector Store for ClaimFlow AI.

Uses ChromaDB for local vector storage and similarity search.
Stores precedent embeddings for semantic retrieval.
"""

from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

from .scraper import Precedent
from ..llm.gemini_client import GeminiClient
from ..utils.logger import get_logger
from ..utils.config import get_project_root

logger = get_logger("claimflow.vectorstore")


class VectorStore:
    """
    Local vector store using ChromaDB.

    Stores precedent embeddings and supports semantic search
    to find relevant rulings for a given query.
    """

    def __init__(
        self,
        llm_client: GeminiClient,
        collection_name: str = "precedents",
        persist_dir: Path | None = None,
    ):
        """
        Initialize vector store.

        Args:
            llm_client: Gemini client for generating embeddings.
            collection_name: Name of the ChromaDB collection.
            persist_dir: Directory for persistent storage.
        """
        self.llm_client = llm_client
        self.collection_name = collection_name
        self.persist_dir = persist_dir or get_project_root() / "data" / "chroma"
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB with persistence
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Insurance precedents and rulings"}
        )

        logger.info(
            f"Vector store initialized. Collection '{collection_name}' has "
            f"{self._collection.count()} documents."
        )

    def add_precedent(self, precedent: Precedent) -> None:
        """
        Add a single precedent to the store.

        Args:
            precedent: Precedent object to add.
        """
        # Create text for embedding
        text_for_embedding = f"{precedent.title}\n{precedent.summary}\n{precedent.key_ruling}"

        # Generate embedding
        embeddings = self.llm_client.embed(text_for_embedding)

        # Add to collection
        self._collection.add(
            ids=[precedent.id],
            embeddings=embeddings,
            documents=[text_for_embedding],
            metadatas=[{
                "source": precedent.source,
                "url": precedent.url,
                "title": precedent.title,
                "summary": precedent.summary,
                "key_ruling": precedent.key_ruling,
                "tags": ",".join(precedent.applicable_to),
                "date_scraped": precedent.date_scraped,
            }]
        )

        logger.debug(f"Added precedent: {precedent.id}")

    def add_precedents(self, precedents: list[Precedent]) -> int:
        """
        Add multiple precedents to the store.

        Args:
            precedents: List of Precedent objects.

        Returns:
            Number of precedents added.
        """
        if not precedents:
            return 0

        # Prepare batch data
        ids = []
        documents = []
        metadatas = []
        texts_for_embedding = []

        for p in precedents:
            # Skip if already exists
            existing = self._collection.get(ids=[p.id])
            if existing["ids"]:
                continue

            text = f"{p.title}\n{p.summary}\n{p.key_ruling}"
            ids.append(p.id)
            documents.append(text)
            texts_for_embedding.append(text)
            metadatas.append({
                "source": p.source,
                "url": p.url,
                "title": p.title,
                "summary": p.summary,
                "key_ruling": p.key_ruling,
                "tags": ",".join(p.applicable_to),
                "date_scraped": p.date_scraped,
            })

        if not ids:
            logger.info("No new precedents to add")
            return 0

        # Generate embeddings in batch
        embeddings = self.llm_client.embed(texts_for_embedding)

        # Add to collection
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info(f"Added {len(ids)} precedents to vector store")
        return len(ids)

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_tags: list[str] | None = None,
    ) -> list[dict]:
        """
        Search for relevant precedents.

        Args:
            query: Search query (e.g., rejection reason, condition).
            top_k: Number of results to return.
            filter_tags: Optional tags to filter by.

        Returns:
            List of matching precedents with scores.
        """
        # Generate query embedding
        query_embedding = self.llm_client.embed(query)[0]

        # Build where filter
        where_filter = None
        if filter_tags:
            # ChromaDB uses $contains for partial string match
            where_filter = {
                "$or": [{"tags": {"$contains": tag}} for tag in filter_tags]
            }

        # Query collection
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        precedents = []
        if results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0

                precedents.append({
                    "id": id_,
                    "title": metadata.get("title", ""),
                    "summary": metadata.get("summary", ""),
                    "key_ruling": metadata.get("key_ruling", ""),
                    "source_url": metadata.get("url", ""),
                    "source": metadata.get("source", ""),
                    "tags": metadata.get("tags", "").split(","),
                    "relevance_score": 1 - distance,  # Convert distance to similarity
                })

        logger.debug(f"Search returned {len(precedents)} results for: {query[:50]}...")
        return precedents

    def search_for_rejection(
        self,
        rejection_type: str,
        condition_claimed: str,
        condition_cited: str | None = None,
    ) -> list[dict]:
        """
        Search for precedents relevant to a specific rejection.

        Args:
            rejection_type: Type of rejection (non_disclosure, pre_existing, etc.)
            condition_claimed: Medical condition being claimed.
            condition_cited: Condition cited by insurer (if any).

        Returns:
            List of relevant precedents.
        """
        # Build comprehensive query
        query_parts = [
            f"insurance claim rejected for {rejection_type}",
            f"claim for {condition_claimed}",
        ]
        if condition_cited:
            query_parts.append(f"cited condition {condition_cited} unrelated")

        query = " ".join(query_parts)

        # Determine relevant tags
        tags = [rejection_type]
        if "disclosure" in rejection_type.lower():
            tags.append("non-disclosure")
        if condition_cited:
            tags.append("unrelated-condition")

        return self.search(query, top_k=5, filter_tags=tags)

    def get_all(self) -> list[dict]:
        """Get all precedents in the store."""
        results = self._collection.get(include=["metadatas"])
        precedents = []
        for i, id_ in enumerate(results["ids"]):
            metadata = results["metadatas"][i] if results["metadatas"] else {}
            precedents.append({
                "id": id_,
                "title": metadata.get("title", ""),
                "source": metadata.get("source", ""),
                "url": metadata.get("url", ""),
            })
        return precedents

    def count(self) -> int:
        """Get count of precedents in store."""
        return self._collection.count()

    def delete(self, precedent_id: str) -> None:
        """Delete a precedent by ID."""
        self._collection.delete(ids=[precedent_id])
        logger.debug(f"Deleted precedent: {precedent_id}")

    def clear(self) -> None:
        """Clear all precedents from the store."""
        # Delete and recreate collection
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.create_collection(
            name=self.collection_name,
            metadata={"description": "Insurance precedents and rulings"}
        )
        logger.info("Vector store cleared")
