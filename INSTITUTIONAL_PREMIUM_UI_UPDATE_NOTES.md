# Red Flag Intelligence — Institutional Premium UI Update

## What changed

- Replaced the conflicting legacy stylesheet layers with one shared Institutional Premium design system in `utils/custom_css.py`.
- Applied the shared system through the main app router so the same navy/charcoal surfaces, muted cyan-blue accents, typography, spacing, controls, tables, Plotly defaults and navigation styling carry across all 14 pages.
- Retained the Welcome terminal's market snapshot, market news, market-intelligence cards, company picker, institutional holdings, sector rotation and results calendar; the shared style is reapplied after its page-local CSS so it matches the rest of the app.
- Updated the application title, product logo, sidebar utility heading and Executive Intelligence Dashboard navigation label.
- Updated shared chart colours and severity palette to the new theme while retaining green/amber/red risk semantics.
- Changed the Company Overview summary heading to **Automated Research Insights — System Generated**, with wording that explicitly states the observations are rule-based and do not imply a human analyst.
- Replaced the combined revenue/EBITDA/PAT/cash-flow chart with separate visualizations: Revenue Trajectory (₹ crore), Profitability Margin Trend (%) and Cash Flow & Earnings Quality (₹ crore). Margin values use percentages; cash-flow values use a zero baseline; FCF appears only when capex is available.
- Suppressed generic industrial cash-flow comparisons for banks, NBFCs and insurers, where those measures would be misleading substitutes for regulatory/sector KPIs.
- Reduced the unavailable segment-performance placeholder to a compact data-coverage note rather than a large empty panel.
- Added a peer comparability caveat so the suggested peer universe is not presented as a certified comparable set.
- Refreshed the setup/readme notes and launcher titles to use Red Flag Intelligence branding.

## Data and functionality preservation

No synthetic company values were added. The update does not change the underlying provider fetchers, annual-statement normalization, forensic calculations, governance/ESG/credit source parsers, peer calculations or annual-report extraction logic. Missing values continue to display as N/A.

## Validation performed

- Python compile check: **80 files, 0 syntax errors**.
- `verify_project.py`: **PROJECT CHECK OK**.
- Offline unit tests: **7 tests passed, 10 subtests passed**.
- Company Overview chart smoke checks: **3 chart groups** for a non-financial-company test frame; the regulated-financial test frame intentionally omits the generic industrial cash-flow/margin comparisons.

## Validation limitations

The build environment did not have Streamlit installed, so a live browser render of the Streamlit application was not performed. The offline tests used a minimal cache-decorator stub only for module import; chart smoke tests used local test-shaped data, not live company data. No live Yahoo Finance, NSE/BSE, BRSR, credit-rating or annual-report source connectivity was verified here.

## Applying the update

Recommended: extract `Red_Flag_Intelligence_Institutional_Premium_UI_Patch.zip` into your current project folder and allow it to overwrite the listed source files. **Keep your existing `.venv` folder.** Then start the app with:

```bat
run_windows.bat
```

The full source archive also excludes `.venv`, Python bytecode and `__pycache__` folders so it remains portable.
