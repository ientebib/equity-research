"""
Evidence Tier Policy for source quality classification.

Provides systematic classification of sources into quality tiers
with policies for how different tiers should be weighted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from er.confidence.calibration import SourceTier


@dataclass
class TierAssignment:
    """Assignment of a source to a quality tier."""

    source_url: str | None
    source_type: str
    tier: SourceTier
    domain: str | None = None
    reason: str = ""
    reputation_score: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "source_url": self.source_url,
            "source_type": self.source_type,
            "tier": self.tier.value,
            "domain": self.domain,
            "reason": self.reason,
            "reputation_score": self.reputation_score,
        }


class EvidenceTierPolicy:
    """Policy for assigning sources to quality tiers.

    Tier Definitions:
    - TIER_1: Primary sources (SEC filings, earnings transcripts, press releases)
    - TIER_2: Secondary sources (analyst reports, institutional research)
    - TIER_3: Tertiary sources (reputable news, trade publications)
    - TIER_4: Quaternary sources (blogs, social media, unverified)
    - DERIVED: Computed/derived from other evidence
    """

    # Domain to tier mappings
    TIER_1_DOMAINS = {
        "sec.gov",
        "investor.apple.com",
        "investor.microsoft.com",
        "investor.google.com",
        "investor.nvidia.com",
        # Add more official investor relations domains
    }

    TIER_2_DOMAINS = {
        "morningstar.com",
        "factset.com",
        "refinitiv.com",
        "spglobal.com",
        "moodys.com",
        "fitchratings.com",
    }

    TIER_3_DOMAINS = {
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "cnbc.com",
        "barrons.com",
        "marketwatch.com",
        "techcrunch.com",
        "theverge.com",
    }

    TIER_4_DOMAINS = {
        "seekingalpha.com",
        "fool.com",
        "investopedia.com",
        "yahoo.com",
        "twitter.com",
        "x.com",
        "reddit.com",
    }

    # Source type mappings (lowercase keys)
    SOURCE_TYPE_TIERS = {
        "10-k": SourceTier.TIER_1,
        "10-q": SourceTier.TIER_1,
        "8-k": SourceTier.TIER_1,
        "transcript": SourceTier.TIER_1,
        "earnings_transcript": SourceTier.TIER_1,
        "press_release": SourceTier.TIER_1,
        "proxy": SourceTier.TIER_1,
        "analyst_report": SourceTier.TIER_2,
        "research_report": SourceTier.TIER_2,
        "news": SourceTier.TIER_3,
        "article": SourceTier.TIER_3,
        "blog": SourceTier.TIER_4,
        "social": SourceTier.TIER_4,
        "computed": SourceTier.DERIVED,
        "derived": SourceTier.DERIVED,
    }

    def __init__(
        self,
        custom_tier_1: set[str] | None = None,
        custom_tier_2: set[str] | None = None,
        custom_tier_3: set[str] | None = None,
    ) -> None:
        """Initialize the tier policy.

        Args:
            custom_tier_1: Additional TIER_1 domains.
            custom_tier_2: Additional TIER_2 domains.
            custom_tier_3: Additional TIER_3 domains.
        """
        self.tier_1_domains = self.TIER_1_DOMAINS.copy()
        self.tier_2_domains = self.TIER_2_DOMAINS.copy()
        self.tier_3_domains = self.TIER_3_DOMAINS.copy()

        if custom_tier_1:
            self.tier_1_domains.update(custom_tier_1)
        if custom_tier_2:
            self.tier_2_domains.update(custom_tier_2)
        if custom_tier_3:
            self.tier_3_domains.update(custom_tier_3)

    def assign_tier(
        self,
        source_url: str | None = None,
        source_type: str | None = None,
        domain: str | None = None,
    ) -> TierAssignment:
        """Assign a source to a quality tier.

        Args:
            source_url: URL of the source.
            source_type: Type of source (e.g., "10-K", "news").
            domain: Domain of the source (extracted from URL if not provided).

        Returns:
            TierAssignment with tier and reasoning.
        """
        # Extract domain from URL if not provided
        if domain is None and source_url:
            domain = self._extract_domain(source_url)

        # First check source type
        if source_type:
            source_type_lower = source_type.lower()
            if source_type_lower in self.SOURCE_TYPE_TIERS:
                tier = self.SOURCE_TYPE_TIERS[source_type_lower]
                return TierAssignment(
                    source_url=source_url,
                    source_type=source_type,
                    tier=tier,
                    domain=domain,
                    reason=f"Source type '{source_type}' maps to {tier.value}",
                    reputation_score=self._get_tier_reputation(tier),
                )

        # Then check domain
        if domain:
            tier = self._get_domain_tier(domain)
            return TierAssignment(
                source_url=source_url,
                source_type=source_type or "unknown",
                tier=tier,
                domain=domain,
                reason=f"Domain '{domain}' maps to {tier.value}",
                reputation_score=self._get_tier_reputation(tier),
            )

        # Default to TIER_4 for unknown sources
        return TierAssignment(
            source_url=source_url,
            source_type=source_type or "unknown",
            tier=SourceTier.TIER_4,
            domain=domain,
            reason="Unknown source defaulted to TIER_4",
            reputation_score=0.3,
        )

    def _extract_domain(self, url: str) -> str | None:
        """Extract domain from URL."""
        match = re.search(r'(?:https?://)?(?:www\.)?([^/]+)', url)
        if match:
            return match.group(1).lower()
        return None

    def _get_domain_tier(self, domain: str) -> SourceTier:
        """Get tier for a domain."""
        domain_lower = domain.lower()

        # Check each tier
        for tier1_domain in self.tier_1_domains:
            if tier1_domain in domain_lower:
                return SourceTier.TIER_1

        for tier2_domain in self.tier_2_domains:
            if tier2_domain in domain_lower:
                return SourceTier.TIER_2

        for tier3_domain in self.tier_3_domains:
            if tier3_domain in domain_lower:
                return SourceTier.TIER_3

        for tier4_domain in self.TIER_4_DOMAINS:
            if tier4_domain in domain_lower:
                return SourceTier.TIER_4

        # Default for unknown domains
        return SourceTier.TIER_4

    def _get_tier_reputation(self, tier: SourceTier) -> float:
        """Get reputation score for a tier."""
        reputation_map = {
            SourceTier.TIER_1: 1.0,
            SourceTier.TIER_2: 0.85,
            SourceTier.TIER_3: 0.7,
            SourceTier.TIER_4: 0.4,
            SourceTier.DERIVED: 0.9,
        }
        return reputation_map.get(tier, 0.5)

    def get_tier_policy_description(self, tier: SourceTier) -> str:
        """Get human-readable description of tier policy."""
        descriptions = {
            SourceTier.TIER_1: (
                "Primary sources: SEC filings, earnings transcripts, official press releases. "
                "Highest reliability - direct from company or regulatory body."
            ),
            SourceTier.TIER_2: (
                "Secondary sources: Analyst reports, institutional research. "
                "High reliability - professional analysis with methodological rigor."
            ),
            SourceTier.TIER_3: (
                "Tertiary sources: Major news outlets, trade publications. "
                "Moderate reliability - journalistic standards but subject to error."
            ),
            SourceTier.TIER_4: (
                "Quaternary sources: Blogs, social media, retail investor sites. "
                "Lower reliability - should be corroborated with higher-tier sources."
            ),
            SourceTier.DERIVED: (
                "Derived/computed values: Calculated from other evidence. "
                "Reliability depends on source data quality."
            ),
        }
        return descriptions.get(tier, "Unknown tier")

    def should_require_corroboration(self, tier: SourceTier) -> bool:
        """Check if tier requires corroboration before use."""
        return tier in (SourceTier.TIER_3, SourceTier.TIER_4)

    def get_minimum_sources_for_claim(
        self,
        highest_tier: SourceTier,
    ) -> int:
        """Get minimum number of sources needed based on highest tier available."""
        if highest_tier == SourceTier.TIER_1:
            return 1  # Single primary source is sufficient
        elif highest_tier == SourceTier.TIER_2:
            return 1  # Single analyst report is sufficient
        elif highest_tier == SourceTier.TIER_3:
            return 2  # Need corroboration for news
        else:
            return 3  # Need multiple sources for lower-tier


def classify_sources(
    sources: list[dict[str, Any]],
) -> list[TierAssignment]:
    """Classify a batch of sources into tiers.

    Args:
        sources: List of source dicts with 'url' and/or 'type' keys.

    Returns:
        List of TierAssignments.
    """
    policy = EvidenceTierPolicy()
    assignments = []

    for source in sources:
        assignment = policy.assign_tier(
            source_url=source.get("url"),
            source_type=source.get("type"),
            domain=source.get("domain"),
        )
        assignments.append(assignment)

    return assignments
