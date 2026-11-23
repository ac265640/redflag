# Red Flag Intelligence

Institutional-style Streamlit research terminal for Indian listed companies, combining financial analysis, forensic screening, governance, ESG disclosure coverage, credit-rating evidence, annual-report intelligence and portfolio tools.

## Run the application

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

On Windows, `SETUP_AND_RUN.bat` performs the one-time environment setup and `run_windows.bat` starts the dashboard after setup. Keep your existing `.venv` when applying a source update; the distributable source archive intentionally does not include a machine-specific virtual environment.

## Workspace

The application contains 14 Streamlit pages: Welcome, Executive Intelligence Dashboard, Company Overview, Forensic Red Flags, Governance Deep Dive, ESG Scorecard, Credit Rating, Portfolio Risk, Compare Companies, Yahoo Finance Data, Annual Report Intelligence, Management Intelligence, Corporate & Regulatory Intelligence and Final Investment Summary.

The Welcome company selector filters out entries marked as demo and presents real NSE/BSE listings returned by the connected listing source. Source availability can vary by company and provider. Yahoo Finance annual statements are a secondary data feed; NSE/BSE filings, issuer annual reports and rating-agency reports should be checked before relying on a value. A missing input is shown as N/A and is not substituted with zero or an estimated figure.

## Code layout

- `app.py` — Streamlit navigation, page configuration and global theme injection
- `utils/custom_css.py` — Institutional Premium design system shared across all pages
- `pages/` — the 14 research and portfolio workspaces
- `data/` — Yahoo Finance, NSE/BSE, BRSR, filing and annual-report data retrieval
- `financial_redflags/`, `forensic_hidden/`, `governance/`, `esg/`, `credit_rating/` — screening and evidence modules
- `intelligence/` — sector-aware ratios, peer comparisons, portfolio risk and management/corporate intelligence
- `visualization/` — Plotly charts and reusable Streamlit components
- `tests/` — offline checks for calculation formulas, missing-data handling and peer comparisons

## Scoring
- Forensic risk (0-100, worse = higher) = 65% financial flags + 35% hidden flags
- Governance (0-100, better = higher) = 100 - saturating penalty from governance flags
- ESG (0-100) = 70% industry-weighted E/S/G + 30% BRSR Core, minus controversy penalty
- Overall grade from a weighted risk index (45 forensic / 25 governance / 15 ESG / 15 credit), with a floor when 2+ critical flags stack

Flag points are Low 3, Medium 8, High 15, Critical 25 and are mapped through `100*(1-exp(-points/K))`. All thresholds live in `core/config.py`.

Red flags are screening signals, not proof of wrongdoing. This is not investment advice.

## Live Yahoo Finance integration

Real NSE/BSE selections are resolved to Yahoo Finance tickers (`.NS` for NSE and `.BO` for BSE). The application now includes a **Yahoo Finance Data** page that fetches available Yahoo Finance datasets for the selected company, including:

- company profile and quote fields
- historical OHLCV prices
- annual and quarterly income statements
- annual and quarterly balance sheets
- annual and quarterly cash flow statements
- dividends, splits and corporate actions
- major, institutional and mutual-fund holders where Yahoo provides them
- insider transactions / roster / purchases where available
- analyst recommendations, upgrades/downgrades and price targets
- earnings dates/history/estimates, revenue estimates, growth estimates, EPS trends/revisions
- valuation measures and fast quote data
- sustainability/ESG data where Yahoo provides it
- shares history, Yahoo news and SEC filings available through Yahoo

Missing Yahoo fields are shown as **N/A** and are never replaced with fabricated values. The existing forensic engine uses the normalized Yahoo annual financial statements for real companies. Governance, BRSR/BRSR Core and agency credit-rating sections remain N/A until their respective primary filing/rating sources are connected.

### Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The Yahoo Finance layer uses `yfinance`. It requires network access when the dashboard is running.

## Phase 2 — Annual Report Intelligence / Evidence Layer

The Phase 2 evidence layer adds the company's latest NSE-submitted annual report as a
primary diligence document. It keeps **Consolidated** financial statements as the
default analyst basis and supports a Standalone view when required.

The new `Annual Report Intelligence` page:
- discovers the latest NSE annual-report filing for the selected company
- links directly to the original NSE PDF
- extracts page-by-page report text when the PDF is available
- maps financial statements, notes, related parties, contingencies, exceptional items,
  accounting policies, segments, subsidiaries/JVs, guarantees, loans/advances,
  auditor observations and management commentary to page numbers
