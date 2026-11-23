RED FLAG INTELLIGENCE — CORPORATE REGULATORY PAGE HOTFIX

Fixes the chart crash shown in the latest screenshot.
Cause: value_counts().to_frame() stores the category name in the DataFrame index,
while st.bar_chart(..., x="Category") expects Category to be a real column.
The chart input now uses reset_index(name="Events") and labels blank values
as Unclassified. Also adds the missing `re` import used by the event search box.

INSTALL:
1. Stop Streamlit with Ctrl+C.
2. Back up pages/12_Corporate_Regulatory_Intelligence.py.
3. Extract this ZIP into the project root (the folder containing app.py).
4. Replace the file under pages/.
5. Restart Streamlit.

Validation: Python compilation and a pandas chart-data regression test passed.
No live NSE request is needed for this UI/chart fix.
