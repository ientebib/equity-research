"""
Source Catalog for web research.

Loads and validates source configuration from YAML.
Provides domain reputation scores and topic-based domain lookups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from er.types import SourceTier, ToSRisk


@dataclass
class DomainPolicy:
    """Policy for a specific domain."""

    domain: str
    tier: SourceTier
    tos_risk: ToSRisk
    allowed_fetch: bool
    reputation_score: float
    notes: str = ""

    @classmethod
    def from_dict(cls, domain: str, data: dict[str, Any]) -> "DomainPolicy":
        """Create from dict."""
        tier_map = {
            "official": SourceTier.OFFICIAL,
            "institutional": SourceTier.INSTITUTIONAL,
            "news": SourceTier.NEWS,
            "other": SourceTier.OTHER,
        }
        tos_map = {
            "none": ToSRisk.NONE,
            "low": ToSRisk.LOW,
            "medium": ToSRisk.MEDIUM,
            "high": ToSRisk.HIGH,
        }

        return cls(
            domain=domain,
            tier=tier_map.get(data.get("tier", "other"), SourceTier.OTHER),
            tos_risk=tos_map.get(data.get("tos_risk", "medium"), ToSRisk.MEDIUM),
            allowed_fetch=data.get("allowed_fetch", True),
            reputation_score=data.get("reputation_score", 0.5),
            notes=data.get("notes", ""),
        )


@dataclass
class TopicConfig:
    """Configuration for a topic."""

    name: str
    domains: list[str]
    description: str = ""


@dataclass
class CategoryConfig:
    """Configuration for a coverage category."""

    name: str
    min_evidence_cards: int
    recency_days: int
    preferred_topics: list[str]
    applicable_sectors: list[str] = field(default_factory=list)


class SourceCatalog:
    """Catalog of sources for web research.

    Loads configuration from YAML and provides:
    - Domain reputation scores
    - Topic-based domain lookups
    - ToS policy enforcement
    - Coverage category configuration
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        """Initialize the source catalog.

        Args:
            config_path: Path to sources.yml. If None, uses default location.
        """
        if config_path is None:
            # Default to config/sources.yml relative to project root
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "sources.yml"
        else:
            config_path = Path(config_path)

        self.config_path = config_path
        self.topics: dict[str, TopicConfig] = {}
        self.domains: dict[str, DomainPolicy] = {}
        self.categories: dict[str, CategoryConfig] = {}
        self._default_policy: DomainPolicy | None = None

        self._load_config()

    def _load_config(self) -> None:
        """Load and validate configuration from YAML."""
        if not self.config_path.exists():
            # Use defaults if config doesn't exist
            self._set_defaults()
            return

        with open(self.config_path) as f:
            config = yaml.safe_load(f)

        # Load topics
        for name, data in config.get("topics", {}).items():
            self.topics[name] = TopicConfig(
                name=name,
                domains=data.get("domains", []),
                description=data.get("description", ""),
            )

        # Load domain policies
        for domain, data in config.get("domains", {}).items():
            if domain == "_default":
                self._default_policy = DomainPolicy.from_dict("_default", data)
            else:
                self.domains[domain] = DomainPolicy.from_dict(domain, data)

        # Load category configs
        for name, data in config.get("coverage_categories", {}).items():
            self.categories[name] = CategoryConfig(
                name=name,
                min_evidence_cards=data.get("min_evidence_cards", 2),
                recency_days=data.get("recency_days", 90),
                preferred_topics=data.get("preferred_topics", []),
                applicable_sectors=data.get("applicable_sectors", []),
            )

    def _set_defaults(self) -> None:
        """Set default configuration if YAML not found."""
        self._default_policy = DomainPolicy(
            domain="_default",
            tier=SourceTier.OTHER,
            tos_risk=ToSRisk.MEDIUM,
            allowed_fetch=True,
            reputation_score=0.5,
        )

    def get_domains_for_tags(self, tags: list[str]) -> list[str]:
        """Get list of domains for the given topic tags.

        Args:
            tags: List of topic tags (e.g., ["tech_analysis", "financial_news"])

        Returns:
            Deduplicated list of domains.
        """
        domains = []
        seen = set()

        for tag in tags:
            topic = self.topics.get(tag)
            if topic:
                for domain in topic.domains:
                    if domain not in seen:
                        domains.append(domain)
                        seen.add(domain)

        return domains

    def get_policy(self, url_or_domain: str) -> DomainPolicy:
        """Get the policy for a URL or domain.

        Args:
            url_or_domain: Either a full URL or just a domain name.

        Returns:
            DomainPolicy for the domain, or default policy if not found.
        """
        # Extract domain from URL if needed
        if url_or_domain.startswith("http"):
            parsed = urlparse(url_or_domain)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
        else:
            domain = url_or_domain.lower()

        # Look up policy
        if domain in self.domains:
            return self.domains[domain]

        # Check if any configured domain is a suffix of the given domain
        for configured_domain, policy in self.domains.items():
            if domain.endswith(configured_domain):
                return policy

        # Return default
        return self._default_policy or DomainPolicy(
            domain=domain,
            tier=SourceTier.OTHER,
            tos_risk=ToSRisk.MEDIUM,
            allowed_fetch=True,
            reputation_score=0.5,
        )

    def get_reputation_score(self, url_or_domain: str) -> float:
        """Get reputation score for a URL or domain.

        Args:
            url_or_domain: Either a full URL or just a domain name.

        Returns:
            Reputation score between 0.0 and 1.0.
        """
        return self.get_policy(url_or_domain).reputation_score

    def is_fetch_allowed(self, url_or_domain: str) -> bool:
        """Check if fetching is allowed for a URL or domain.

        Args:
            url_or_domain: Either a full URL or just a domain name.

        Returns:
            True if fetching is allowed.
        """
        return self.get_policy(url_or_domain).allowed_fetch

    def get_category_config(self, category_name: str) -> CategoryConfig | None:
        """Get configuration for a coverage category.

        Args:
            category_name: Name of the category (e.g., "recent_developments").

        Returns:
            CategoryConfig or None if not found.
        """
        return self.categories.get(category_name)

    def get_preferred_domains_for_category(self, category_name: str) -> list[str]:
        """Get preferred domains for a coverage category.

        Args:
            category_name: Name of the category.

        Returns:
            List of preferred domains.
        """
        config = self.categories.get(category_name)
        if not config:
            return []

        return self.get_domains_for_tags(config.preferred_topics)
