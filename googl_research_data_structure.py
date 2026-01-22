#!/usr/bin/env python3
"""
Comprehensive GOOGL Equity Research Data Structure
This module defines the complete data structure for GOOGL financial research
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime

@dataclass
class CompanyProfile:
    """Company profile information"""
    symbol: str
    name: str
    sector: str
    industry: str
    description: str
    website: str
    ceo: str
    exchange: str
    market_cap: float
    employee_count: int
    country: str
    stock_price: float
    beta: float
    ipo_date: str

@dataclass
class IncomeStatementEntry:
    """Single period income statement"""
    date: str
    period: str
    revenue: float
    cost_of_revenue: float
    gross_profit: float
    gross_margin_percent: float
    operating_expenses: float
    operating_income: float
    operating_margin_percent: float
    ebitda: float
    net_income: float
    net_margin_percent: float
    eps: float

@dataclass
class BalanceSheet:
    """Balance sheet data"""
    date: str
    period: str
    current_assets: float
    total_assets: float
    current_liabilities: float
    total_liabilities: float
    total_equity: float
    cash_and_equivalents: float
    short_term_debt: float
    long_term_debt: float
    total_debt: float
    retained_earnings: float
    common_stock: float

@dataclass
class FinancialRatios:
    """Financial ratios"""
    date: str
    period: str
    pe_ratio: float
    price_to_sales: float
    price_to_book: float
    roe: float
    roa: float
    roic: float
    debt_to_equity: float
    debt_to_assets: float
    current_ratio: float
    quick_ratio: float
    cash_ratio: float
    asset_turnover: float
    receivables_turnover: float
    inventory_turnover: float

@dataclass
class KeyMetrics:
    """Key financial metrics"""
    date: str
    period: str
    enterprise_value: float
    ev_to_revenue: float
    ev_to_ebitda: float
    free_cash_flow: float
    fcf_per_share: float
    book_value_per_share: float
    dividend_per_share: float
    net_income_per_share: float
    revenue_per_share: float
    shares_outstanding: float
    market_cap: float

@dataclass
class AnalystEstimate:
    """Analyst estimate entry"""
    date: str
    period: str
    estimated_revenue_low: float
    estimated_revenue_high: float
    estimated_revenue_avg: float
    estimated_eps_low: float
    estimated_eps_high: float
    estimated_eps_avg: float
    number_of_estimates: int

@dataclass
class BusinessSegment:
    """Business segment information"""
    segment: str
    revenue: float
    revenue_ratio: float

@dataclass
class ResearchPackage:
    """Complete research package for equity analysis"""
    metadata: Dict[str, Any]
    company_profile: CompanyProfile
    income_statement: List[IncomeStatementEntry]
    balance_sheet: BalanceSheet
    financial_ratios: FinancialRatios
    key_metrics: KeyMetrics
    analyst_estimates: List[AnalystEstimate]
    business_segments: List[BusinessSegment]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'metadata': self.metadata,
            'company_profile': asdict(self.company_profile) if self.company_profile else None,
            'income_statement': [asdict(item) for item in self.income_statement] if self.income_statement else [],
            'balance_sheet': asdict(self.balance_sheet) if self.balance_sheet else None,
            'financial_ratios': asdict(self.financial_ratios) if self.financial_ratios else None,
            'key_metrics': asdict(self.key_metrics) if self.key_metrics else None,
            'analyst_estimates': [asdict(item) for item in self.analyst_estimates] if self.analyst_estimates else [],
            'business_segments': [asdict(item) for item in self.business_segments] if self.business_segments else []
        }

    def calculate_valuation_metrics(self) -> Dict[str, Any]:
        """Calculate key valuation metrics for analysis"""
        metrics = {}

        if self.key_metrics and self.financial_ratios:
            # Price-to-Earnings multiple
            if self.financial_ratios.pe_ratio:
                metrics['pe_ratio'] = self.financial_ratios.pe_ratio

            # EV/EBITDA multiple
            if self.key_metrics.ev_to_ebitda:
                metrics['ev_to_ebitda'] = self.key_metrics.ev_to_ebitda

            # Price-to-Sales
            if self.financial_ratios.price_to_sales:
                metrics['price_to_sales'] = self.financial_ratios.price_to_sales

            # Price-to-Book
            if self.financial_ratios.price_to_book:
                metrics['price_to_book'] = self.financial_ratios.price_to_book

            # Enterprise Value metrics
            if self.key_metrics.ev_to_revenue:
                metrics['ev_to_revenue'] = self.key_metrics.ev_to_revenue

        return metrics

    def calculate_profitability_metrics(self) -> Dict[str, Any]:
        """Calculate profitability metrics"""
        metrics = {}

        if self.financial_ratios:
            metrics['roe'] = self.financial_ratios.roe
            metrics['roa'] = self.financial_ratios.roa
            metrics['roic'] = self.financial_ratios.roic

        if self.income_statement:
            latest = self.income_statement[0]
            if latest.gross_margin_percent:
                metrics['gross_margin'] = latest.gross_margin_percent
            if latest.operating_margin_percent:
                metrics['operating_margin'] = latest.operating_margin_percent
            if latest.net_margin_percent:
                metrics['net_margin'] = latest.net_margin_percent

        return metrics

    def calculate_financial_health_metrics(self) -> Dict[str, Any]:
        """Calculate financial health metrics"""
        metrics = {}

        if self.balance_sheet:
            metrics['total_assets'] = self.balance_sheet.total_assets
            metrics['total_debt'] = self.balance_sheet.total_debt
            metrics['cash'] = self.balance_sheet.cash_and_equivalents
            metrics['net_debt'] = self.balance_sheet.total_debt - self.balance_sheet.cash_and_equivalents

        if self.financial_ratios:
            metrics['current_ratio'] = self.financial_ratios.current_ratio
            metrics['debt_to_equity'] = self.financial_ratios.debt_to_equity
            metrics['debt_to_assets'] = self.financial_ratios.debt_to_assets

        return metrics

    def calculate_growth_metrics(self) -> Dict[str, Any]:
        """Calculate growth metrics from historical data"""
        metrics = {}

        if len(self.income_statement) >= 2:
            # Revenue growth year-over-year
            latest_revenue = self.income_statement[0].revenue
            prior_revenue = self.income_statement[1].revenue

            if prior_revenue:
                yoy_growth = ((latest_revenue - prior_revenue) / prior_revenue) * 100
                metrics['revenue_growth_yoy_percent'] = yoy_growth

            # EPS growth
            latest_eps = self.income_statement[0].eps
            prior_eps = self.income_statement[1].eps

            if prior_eps and prior_eps != 0:
                eps_growth = ((latest_eps - prior_eps) / abs(prior_eps)) * 100
                metrics['eps_growth_yoy_percent'] = eps_growth

        return metrics

    def get_segment_breakdown(self) -> Dict[str, float]:
        """Get segment revenue breakdown as percentages"""
        breakdown = {}
        total_revenue = sum(segment.revenue for segment in self.business_segments) if self.business_segments else 0

        if total_revenue > 0:
            for segment in self.business_segments:
                percentage = (segment.revenue / total_revenue) * 100
                breakdown[segment.segment] = {
                    'revenue': segment.revenue,
                    'percentage': percentage
                }

        return breakdown