- shows a short locating quote for each extracted topic
- keeps unavailable topics as **N/A**
- provides a source trail that can be reused during equity-research diligence

The Company Overview also shows the latest annual-report source link without
downloading the full PDF, so normal navigation remains fast. The Forensic Red Flags
page links directly to the evidence layer for verification of flagged areas.

Evidence rule: **Source → Extract → Validate → Calculate → Explain**. A missing source
or unverified topic is not replaced with an estimated value.

## Public-source modules
- Governance: NSE Integrated Filing - Governance and NSE corporate announcements.
- ESG: NSE BRSR/BRSR Core filing coverage plus Yahoo Finance sustainability fields when available.
- Credit Rating: NSE corporate announcements containing credit-rating actions, with links to major rating agencies for verification.
- Missing values are shown as N/A. The public-source pages never create synthetic governance, ESG or credit-rating values for a live company.

## Public ESG / Governance / Credit sources
- **NSE BRSR:** filing metadata plus best-effort XBRL metric extraction from the latest accessible BRSR file.
- **CRISIL ESG:** public ESG ratings list is checked separately from BRSR disclosures; no rating is invented if the company is not listed.
- **NSE Governance:** Integrated Filing – Governance and filtered governance-related corporate announcements are summarised on the Governance Deep Dive page.
- **Credit:** NSE corporate announcements provide instrument-level rating actions; the dashboard links to rating-agency rationale pages and attempts a short rationale extraction from the public NSE attachment when available.
- Missing data remains **N/A**. A BRSR disclosure-coverage percentage is not treated as an ESG performance rating, and a debt credit rating is not treated as an equity rating.


V15: Governance retrieval optimized to avoid long waits: shorter NSE timeouts, only newest two XBRL candidates, and clearer retrieval status.


### Governance parser V18
- Uses a clean browser-like session for NSE archive/iXBRL HTML instead of the API session headers.
- Handles NSE archive wrappers/iframes in Chrome.
- Adds a body-text fallback for iXBRL filings when normal HTML tables are not exposed.
- Keeps missing/unparsed fields as N/A; no synthetic governance values are created.


V20: reads the exact NSE raw Integrated Filing-Governance XML before attempting any derived iXBRL HTML URL; expands the analyst takeaway with a time-saving summary.

### Phase 3 — Management Intelligence
- `intelligence/management_vs_numbers.py` extracts short, page-cited management commentary from the latest NSE annual report.
- The dashboard classifies commentary into growth/demand, margins/cost efficiency, cash/working capital, deleveraging and capex/expansion themes.
- Each theme is checked against reported financial trends. Contradictions are review prompts, not accusations.
- Missing annual-report evidence or financial inputs remain N/A; no synthetic values are introduced.
- UI page: **Management Intelligence**.


### Phase 3 — Corporate & Regulatory Intelligence
- `intelligence/corporate_regulatory.py` retrieves up to five years of NSE corporate announcements for the selected live company.
- It classifies diligence-relevant disclosures into regulatory/enforcement, legal/litigation, audit/accounting, promoter/capital structure, M&A/related parties and business-disruption/financial-stress themes.
- A keyword-based `Analyst attention` field prioritizes review; it is explicitly **not** a misconduct finding or synthetic risk score.
- Each event retains the NSE disclosure date, type, short detail and original attachment/source where exposed.
- The new **Corporate & Regulatory Intelligence** page provides filters, an event timeline and analyst guidance for reconciling disclosures with annual-report notes and financial statements.
- Missing attachments or unavailable NSE records remain **N/A**.

## If NSE/BRSR/Annual Report shows N/A
The dashboard does **not** invent ESG or annual-report values. NSE filing pages are JavaScript-driven and some NSE archive PDFs can be accessible in Chrome while a plain Python request is blocked. The current build therefore uses this order: NSE API -> NSE HTML -> Chrome/Selenium -> BSE annual-report fallback, and for PDF downloads it retries through a Chrome-cookie session.

Run `install_requirements.bat` once in the same Python/Anaconda environment used to launch Streamlit. Then restart Streamlit. The app also checks the PDF/XBRL dependencies at startup.

Verify the environment with:
```bat
python -c "import streamlit, selenium, pypdf, pdfplumber; print('Streamlit', streamlit.__version__); print('Selenium', selenium.__version__)"
```

If the annual report is a scanned/image-only PDF, the dashboard will keep page evidence and management commentary as N/A instead of fabricating text.
