"""Sector-aware company classification, ratio selection and peer benchmarking.

Only ratios that can be reproduced from the connected statement fields are calculated.
Regulatory/operating KPIs that require dedicated filings remain explicitly unavailable.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class SectorProfile:
    key: str
    label: str
    industry: str
    business_model: str
    classification_source: str
    confidence: str
    metrics: tuple[str, ...]
    peer_metrics: tuple[str, ...]
    peers: tuple[str, ...]
    peer_note: str
    unavailable_metrics: tuple[str, ...] = ()


# Seeded issuer mapping is a classification aid, not a claim that every issuer is identical.
TICKER_SECTOR = {
    # Cement
    **{x: "cement" for x in ("ULTRACEMCO", "SHREECEM", "AMBUJACEM", "DALBHARAT", "JKCEMENT", "RAMCOCEM", "JKLAKSHMI", "BIRLACORPN", "NUVOCO")},
    # Banks
    **{x: "banking" for x in ("HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK", "BANKBARODA", "CANBK", "PNB", "FEDERALBNK", "IDFCFIRSTB", "AUBANK")},
    # Infrastructure finance NBFC
    **{x: "nbfc_infra" for x in ("IRFC", "RECLTD", "PFC", "HUDCO", "IREDA")},
    # Consumer / diversified lending NBFC
    **{x: "nbfc_lending" for x in ("BAJFINANCE", "SHRIRAMFIN", "CHOLAFIN", "M&MFIN", "LTF", "MUTHOOTFIN", "MANAPPURAM", "POONAWALLA", "SBFC")},
    # IT services
    **{x: "it_services" for x in ("TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "MPHASIS", "PERSISTENT", "COFORGE")},
    # Automobiles / OEMs
    **{x: "automobile" for x in ("MARUTI", "M&M", "TATAMOTORS", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR", "BAJAJ-AUTO", "ASHOKLEY", "BOSCHLTD")},
    # FMCG / consumer goods
    **{x: "fmcg" for x in ("HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "GODREJCP", "MARICO", "COLPAL", "TATACONSUM", "VBL")},
    # Pharma
    **{x: "pharma" for x in ("SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "TORNTPHARM", "AUROPHARMA", "ZYDUSLIFE", "BIOCON")},
    # Real estate
    **{x: "real_estate" for x in ("DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "BRIGADE", "SOBHA", "PHOENIXLTD", "LODHA")},
    # Insurance sub-models
    **{x: "insurance_life" for x in ("HDFCLIFE", "SBILIFE", "ICICIPRULI")},
    **{x: "insurance_general" for x in ("ICICIGI", "GICRE")},
    **{x: "insurance_health" for x in ("STARHEALTH")},
    # Capital-market sub-models
    "CDSL": "depository",
    **{x: "exchange" for x in ("BSE", "MCX")},
    **{x: "brokerage" for x in ("ANGELONE", "MOTILALOFS", "360ONE", "IIFLSEC", "5PAISA")},
    **{x: "registrar" for x in ("CAMS", "KFINTECH")},
    # Oil and gas value-chain sub-models
    **{x: "oil_upstream" for x in ("ONGC", "OIL")},
    **{x: "oil_downstream" for x in ("IOC", "BPCL", "HINDPETRO")},
    **{x: "gas_distribution" for x in ("GAIL", "PETRONET", "MGL", "IGL")},
    # Utilities / power
    **{x: "utilities" for x in ("NTPC", "POWERGRID", "TATAPOWER", "NHPC", "ADANIGREEN", "JSWENERGY", "TORNTPOWER", "CESC")},
    # Steel and metals
    **{x: "metals" for x in ("TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "HINDZINC", "SAIL", "NATIONALUM")},
    # Oil, gas and energy value chain
    "RELIANCE": "generic",
    # Telecom
    **{x: "telecom" for x in ("BHARTIARTL", "IDEA", "INDUSTOWER")},
    # Logistics and transport
    **{x: "logistics" for x in ("DELHIVERY", "CONCOR", "BLUEDART", "TCI", "VRLLOG", "GATEWAY")},
    # Quick service restaurants / food service
    **{x: "qsr" for x in ("JUBLFOOD", "DEVYANI", "SAPPHIRE", "WESTLIFE", "BIKAJI", "HATSUN")},
    # Consumer durables / electrical equipment
    **{x: "consumer_durables" for x in ("HAVELLS", "DIXON", "VOLTAS", "CROMPTON", "BLUESTARCO", "WHIRLPOOL", "VGUARD")},
    # Chemicals
    **{x: "chemicals" for x in ("SRF", "PIIND", "DEEPAKNTR", "AARTIIND", "NAVINFLUOR", "ATUL", "TATACHEM", "FINEORG")},
    # EPC / infrastructure
    **{x: "epc" for x in ("LT", "KEC", "KALPATPOWR", "NCC", "PNCINFRA", "KNRCON", "RVNL", "IRCON", "NBCC")},
}

PEERS = {
    "cement": ("SHREECEM.NS", "AMBUJACEM.NS", "DALBHARAT.NS", "JKCEMENT.NS", "RAMCOCEM.NS"),
    "banking": ("ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "INDUSINDBK.NS"),
    "nbfc_infra": ("RECLTD.NS", "PFC.NS", "HUDCO.NS", "IREDA.NS"),
    "nbfc_lending": ("BAJFINANCE.NS", "SHRIRAMFIN.NS", "CHOLAFIN.NS", "M&MFIN.NS", "MUTHOOTFIN.NS"),
    "it_services": ("INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "LTIM.NS"),
    "automobile": ("MARUTI.NS", "M&M.NS", "TATAMOTORS.NS", "EICHERMOT.NS", "HEROMOTOCO.NS"),
    "fmcg": ("HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS"),
    "pharma": ("SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "LUPIN.NS"),
    "real_estate": ("DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS", "PRESTIGE.NS", "BRIGADE.NS"),
    "insurance": (),
    "capital_markets": (),
    "insurance_life": ("SBILIFE.NS", "ICICIPRULI.NS"),
    "insurance_general": ("ICICIGI.NS", "GICRE.NS"),
    "insurance_health": (),
    "depository": (),
    "exchange": ("BSE.NS", "MCX.NS"),
    "brokerage": ("ANGELONE.NS", "MOTILALOFS.NS", "IIFLSEC.NS", "5PAISA.NS"),
    "registrar": ("CAMS.NS", "KFINTECH.NS"),
    "oil_upstream": ("OIL.NS", "ONGC.NS"),
    "oil_downstream": ("IOC.NS", "BPCL.NS", "HINDPETRO.NS"),
    "gas_distribution": ("GAIL.NS", "MGL.NS", "IGL.NS"),
    "utilities": ("NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS", "NHPC.NS", "JSWENERGY.NS"),
    "epc": ("LT.NS", "KEC.NS", "KALPATPOWR.NS", "NCC.NS", "PNCINFRA.NS"),
    "metals": ("TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "JINDALSTEL.NS"),
    "oil_gas": ("ONGC.NS", "OIL.NS", "IOC.NS", "BPCL.NS", "HINDPETRO.NS", "GAIL.NS"),
    "telecom": ("BHARTIARTL.NS", "IDEA.NS", "INDUSTOWER.NS"),
    "logistics": ("DELHIVERY.NS", "CONCOR.NS", "BLUEDART.NS", "TCI.NS", "VRLLOG.NS"),
    "qsr": ("JUBLFOOD.NS", "DEVYANI.NS", "SAPPHIRE.NS", "WESTLIFE.NS"),
    "consumer_durables": ("HAVELLS.NS", "DIXON.NS", "VOLTAS.NS", "CROMPTON.NS", "BLUESTARCO.NS"),
    "chemicals": ("SRF.NS", "PIIND.NS", "DEEPAKNTR.NS", "AARTIIND.NS", "NAVINFLUOR.NS"),
}

RATIO_LIBRARY: dict[str, dict[str, str]] = {
    "revenue_growth": {
        "label": "Revenue growth", "unit": "%", "formula": "(Current-year revenue / Previous-year revenue − 1) × 100",
        "definition": "Year-on-year change in reported revenue.", "interpretation": "Read growth alongside margins, cash generation and the company's business cycle.",
        "inputs": "Total Revenue; previous-year Total Revenue", "caveat": "A growth rate is not meaningful if the prior-year base is zero or missing.",
    },
    "pat_growth": {
        "label": "PAT growth", "unit": "%", "formula": "(Current-year PAT / Previous-year PAT − 1) × 100",
        "definition": "Year-on-year change in profit after tax.", "interpretation": "Check whether profit growth is supported by revenue, margins and operating cash generation.",
        "inputs": "Net Income / Net Income Common Stockholders; previous-year PAT", "caveat": "Not calculated when either period's PAT is zero or negative.",
    },
    "asset_growth": {
        "label": "Total assets growth", "unit": "%", "formula": "(Current-year total assets / Previous-year total assets − 1) × 100",
        "definition": "Year-on-year growth in the reported asset base.", "interpretation": "For lenders, assess whether asset growth is supported by capital and funding; for industrial businesses, compare with sales and returns.",
        "inputs": "Total Assets; previous-year Total Assets", "caveat": "Balance-sheet perimeter and reporting basis must remain consistent.",
    },
    "gross_margin": {
        "label": "Gross margin", "unit": "%", "formula": "(Revenue − Cost of Revenue) / Revenue × 100",
        "definition": "Revenue remaining after reported direct cost of revenue.", "interpretation": "Changes can reflect pricing, product mix, input costs or accounting classification.",
        "inputs": "Total Revenue; Cost Of Revenue", "caveat": "Provider classification of cost of revenue may differ by industry.",
    },
    "ebitda_margin": {
        "label": "EBITDA margin", "unit": "%", "formula": "Reported EBITDA / Total Revenue × 100",
        "definition": "Reported EBITDA as a percentage of revenue.", "interpretation": "Compare with the company's own history and closely matched peers; business mix matters.",
        "inputs": "EBITDA; Total Revenue", "caveat": "Provider EBITDA may be calculated or reported; check the source statement before using it in a model.",
    },
    "ebit_margin": {
        "label": "EBIT margin", "unit": "%", "formula": "(EBITDA − Depreciation and amortisation) / Revenue × 100",
        "definition": "Operating earnings after depreciation, before interest and tax, relative to revenue.", "interpretation": "Useful for comparing operating profitability where depreciation is consistently reported.",
        "inputs": "EBITDA; Reconciled Depreciation or Cash Flow Depreciation; Total Revenue", "caveat": "Not calculated if depreciation is unavailable; zero is not assumed.",
    },
    "pat_margin": {
        "label": "PAT margin", "unit": "%", "formula": "Profit after tax / Total Revenue × 100",
        "definition": "Share of reported revenue retained as profit after tax.", "interpretation": "Review alongside one-off items, funding costs and operating margins.",
        "inputs": "Net Income; Total Revenue", "caveat": "Reported revenue definitions can differ for financial institutions.",
    },
    "roa": {
        "label": "Return on average assets (ROA)", "unit": "%", "formula": "PAT / Average total assets × 100",
        "definition": "Profit generated relative to the average asset base.", "interpretation": "For banks and NBFCs, ROA is a key profitability indicator; compare within the same type of institution.",
        "inputs": "PAT; opening and closing Total Assets", "caveat": "Requires opening and closing balances for the period.",
    },
    "roe": {
        "label": "Return on average equity (ROE)", "unit": "%", "formula": "PAT / Average shareholders' equity × 100",
        "definition": "Profit generated relative to average shareholders' funds.", "interpretation": "A rising ROE can be driven by better profitability or higher leverage; review both.",
        "inputs": "PAT; opening and closing Stockholders Equity", "caveat": "Requires positive average equity and consistent consolidated/standalone basis.",
    },
    "roce": {
        "label": "Return on capital employed (ROCE)", "unit": "%", "formula": "EBIT / Average capital employed × 100; capital employed = total assets − current liabilities",
        "definition": "Operating return earned on capital invested in the business.", "interpretation": "Compare with the company's cost of capital and peers with similar asset intensity.",
        "inputs": "EBIT; opening/closing Total Assets; opening/closing Current Liabilities", "caveat": "Uses a balance-sheet definition of capital employed; missing depreciation or current liabilities makes it unavailable.",
    },
    "debt_equity": {
        "label": "Borrowings / Equity", "unit": "x", "formula": "Reported total debt / Shareholders' equity",
        "definition": "Reported interest-bearing borrowings relative to book equity.", "interpretation": "For non-financial companies this is a leverage measure; for lenders it is a funding-structure metric and is not directly comparable with industrial companies.",
        "inputs": "Total Debt; Stockholders Equity", "caveat": "Only calculated when total debt is actually reported; missing debt is not interpreted as zero.",
    },
    "net_debt_ebitda": {
        "label": "Net debt / EBITDA", "unit": "x", "formula": "(Reported total debt − Cash and short-term investments) / EBITDA",
        "definition": "Net borrowings relative to operating earnings.", "interpretation": "A lower multiple generally indicates less balance-sheet leverage, but sector and cash-flow stability matter.",
        "inputs": "Total Debt; Cash and Cash Equivalents; EBITDA", "caveat": "Not meaningful for banks and many financial institutions; not calculated where cash/debt/EBITDA inputs are missing.",
    },
    "interest_coverage": {
        "label": "Interest coverage", "unit": "x", "formula": "EBIT / Interest expense",
        "definition": "Operating earnings available to cover interest expense.", "interpretation": "A declining ratio reduces the earnings cushion available to service debt.",
        "inputs": "EBITDA; Depreciation; Interest Expense", "caveat": "Not suitable as a primary ratio for banks; not calculated if interest expense is unavailable or zero.",
    },
    "sloan_accruals": {
        "label": "Sloan accrual ratio", "unit": "%",
        "formula": "(PAT − Operating cash flow) / Average total assets × 100",
        "definition": "Measures the portion of reported earnings represented by accruals rather than operating cash flow.",
        "interpretation": "A persistently higher positive accrual ratio can indicate weaker cash backing for earnings and deserves investigation; it is not proof of manipulation.",
        "inputs": "PAT; Operating Cash Flow; opening and closing Total Assets",
        "caveat": "Used as an earnings-quality screen for non-financial businesses; not compared across banks/NBFCs."
    },
    "cfo_pat": {
        "label": "Operating cash flow / PAT", "unit": "x", "formula": "Cash flow from operations / Profit after tax",
        "definition": "Compares cash generated by operations with accounting profit.", "interpretation": "For non-financial businesses, persistent weak conversion deserves working-capital and earnings-quality review.",
        "inputs": "Operating Cash Flow; PAT", "caveat": "Operating cash flow for banks and lenders is affected by loan/deposit flows and is not comparable to industrial CFO/PAT.",
    },
    "dso": {
        "label": "Receivable days (sales proxy)", "unit": "days", "formula": "Average trade receivables / Total revenue × 365",
        "definition": "Approximate days of revenue represented by trade receivables.", "interpretation": "An increase may indicate slower collections, a shift in customer terms or a change in revenue mix.",
        "inputs": "Opening/closing Accounts Receivable; Total Revenue", "caveat": "Revenue is used as a proxy because credit sales are not separated in the connected statement feed.",
    },
    "dio": {
        "label": "Inventory days (COGS proxy)", "unit": "days", "formula": "Average inventory / Cost of revenue × 365",
        "definition": "Approximate time inventory remains in the business.", "interpretation": "Rising days can reflect stock build-up, lower demand, supply planning or a deliberate capacity buffer.",
        "inputs": "Opening/closing Inventory; Cost Of Revenue", "caveat": "Cost of revenue is used as a purchases/COGS proxy; exclude for lenders and service businesses without meaningful inventory.",
    },
    "dpo": {
        "label": "Payable days (COGS proxy)", "unit": "days", "formula": "Average trade payables / Cost of revenue × 365",
        "definition": "Approximate time taken to pay suppliers.", "interpretation": "Longer days may support cash flow, but can also signal supplier-payment pressure.",
        "inputs": "Opening/closing Accounts Payable; Cost Of Revenue", "caveat": "Cost of revenue is a proxy for purchases where purchases are not separately reported.",
    },
    "ccc": {
        "label": "Cash conversion cycle (CCC)", "unit": "days", "formula": "Receivable days + Inventory days − Payable days",
        "definition": "Approximate number of days cash is tied up in the operating cycle.", "interpretation": "A shorter cycle often releases working capital; business model and negative-cycle models must be considered.",
        "inputs": "DSO; DIO; DPO", "caveat": "Only displayed when all three components can be calculated.",
    },
    "asset_turnover": {
        "label": "Asset turnover", "unit": "x", "formula": "Revenue / Average total assets",
        "definition": "Revenue generated per rupee of average assets.", "interpretation": "Compare businesses with similar asset intensity and accounting treatment.",
        "inputs": "Total Revenue; opening and closing Total Assets", "caveat": "Requires opening and closing asset balances.",
    },
    "cost_of_borrowings_proxy": {
        "label": "Interest cost / average borrowings (proxy)", "unit": "%", "formula": "Interest expense / Average reported total debt × 100",
        "definition": "An approximate interest cost on the reported borrowing base.", "interpretation": "A rising proxy can indicate more expensive funding, a change in borrowing mix or timing effects.",
        "inputs": "Interest Expense; opening and closing Total Debt", "caveat": "This is not regulatory cost of funds; it excludes non-interest funding and timing/fee adjustments.",
    },
    "capex_revenue": {
        "label": "Capital expenditure / Revenue", "unit": "%", "formula": "Capital expenditure / Total Revenue × 100",
        "definition": "Capital investment as a share of revenue.", "interpretation": "Assess whether the investment cycle is supporting profitable growth and whether cash flows can fund it.",
        "inputs": "Capital Expenditure; Total Revenue", "caveat": "Not calculated if capex is absent; missing capex is not treated as zero.",
    },
}

# Each item is shown only for sectors where it is analytically relevant.
SECTOR_CONFIG = {
    "cement": dict(label="Cement & Building Materials", industry="Materials", business_model="Cement manufacturing",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","cfo_pat","sloan_accruals","dso","dio","dpo","ccc","capex_revenue","ebitda_per_tonne","capacity_utilisation"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","cfo_pat"),
        peers=PEERS["cement"], peer_note="Cement manufacturers; integrated and grinding-heavy business mixes can differ.",
        unavailable={"ebitda_per_tonne":"Requires cement volume (tonnes) and EBITDA from the same reporting period; not present in normalized statements.","capacity_utilisation":"Requires disclosed installed capacity and actual production; not present in normalized statements."}),
    "banking": dict(label="Banking", industry="Banks", business_model="Banking",
        metrics=("revenue_growth","pat_growth","roa","roe","nim","gnpa","nnpa","casa","crar","credit_cost","cost_to_income","asset_growth"),
        peer_metrics=("roa","roe","pat_growth","asset_growth"),
        peers=PEERS["banking"], peer_note="Listed banks; compare similar reporting periods and business mix. Public statement-feed ratios are limited.",
        unavailable={"nim":"Requires interest income, interest expense and average earning assets from bank disclosures.","gnpa":"Requires reported gross non-performing advances from regulatory/quarterly bank filings.","nnpa":"Requires reported net non-performing advances and provisions from bank filings.","casa":"Requires CASA deposits and total deposits from bank disclosures.","crar":"Requires regulatory capital and risk-weighted assets from bank disclosures.","credit_cost":"Requires loan-loss/provision expense and average advances; not in the standardized statement feed.","cost_to_income":"Requires operating expenses and operating income on a consistent bank definition."}),
    "nbfc_infra": dict(label="Infrastructure Finance NBFC", industry="Financial Services", business_model="Infrastructure finance / lending NBFC",
        metrics=("revenue_growth","pat_growth","roa","roe","debt_equity","cost_of_borrowings_proxy","asset_growth","nim","gnpa","nnpa","crar","alm_gaps"),
        peer_metrics=("roa","roe","debt_equity","cost_of_borrowings_proxy","pat_growth"),
        peers=PEERS["nbfc_infra"], peer_note="Infrastructure-focused public finance institutions; mandates, asset mix and funding structures differ.",
        unavailable={"nim":"Requires interest income/expense and average earning assets from NBFC disclosures.","gnpa":"Requires gross NPA/standard-asset classification from RBI/issuer filings.","nnpa":"Requires net NPA and provisioning disclosures.","crar":"Requires regulatory capital and risk-weighted assets.","alm_gaps":"Requires asset-liability maturity buckets from NBFC disclosures."}),
    "nbfc_lending": dict(label="Lending NBFC", industry="Financial Services", business_model="Lending / consumer or diversified NBFC",
        metrics=("revenue_growth","pat_growth","roa","roe","debt_equity","cost_of_borrowings_proxy","nim","gnpa","nnpa","credit_cost","crar","asset_growth"),
        peer_metrics=("roa","roe","debt_equity","cost_of_borrowings_proxy","pat_growth"),
        peers=PEERS["nbfc_lending"], peer_note="Lending NBFCs; customer mix, secured/unsecured exposure and product mix should be reviewed.",
        unavailable={"nim":"Requires interest income/expense and average earning assets.","gnpa":"Requires gross NPA disclosure from issuer/RBI filing.","nnpa":"Requires net NPA and provisioning disclosure.","credit_cost":"Requires credit impairment/provision charge and average loan book.","crar":"Requires regulatory capital and risk-weighted assets."}),
    "it_services": dict(label="IT Services", industry="Information Technology", business_model="IT services and software",
        metrics=("revenue_growth","ebitda_margin","ebit_margin","pat_margin","roce","roe","cfo_pat","sloan_accruals","dso","employee_cost_revenue","utilisation","attrition"),
        peer_metrics=("revenue_growth","ebit_margin","roce","cfo_pat"),
        peers=PEERS["it_services"], peer_note="IT services peers; geography, service mix, acquisitions and currency exposure affect comparability.",
        unavailable={"employee_cost_revenue":"Requires employee/staff cost separately disclosed in the same reporting period.","utilisation":"Requires reported billable utilisation; not present in standardized statements.","attrition":"Requires reported employee attrition disclosure."}),
    "automobile": dict(label="Automobiles & Auto Components", industry="Consumer Discretionary", business_model="Automotive manufacturing",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","cfo_pat","sloan_accruals","dio","asset_turnover","volume_growth","average_realisation"),
        peer_metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda"),
        peers=PEERS["automobile"], peer_note="Automotive OEMs; two-wheelers, passenger vehicles and commercial vehicles have different cycles and margins.",
        unavailable={"volume_growth":"Requires reported vehicle/unit volumes by segment.","average_realisation":"Requires revenue and matched unit volumes/segment mix."}),
    "fmcg": dict(label="FMCG & Consumer Staples", industry="Consumer Staples", business_model="Branded consumer products",
        metrics=("revenue_growth","gross_margin","ebitda_margin","roce","dso","dio","dpo","ccc","cfo_pat","sloan_accruals","capex_revenue"),
        peer_metrics=("gross_margin","ebitda_margin","roce","ccc"),
        peers=PEERS["fmcg"], peer_note="Consumer staples peers; product mix, distribution and commodity exposure affect margins.",
        unavailable={}),
    "pharma": dict(label="Pharmaceuticals & Healthcare", industry="Healthcare", business_model="Pharmaceutical products",
        metrics=("revenue_growth","ebitda_margin","roce","roe","cfo_pat","sloan_accruals","dso","net_debt_ebitda","rnd_revenue","export_mix"),
        peer_metrics=("revenue_growth","ebitda_margin","roce","cfo_pat"),
        peers=PEERS["pharma"], peer_note="Pharma peers; branded/generics, domestic/export mix and product concentration differ.",
        unavailable={"rnd_revenue":"Requires R&D expense line disclosed separately.","export_mix":"Requires export revenue or geographic revenue split."}),
    "real_estate": dict(label="Real Estate & Developers", industry="Real Estate", business_model="Real estate development",
        metrics=("revenue_growth","ebitda_margin","roce","debt_equity","net_debt_ebitda","cfo_pat","sloan_accruals","inventory_days","presales_growth","collections_ratio"),
        peer_metrics=("ebitda_margin","roce","debt_equity","cfo_pat"),
        peers=PEERS["real_estate"], peer_note="Listed developers; project stage, land bank, joint ventures and revenue recognition vary.",
        unavailable={"inventory_days":"Requires project-level inventory/WIP classification; a single balance-sheet inventory figure may not be comparable.","presales_growth":"Requires disclosed pre-sales/bookings by period.","collections_ratio":"Requires collections and pre-sales/contracted sales disclosures."}),
    "insurance": dict(label="Insurance", industry="Financial Services", business_model="Life or general insurance",
        metrics=("roe","pat_growth","solvency_ratio","vnb_margin","persistency","combined_ratio","claims_ratio"),
        peer_metrics=("roe","pat_growth"),
        peers=PEERS["insurance"], peer_note="Life and general insurers are not direct peers; peer list must be narrowed to the same insurance category.",
        unavailable={"solvency_ratio":"Requires insurer regulatory solvency margin and required solvency margin disclosures.","vnb_margin":"Requires value of new business and APE from life-insurance disclosures.","persistency":"Requires policy persistency disclosures by cohort.","combined_ratio":"Requires incurred claims plus expenses divided by earned premium; relevant to general insurers.","claims_ratio":"Requires claims and premium disclosures."}),
    "capital_markets": dict(label="Capital Markets & Market Infrastructure", industry="Financial Services", business_model="Exchange, depository, broker or market infrastructure",
        metrics=("revenue_growth","pat_growth","ebitda_margin","pat_margin","roe","roa","asset_turnover","cfo_pat","sloan_accruals"),
        peer_metrics=("revenue_growth","ebitda_margin","roe","pat_growth"),
        peers=PEERS["capital_markets"], peer_note="Market infrastructure and brokerage peers; exchange, depository and broker economics are not identical.",
        unavailable={}),
    "utilities": dict(label="Power & Utilities", industry="Utilities", business_model="Power generation, transmission or utility",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","capex_revenue"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
        peers=PEERS["utilities"], peer_note="Power and utility peers; generation, transmission and renewable asset profiles differ.",
        unavailable={}),
    "epc": dict(label="EPC & Infrastructure", industry="Industrials", business_model="Engineering, procurement, construction or infrastructure execution",
        metrics=("revenue_growth","ebitda_margin","roce","debt_equity","cfo_pat","sloan_accruals","dso","orderbook_revenue","contract_assets"),
        peer_metrics=("revenue_growth","ebitda_margin","roce","debt_equity","cfo_pat"),
        peers=PEERS["epc"], peer_note="EPC/infrastructure peers; project mix, working-capital terms and execution stages differ.",
        unavailable={"orderbook_revenue":"Requires the latest disclosed executable order book and annual revenue.","contract_assets":"Requires contract asset/unbilled revenue disclosure; not consistently exposed in standardized statements."}),
    "metals": dict(label="Steel & Metals", industry="Materials", business_model="Steel, aluminium or diversified metals producer",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","dso","dio","capex_revenue","production_growth"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
        peers=PEERS["metals"], peer_note="Metals peers; product mix, captive raw materials, energy exposure and cycle position materially affect comparability.",
        unavailable={"production_growth":"Requires reported production/sales volumes by metal or product; not present in standardized statements."}),
    "oil_gas": dict(label="Oil, Gas & Energy", industry="Energy", business_model="Upstream, refining, marketing, gas or integrated energy",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","capex_revenue","production_growth","realisation_per_unit"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
        peers=PEERS["oil_gas"], peer_note="A broad oil-and-gas label does not define a comparable business model. No automatic peers are assigned until upstream, downstream, gas transmission or integrated exposure is identified.",
        unavailable={"production_growth":"Requires reported production/throughput volumes.","realisation_per_unit":"Requires matched commodity realisation and production/sales volume."}),
    "telecom": dict(label="Telecommunications", industry="Communication Services", business_model="Telecom services or tower infrastructure",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","cfo_pat","sloan_accruals","subscriber_growth","arpu","capex_revenue"),
        peer_metrics=("revenue_growth","ebitda_margin","net_debt_ebitda","cfo_pat"),
        peers=PEERS["telecom"], peer_note="Telecom operators and tower infrastructure companies have different revenue and leverage models; do not compare across those models without adjustment.",
        unavailable={"subscriber_growth":"Requires active subscriber/customer data by period.","arpu":"Requires reported average revenue per user.","capex_revenue":"Requires reported capex; shown only when the capital-expenditure statement line is available."}),
    "logistics": dict(label="Logistics & Transportation", industry="Industrials", business_model="Logistics, freight, transport or warehousing",
        metrics=("revenue_growth","ebitda_margin","roce","asset_turnover","debt_equity","cfo_pat","sloan_accruals","dso","capex_revenue","volume_growth"),
        peer_metrics=("revenue_growth","ebitda_margin","roce","asset_turnover"),
        peers=PEERS["logistics"], peer_note="Logistics peers differ by asset ownership, express/contract logistics, freight and warehousing mix.",
        unavailable={"volume_growth":"Requires shipment, tonnage, container or parcel volumes by period."}),
    "qsr": dict(label="Quick Service Restaurants & Food Service", industry="Consumer Discretionary", business_model="Restaurant chain / food service",
        metrics=("revenue_growth","gross_margin","ebitda_margin","roce","debt_equity","cfo_pat","sloan_accruals","inventory_days","same_store_sales_growth","store_growth"),
        peer_metrics=("revenue_growth","ebitda_margin","roce","cfo_pat"),
        peers=PEERS["qsr"], peer_note="Restaurant peers; store maturity, franchise mix, geography and format affect comparability.",
        unavailable={"inventory_days":"Requires food/operating inventory consistently separated from other current assets.","same_store_sales_growth":"Requires company-reported same-store sales growth.","store_growth":"Requires comparable operating store counts."}),
    "consumer_durables": dict(label="Consumer Durables & Electricals", industry="Consumer Discretionary", business_model="Consumer durables, electronics or electrical equipment",
        metrics=("revenue_growth","gross_margin","ebitda_margin","roce","debt_equity","cfo_pat","sloan_accruals","dso","dio","ccc","capex_revenue"),
        peer_metrics=("revenue_growth","gross_margin","ebitda_margin","roce"),
        peers=PEERS["consumer_durables"], peer_note="Consumer-durable peers; product category, manufacturing mix and distribution intensity differ.",
        unavailable={}),
    "chemicals": dict(label="Chemicals & Specialty Materials", industry="Materials", business_model="Commodity or specialty chemicals manufacturing",
        metrics=("revenue_growth","gross_margin","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","dso","dio","ccc","capex_revenue"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","cfo_pat"),
        peers=PEERS["chemicals"], peer_note="Chemical peers; product mix, export share, feedstock and specialty/commodity exposure affect comparability.",
        unavailable={}),
    "insurance_life": dict(label="Life Insurance", industry="Financial Services", business_model="Life insurance",
        metrics=("roe","pat_growth","solvency_ratio","vnb_margin","persistency","ape_growth"),
        peer_metrics=("roe","pat_growth"), peers=PEERS["insurance_life"],
        peer_note="Life insurers; product mix, distribution mix and embedded-value assumptions differ.",
        unavailable={"solvency_ratio":"Requires insurer regulatory solvency margin disclosures.","vnb_margin":"Requires value of new business and APE from life-insurance disclosures.","persistency":"Requires policy persistency disclosures by cohort.","ape_growth":"Requires annualised premium equivalent from insurer disclosures."}),
    "insurance_general": dict(label="General Insurance", industry="Financial Services", business_model="General insurance",
        metrics=("roe","pat_growth","solvency_ratio","combined_ratio","claims_ratio"),
        peer_metrics=("roe","pat_growth"), peers=PEERS["insurance_general"],
        peer_note="General insurers; product mix, reinsurance and claims experience affect comparability.",
        unavailable={"solvency_ratio":"Requires insurer regulatory solvency margin disclosures.","combined_ratio":"Requires incurred claims plus expenses divided by earned premium.","claims_ratio":"Requires claims and premium disclosures."}),
    "insurance_health": dict(label="Health Insurance", industry="Financial Services", business_model="Standalone health insurance",
        metrics=("roe","pat_growth","solvency_ratio","claims_ratio"),
        peer_metrics=("roe","pat_growth"), peers=PEERS["insurance_health"],
        peer_note="A standalone health insurer should not be benchmarked against life insurers; no robust listed peer set is assigned by default.",
        unavailable={"solvency_ratio":"Requires insurer regulatory solvency margin disclosures.","claims_ratio":"Requires claims and premium disclosures."}),
    "depository": dict(label="Depository / Market Infrastructure", industry="Financial Services", business_model="Securities depository",
        metrics=("revenue_growth","pat_growth","ebitda_margin","pat_margin","roe","roa","asset_turnover"),
        peer_metrics=(), peers=PEERS["depository"],
        peer_note="A direct listed depository peer is not available in the current curated peer set; no false peer median is shown.",
        unavailable={}),
    "exchange": dict(label="Financial Exchange", industry="Financial Services", business_model="Exchange operator",
        metrics=("revenue_growth","pat_growth","ebitda_margin","pat_margin","roe","roa","asset_turnover"),
        peer_metrics=("revenue_growth","ebitda_margin","roe","pat_growth"), peers=PEERS["exchange"],
        peer_note="Exchange operators; product mix and revenue from transaction, listing and data services differ.",
        unavailable={}),
    "brokerage": dict(label="Brokerage & Wealth Platforms", industry="Financial Services", business_model="Brokerage / wealth platform",
        metrics=("revenue_growth","pat_growth","ebitda_margin","pat_margin","roe","roa","cfo_pat","sloan_accruals"),
        peer_metrics=("revenue_growth","ebitda_margin","roe","pat_growth"), peers=PEERS["brokerage"],
        peer_note="Brokerage peers; active client mix, derivatives share, distribution and wealth mix differ.",
        unavailable={}),
    "registrar": dict(label="Registrar & Transfer Agency", industry="Financial Services", business_model="Registrar / mutual-fund transfer agency",
        metrics=("revenue_growth","pat_growth","ebitda_margin","pat_margin","roe","roa","asset_turnover"),
        peer_metrics=("revenue_growth","ebitda_margin","roe","pat_growth"), peers=PEERS["registrar"],
        peer_note="Registrar and transfer-agency peers; client mix and assets serviced differ.",
        unavailable={}),
    "oil_upstream": dict(label="Oil & Gas — Upstream", industry="Energy", business_model="Oil and gas exploration / production",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","capex_revenue","production_growth"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","interest_coverage"), peers=PEERS["oil_upstream"],
        peer_note="Upstream exploration and production peers; reserves, production mix and realisations affect results.",
        unavailable={"production_growth":"Requires reported oil/gas production volumes by period."}),
    "oil_downstream": dict(label="Oil & Gas — Refining / Marketing", industry="Energy", business_model="Refining and petroleum marketing",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","capex_revenue","throughput_growth"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","interest_coverage"), peers=PEERS["oil_downstream"],
        peer_note="Refining and marketing peers; refining margins, product mix and inventory gains/losses affect comparability.",
        unavailable={"throughput_growth":"Requires reported refinery throughput or sales volumes."}),
    "gas_distribution": dict(label="Gas Transmission & Distribution", industry="Energy", business_model="Gas transmission, distribution or regasification",
        metrics=("revenue_growth","ebitda_margin","roce","net_debt_ebitda","interest_coverage","cfo_pat","sloan_accruals","capex_revenue","volume_growth"),
        peer_metrics=("ebitda_margin","roce","net_debt_ebitda","interest_coverage"), peers=PEERS["gas_distribution"],
        peer_note="Gas transmission/distribution and regasification peers; regulated tariffs and infrastructure mix differ.",
        unavailable={"volume_growth":"Requires reported gas transmission/distribution volumes."}),
    "generic": dict(label="Unclassified / diversified", industry="Not verified", business_model="Business model not confidently classified",
        metrics=("revenue_growth","ebitda_margin","pat_margin","roa","roe","debt_equity","cfo_pat","sloan_accruals"),
        peer_metrics=(), peers=(), peer_note="No automated peer set is assigned until the business model is verified.",
        unavailable={}),
}

def _ticker_root(ticker: str) -> str:
    return str(ticker or "").upper().replace(".NS", "").replace(".BO", "").strip()


def classify_company(ticker: str, profile: dict[str, Any]) -> SectorProfile:
    root = _ticker_root(ticker)
    sector = str(profile.get("sector") or "").lower()
    industry = str(profile.get("industry") or "").lower()
    source = "Yahoo Finance sector/industry metadata"
    confidence = "Provider classification — analyst verification recommended"
    key = TICKER_SECTOR.get(root)
    if key:
        if key == "generic":
            source = "Diversified issuer mapping; segment disclosures are required to select a narrower business model"
            confidence = "Needs analyst review"
        else:
            source = "Curated issuer/ticker mapping; review against provider metadata"
            confidence = "High-confidence issuer mapping; confirm with latest annual report"
    else:
        text = f"{sector} {industry}"
        if any(x in text for x in ("bank", "commercial banks", "regional banks")):
            key = "banking"
        elif "life insurance" in text:
            key = "insurance_life"
        elif "health insurance" in text:
            key = "insurance_health"
        elif "general insurance" in text:
            key = "insurance_general"
        elif "insurance" in text:
            key = "insurance"
        elif "cement" in text:
            key = "cement"
        elif any(x in text for x in ("information technology services", "it services", "software—application", "software - application", "software— infrastructure", "software - infrastructure")):
            key = "it_services"
        elif any(x in text for x in ("credit services", "consumer finance", "mortgage finance", "non-bank financial", "nonbank financial")):
            key = "nbfc_lending"
        elif any(x in text for x in ("securities depository", "depository services")):
            key = "depository"
        elif any(x in text for x in ("stock exchange", "financial exchange", "commodity exchange")):
            key = "exchange"
        elif any(x in text for x in ("brokerage", "capital markets", "financial data", "asset management", "wealth management")):
            key = "brokerage"
        elif any(x in text for x in ("transfer agency", "registrar")):
            key = "registrar"
        elif any(x in text for x in ("automobiles", "auto manufacturers", "auto parts")):
            key = "automobile"
        elif any(x in text for x in ("personal products", "packaged foods", "household products", "beverages", "food products")):
            key = "fmcg"
        elif any(x in text for x in ("drug manufacturers", "biotechnology", "pharmaceutical")):
            key = "pharma"
        elif any(x in text for x in ("real estate", "realty")):
            key = "real_estate"
        elif any(x in text for x in ("utilities", "electric utilities", "renewable utilities")):
            key = "utilities"
        elif any(x in text for x in ("engineering & construction", "engineering and construction", "construction")):
            key = "epc"
        elif any(x in text for x in ("steel", "aluminium", "aluminum", "copper", "diversified metals", "metal products")):
            key = "metals"
        elif any(x in text for x in ("exploration & production", "oil & gas e&p", "oil and gas e&p", "upstream oil")):
            key = "oil_upstream"
        elif any(x in text for x in ("refining", "oil & gas refining", "oil and gas refining")):
            key = "oil_downstream"
        elif any(x in text for x in ("gas distribution", "gas transmission", "lng regasification")):
            key = "gas_distribution"
        elif any(x in text for x in ("oil & gas", "oil and gas", "integrated oil")):
            key = "oil_gas"
        elif any(x in text for x in ("telecom", "wireless telecommunications", "telecommunication services")):
            key = "telecom"
        elif any(x in text for x in ("logistics", "freight", "shipping", "transportation", "courier")):
            key = "logistics"
        elif any(x in text for x in ("restaurants", "quick service", "food service", "food retail")):
            key = "qsr"
        elif any(x in text for x in ("consumer durables", "household appliances", "electrical equipment", "consumer electronics")):
            key = "consumer_durables"
        elif any(x in text for x in ("chemicals", "specialty chemicals", "agrochemicals")):
            key = "chemicals"
        else:
            key = "generic"
            source = "Provider metadata insufficient for a sector-specific classification"
            confidence = "Needs analyst review"
    config = SECTOR_CONFIG.get(key, SECTOR_CONFIG["generic"])
    # IRFC/REC/PFC/HUDCO/IREDA are infrastructure-focused public finance entities.
    return SectorProfile(
        key=key, label=config["label"], industry=config["industry"],
        business_model=config["business_model"], classification_source=source,
        confidence=confidence, metrics=tuple(config["metrics"]), peer_metrics=tuple(config["peer_metrics"]),
        peers=tuple(config["peers"]), peer_note=config["peer_note"],
        unavailable_metrics=tuple(config.get("unavailable", {}).keys()),
    )


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _safe_div(numer: pd.Series, denom: pd.Series, multiplier: float = 1.0) -> pd.Series:
    numer = pd.to_numeric(numer, errors="coerce")
    denom = pd.to_numeric(denom, errors="coerce")
    valid = denom.notna() & (denom != 0) & numer.notna()
    out = pd.Series(np.nan, index=numer.index, dtype=float)
    out.loc[valid] = numer.loc[valid] / denom.loc[valid] * multiplier
    return out.replace([np.inf, -np.inf], np.nan)


def calculate_ratio_series(financials: pd.DataFrame) -> dict[str, pd.Series]:
    """Calculate reproducible metrics from missingness-preserving annual statements."""
    if financials is None or financials.empty:
        return {}
    d = financials.copy().sort_index()
    rev, pat = _num(d, "revenue"), _num(d, "pat")
    ebitda, dep = _num(d, "ebitda"), _num(d, "depreciation")
    assets, equity = _num(d, "total_assets"), _num(d, "net_worth")
    debt, cash = _num(d, "total_debt"), _num(d, "cash")
    cfo, cogs = _num(d, "cfo"), _num(d, "cogs")
    interest = _num(d, "interest")
    receivables, inventory, payables = _num(d, "receivables"), _num(d, "inventory"), _num(d, "payables")
    current_liab = _num(d, "current_liabilities")
    capex = _num(d, "capex")

    ebit = ebitda - dep
    avg_assets = (assets + assets.shift(1)) / 2
    avg_equity = (equity + equity.shift(1)) / 2
    capital_employed = assets - current_liab
    avg_capital_employed = (capital_employed + capital_employed.shift(1)) / 2
    avg_debt = (debt + debt.shift(1)) / 2
    avg_receivables = (receivables + receivables.shift(1)) / 2
    avg_inventory = (inventory + inventory.shift(1)) / 2
    avg_payables = (payables + payables.shift(1)) / 2

    result = {
        "revenue_growth": (rev / rev.shift(1) - 1) * 100,
        "pat_growth": (pat / pat.shift(1) - 1) * 100,
        "asset_growth": (assets / assets.shift(1) - 1) * 100,
        "gross_margin": _safe_div(rev - cogs, rev, 100),
        "ebitda_margin": _safe_div(ebitda, rev, 100),
        "ebit_margin": _safe_div(ebit, rev, 100),
        "pat_margin": _safe_div(pat, rev, 100),
        "roa": _safe_div(pat, avg_assets, 100).where(avg_assets > 0),
        "roe": _safe_div(pat, avg_equity, 100).where(avg_equity > 0),
        "roce": _safe_div(ebit, avg_capital_employed, 100).where(avg_capital_employed > 0),
        "debt_equity": _safe_div(debt, equity).where(equity > 0),
        "net_debt_ebitda": _safe_div(debt - cash, ebitda).where(ebitda > 0),
        "interest_coverage": _safe_div(ebit, interest).where(interest > 0),
        "cfo_pat": _safe_div(cfo.where(pat > 0), pat.where(pat > 0)),
        "sloan_accruals": _safe_div(pat - cfo, avg_assets, 100).where(avg_assets > 0),
        "dso": _safe_div(avg_receivables, rev, 365).where(rev > 0),
        "dio": _safe_div(avg_inventory, cogs, 365).where(cogs > 0),
        "dpo": _safe_div(avg_payables, cogs, 365).where(cogs > 0),
        "asset_turnover": _safe_div(rev, avg_assets).where(avg_assets > 0),
        "cost_of_borrowings_proxy": _safe_div(interest, avg_debt, 100).where(avg_debt > 0),
        "capex_revenue": _safe_div(capex, rev, 100).where(rev > 0),
    }
    result["ccc"] = result["dso"] + result["dio"] - result["dpo"]
    # Growth measures are not meaningful when the prior-year base is non-positive.
    for code in ("revenue_growth", "pat_growth", "asset_growth"):
        base = {"revenue_growth": rev.shift(1), "pat_growth": pat.shift(1), "asset_growth": assets.shift(1)}[code]
        current = {"revenue_growth": rev, "pat_growth": pat, "asset_growth": assets}[code]
        result[code] = result[code].where((base > 0) & (current > 0))
    return {k: v.replace([np.inf, -np.inf], np.nan).round(4) for k, v in result.items()}


def ratio_rows(financials: pd.DataFrame, sector: SectorProfile) -> list[dict[str, Any]]:
    series = calculate_ratio_series(financials)
    config = SECTOR_CONFIG[sector.key]
    rows: list[dict[str, Any]] = []
    for code in sector.metrics:
        meta = RATIO_LIBRARY.get(code)
        if meta is None:
            reason = config.get("unavailable", {}).get(code, "Requires a dedicated sector filing or operating KPI not present in the connected annual statement feed.")
            missing_values = pd.Series(np.nan, index=financials.index, dtype=float)
            rows.append({"code": code, "label": _special_label(code), "unit": "", "formula": "Not calculated from available fields", "definition": reason, "interpretation": reason, "inputs": "Dedicated issuer / regulatory disclosure required", "caveat": reason, "values": missing_values, "available": False, "latest_available": False})
            continue
        values = series.get(code, pd.Series(np.nan, index=financials.index, dtype=float))
        rows.append({"code": code, **meta, "values": values, "available": bool(values.notna().any()), "latest_available": bool(len(values) and pd.notna(values.iloc[-1]))})
    return rows


def _special_label(code: str) -> str:
    labels = {
        "nim":"Net interest margin (NIM)", "gnpa":"Gross NPA (GNPA)", "nnpa":"Net NPA (NNPA)",
        "casa":"CASA ratio", "crar":"Capital adequacy (CRAR)", "credit_cost":"Credit cost",
        "cost_to_income":"Cost-to-income ratio", "alm_gaps":"Asset-liability maturity gaps",
        "employee_cost_revenue":"Employee cost / revenue", "utilisation":"Employee utilisation",
        "attrition":"Employee attrition", "volume_growth":"Unit volume growth", "average_realisation":"Average realisation",
        "ebitda_per_tonne":"EBITDA per tonne", "capacity_utilisation":"Capacity utilisation",
        "rnd_revenue":"R&D / revenue", "export_mix":"Export revenue mix", "inventory_days":"Project inventory days",
        "presales_growth":"Pre-sales growth", "collections_ratio":"Collections / pre-sales",
        "solvency_ratio":"Solvency ratio", "vnb_margin":"Value of new business margin",
        "persistency":"Policy persistency", "combined_ratio":"Combined ratio", "claims_ratio":"Claims ratio",
        "orderbook_revenue":"Order book / revenue", "contract_assets":"Contract assets / unbilled revenue",
    }
    return labels.get(code, code.replace("_", " ").title())


def metric_status(current: float | None, previous: float | None, higher_is_better: bool | None = None) -> str:
    if current is None or not np.isfinite(current) or previous is None or not np.isfinite(previous):
        return "Insufficient history"
    delta = current - previous
    if abs(delta) < 0.05:
        return "Broadly stable"
    if higher_is_better is None:
        return "Changed — review context"
    improving = delta > 0 if higher_is_better else delta < 0
    return "Improving" if improving else "Deteriorating"


METRIC_DIRECTION = {
    "revenue_growth": True, "pat_growth": True, "asset_growth": None, "gross_margin": True,
    "ebitda_margin": True, "ebit_margin": True, "pat_margin": True, "roa": True, "roe": True,
    "roce": True, "debt_equity": False, "net_debt_ebitda": False, "interest_coverage": True,
    "cfo_pat": True, "sloan_accruals": False, "dso": False, "dio": False, "dpo": None, "ccc": False,
    "asset_turnover": True, "cost_of_borrowings_proxy": False, "capex_revenue": None,
}


@st.cache_data(ttl=21600, show_spinner=False)
def load_peer_statement_frames(peer_tickers: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """Load peer annual statements concurrently; unavailable peers are omitted, never imputed."""
    from data.fetch_live import get_source_preserving_financials

    unique = tuple(dict.fromkeys(str(t) for t in peer_tickers if t))
    output: dict[str, pd.DataFrame] = {}
    if not unique:
        return output
    with ThreadPoolExecutor(max_workers=min(4, len(unique))) as pool:
        futures = {pool.submit(get_source_preserving_financials, ticker): ticker for ticker in unique}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                frame = future.result()
                if frame is not None and not frame.empty:
                    output[ticker] = frame
            except Exception:
                continue
    return output


def compare_peers(
    company_ticker: str,
    company_financials: pd.DataFrame,
    peer_frames: dict[str, pd.DataFrame],
    sector: SectorProfile,
) -> tuple[pd.DataFrame, str | None]:
    """Compare only peers sharing one fiscal period with the selected company.

    An unavailable peer is omitted. A different fiscal year is never mixed into
    the comparison. One peer can be displayed, but peer medians require at least
    two valid peer observations in the UI.
    """
    company_series = calculate_ratio_series(company_financials)
    company_years = set(company_financials.index.astype(str))
    compatible: dict[str, dict[str, pd.Series]] = {}
    common_counts: dict[str, int] = {}
    for ticker, frame in peer_frames.items():
        if frame is None or frame.empty:
            continue
        shared_years = company_years.intersection(set(frame.index.astype(str)))
        if not shared_years:
            continue
        # The latest common period for this peer is considered when choosing
        # the cohort period; exact matching is applied again below.
        for year in shared_years:
            common_counts[year] = common_counts.get(year, 0) + 1
        compatible[ticker] = calculate_ratio_series(frame)

    viable_years = [year for year, count in common_counts.items() if count >= 1]
    if not viable_years:
        return pd.DataFrame(), None
    period = sorted(viable_years)[-1]
    selected_peers = [
        (ticker, metric_map) for ticker, metric_map in compatible.items()
        if period in set(peer_frames[ticker].index.astype(str))
    ]
    if len(selected_peers) < 1:
        return pd.DataFrame(), None

    def value(series: pd.Series | None) -> float:
        if series is None or period not in series.index:
            return np.nan
        try:
            return float(series.loc[period]) if pd.notna(series.loc[period]) else np.nan
        except Exception:
            return np.nan

    rows: list[dict[str, Any]] = []
    for ticker, metric_map in [(company_ticker, company_series), *selected_peers]:
        row: dict[str, Any] = {"Company / ticker": ticker, "Period": period}
        for code in sector.peer_metrics:
            label = RATIO_LIBRARY.get(code, {}).get("label", _special_label(code))
            row[label] = value(metric_map.get(code))
        rows.append(row)
    return pd.DataFrame(rows), period

