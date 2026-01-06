"""
Sector and business model classifier.

Combines GICS sector with business model characteristics to produce
classifications like "Technology/SaaS", "Financials/Bank", etc.

This enables sector-specific threshold analysis for financial ratios.
"""

from __future__ import annotations

from typing import Any

from er.logging import get_logger

logger = get_logger(__name__)


# Business model keywords mapped to classifications
BUSINESS_MODEL_KEYWORDS: dict[str, list[str]] = {
    # Technology sub-types
    "SaaS": [
        "software as a service", "saas", "subscription software",
        "cloud software", "enterprise software", "platform as a service",
        "infrastructure as a service", "recurring revenue", "arr",
        "annual recurring revenue", "subscription-based",
    ],
    "Hardware": [
        "hardware", "devices", "equipment", "electronics",
        "consumer electronics", "computer hardware", "networking equipment",
        "data center hardware",
    ],
    "Semiconductor": [
        "semiconductor", "chip", "integrated circuit", "fabless",
        "foundry", "processor", "memory chip", "gpu", "cpu",
    ],
    "Internet": [
        "internet", "online platform", "digital advertising",
        "social media", "e-commerce platform", "marketplace",
        "search engine", "streaming",
    ],

    # Financials sub-types
    "Bank": [
        "bank", "banking", "commercial bank", "investment bank",
        "retail bank", "deposits", "loans", "net interest margin",
    ],
    "Insurance": [
        "insurance", "underwriting", "premiums", "claims",
        "life insurance", "property and casualty", "reinsurance",
    ],
    "Asset_Management": [
        "asset management", "investment management", "mutual fund",
        "hedge fund", "private equity", "venture capital",
        "assets under management", "aum",
    ],
    "REIT": [
        "reit", "real estate investment trust", "property",
        "ffo", "funds from operations", "rental income",
        "commercial real estate", "residential properties",
    ],
    "Fintech": [
        "fintech", "payment processing", "digital payments",
        "buy now pay later", "bnpl", "neobank", "digital bank",
    ],

    # Healthcare sub-types
    "Pharma": [
        "pharmaceutical", "drug development", "clinical trials",
        "fda approval", "generic drugs", "branded drugs",
        "patent expiration",
    ],
    "Biotech": [
        "biotechnology", "biotech", "gene therapy", "cell therapy",
        "biologics", "pipeline", "pre-clinical", "phase 1", "phase 2",
    ],
    "Medical_Devices": [
        "medical device", "medical equipment", "diagnostic",
        "surgical equipment", "implant",
    ],
    "Services": [
        "healthcare services", "hospital", "clinic", "outpatient",
        "managed care", "health insurance", "pharmacy benefit",
    ],

    # Consumer sub-types
    "Retail": [
        "retail", "store", "brick and mortar", "shopping",
        "department store", "specialty retail",
    ],
    "E-commerce": [
        "e-commerce", "ecommerce", "online retail", "direct to consumer",
        "d2c", "dtc", "online marketplace",
    ],
    "CPG": [
        "consumer packaged goods", "cpg", "fmcg", "fast moving",
        "household products", "personal care", "food and beverage",
    ],
    "Restaurant": [
        "restaurant", "quick service", "fast food", "casual dining",
        "food service", "same store sales",
    ],
    "Luxury": [
        "luxury", "premium", "high-end", "designer",
    ],

    # Industrials sub-types
    "Manufacturing": [
        "manufacturing", "industrial equipment", "machinery",
        "factory", "production",
    ],
    "Aerospace": [
        "aerospace", "defense", "aircraft", "aviation",
        "military", "government contractor",
    ],
    "Construction": [
        "construction", "engineering", "infrastructure",
        "building materials",
    ],
    "Transportation": [
        "transportation", "logistics", "trucking", "rail",
        "shipping", "freight",
    ],

    # Energy sub-types
    "Oil_Gas": [
        "oil", "gas", "petroleum", "exploration", "production",
        "upstream", "downstream", "refining", "drilling",
    ],
    "Utilities": [
        "utility", "electric utility", "gas utility", "water utility",
        "regulated", "rate base",
    ],
    "Renewables": [
        "renewable", "solar", "wind", "clean energy",
        "green energy", "sustainable energy",
    ],
}

