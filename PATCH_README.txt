RED FLAG INTELLIGENCE — CORPORATE & REGULATORY UI + SUMMARY RENAME

WHAT THIS PATCH CHANGES
1. Replaces pages/12_Corporate_Regulatory_Intelligence.py with a more understandable analyst-facing page:
   - Corporate Intelligence overview and clear KPI cards
   - Disclosure mix and analyst-attention distribution (counts, not an invented risk score)
   - Priority event cards with "why it matters" analyst checks
   - Corporate event timeline
   - Searchable/filterable event explorer
   - Legal & regulatory follow-up watchlist
   - Primary-source links within each event
2. Updates intelligence/corporate_regulatory.py so routine SEBI/exchange disclosures are not automatically labelled as enforcement.
   - Separates Regulatory actions & enforcement from Regulatory filings & compliance
   - Adds separate legal, audit, promoter/shareholding, related-party/corporate transaction,
     business-disruption and material-event categories
   - Uses Urgent review / Analyst review / Monitor / Routine labels
   - Keeps announcement counts separate from any risk score
   - Retains event_summary keys used by the Investment Summary page
3. Renames the sidebar page "Final Investment Summary" to "Summary".
4. Updates the page's own title to "Investment Summary" and section wording.

INSTALLATION
1. Stop Streamlit (Ctrl+C in the terminal).
2. Make a backup of app.py, pages/12_Corporate_Regulatory_Intelligence.py,
   pages/13_Final_Investment_Summary.py and intelligence/corporate_regulatory.py.
3. Extract this ZIP into the existing project root (the folder containing app.py).
4. Choose Replace files when prompted.
5. Restart using the project's existing launcher, preferably WINDOWS_RUN_DASHBOARD.bat.

FILES IN THIS PATCH
- app.py
- pages/12_Corporate_Regulatory_Intelligence.py
- pages/13_Final_Investment_Summary.py
- intelligence/corporate_regulatory.py

VALIDATION PERFORMED IN THE BUILD ENVIRONMENT
- Python syntax compilation passed for all four files.
- Six classification examples passed, including the distinction between routine SEBI disclosures and an explicit penalty/order.
- Mocked retrieval integration passed for filtering, duplicate removal, source normalization and event summary counts.
- No live NSE call was made in this build environment. Real event availability and primary-source links remain dependent on NSE connectivity and the records returned for the selected ticker.

IMPORTANT
The page's attention labels are research triage prompts, not legal conclusions or proof of wrongdoing. A disclosure count is not an overall company risk score. Always open and read the original exchange filing before treating an event as material.