# GICS sector to our sector mapping
GICS_SECTOR_MAPPING: dict[str, str] = {
    "Information Technology": "Technology",
    "Technology": "Technology",
    "Financials": "Financials",
    "Financial Services": "Financials",
    "Healthcare": "Healthcare",
    "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer",
    "Consumer Staples": "Consumer",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Materials": "Materials",
    "Utilities": "Energy",  # Map to Energy for threshold purposes
    "Communication Services": "Technology",  # Media/telecom -> Tech
    "Real Estate": "Financials",  # REITs are financial
}


def _detect_business_model(description: str, industry: str | None = None) -> str | None:
    """Detect business model from company description and industry.

    Args:
        description: Company description text.
        industry: Industry classification if available.

    Returns:
        Business model string or None if not detected.
    """
    if not description:
        return None

    text = description.lower()
    if industry:
        text = f"{text} {industry.lower()}"

    # Check each business model's keywords
    best_match = None
    best_score = 0

    for model, keywords in BUSINESS_MODEL_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_match = model

    return best_match if best_score >= 1 else None


def classify_company(profile: dict[str, Any]) -> str:
    """Classify company into sector/business model combination.

    Args:
        profile: Company profile dict from FMP API.

    Returns:
        Classification string like "Technology/SaaS" or "Financials/Bank".
    """
    # Get GICS sector
    gics_sector = profile.get("sector", "")
    industry = profile.get("industry", "")
    description = profile.get("description", "")

    # Map GICS to our sector
    sector = GICS_SECTOR_MAPPING.get(gics_sector, "")
    if not sector:
        # Try industry as fallback
        for gics, mapped in GICS_SECTOR_MAPPING.items():
            if gics.lower() in industry.lower():
                sector = mapped
                break

    if not sector:
        sector = "Unknown"

    # Detect business model
    business_model = _detect_business_model(description, industry)

    # If no business model detected, try industry-based inference
    if not business_model:
        industry_lower = industry.lower() if industry else ""

        # Industry-based fallbacks
        if "software" in industry_lower:
            business_model = "SaaS"
        elif "semiconductor" in industry_lower:
            business_model = "Semiconductor"
        elif "bank" in industry_lower:
            business_model = "Bank"
        elif "insurance" in industry_lower:
            business_model = "Insurance"
        elif "reit" in industry_lower or "real estate" in industry_lower:
            business_model = "REIT"
        elif "pharmaceutical" in industry_lower:
            business_model = "Pharma"
        elif "biotech" in industry_lower:
            business_model = "Biotech"
        elif "retail" in industry_lower:
            business_model = "Retail"
        elif "restaurant" in industry_lower:
            business_model = "Restaurant"
        elif "oil" in industry_lower or "gas" in industry_lower:
            business_model = "Oil_Gas"
        elif "utility" in industry_lower or "utilities" in industry_lower:
            business_model = "Utilities"

    # Build classification
    if business_model:
        classification = f"{sector}/{business_model}"
    else:
        classification = sector

    logger.debug(
        "Classified company",
        gics_sector=gics_sector,
        industry=industry,
        classification=classification,
    )

    return classification


def get_sector_from_classification(classification: str) -> str:
    """Extract just the sector from a classification.

    Args:
        classification: Full classification like "Technology/SaaS".

    Returns:
        Just the sector like "Technology".
    """
    if "/" in classification:
        return classification.split("/")[0]
    return classification


def get_business_model_from_classification(classification: str) -> str | None:
    """Extract the business model from a classification.

    Args:
        classification: Full classification like "Technology/SaaS".

    Returns:
        Business model like "SaaS" or None if not present.
    """
    if "/" in classification:
        return classification.split("/")[1]
    return None
