"""Phase 3 — Management Intelligence: management commentary versus numbers."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from intelligence.management_vs_numbers import management_vs_numbers
from visualization.components import badge, notice, render, section, setup_page


ticker = setup_page("Management Intelligence")

render(
    f'<div class="rf-hero"><div style="display:flex;gap:.7rem;align-items:center;flex-wrap:wrap;margin-bottom:.8rem">'
    f'{badge("Phase 3", "blue")}{badge("Evidence-linked", "gray")}</div>'
    f'<h1>{ticker}: Management Intelligence</h1>'
    '<p>Read what management says, then test whether the reported financial trend supports the story.</p></div>'
)

basis = st.radio("Statement basis", ["Consolidated", "Standalone"], horizontal=True, index=0)

with st.status("Reading the latest NSE annual report…", expanded=False) as status:
    result = management_vs_numbers(ticker, basis)
    status.update(label="Management intelligence ready", state="complete")

if not result.get("latest_url"):
    notice("N/A — the latest annual-report attachment could not be retrieved, so management commentary cannot be validated.")
    st.stop()

if result.get("extraction_status") == "pdf_retrieved_but_text_unavailable":
    notice("The official annual-report PDF is available above, but its text layer could not be extracted automatically. Management commentary is therefore left N/A rather than inferred.")

m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Report period", result.get("period", "N/A"))
with m2:
    commentary = result.get("commentary")
    st.metric("Evidence statements", 0 if commentary is None else len(commentary))
with m3:
    checks = result.get("checks")
    contradictions = 0 if checks is None or checks.empty else int((checks["Status"] == "Contradicts").sum())
    st.metric("Contradictory themes", contradictions)

st.markdown(f"[Open original NSE annual-report attachment]({result['latest_url']})")

checks = result.get("checks")
if checks is not None and not checks.empty:
    section("Management vs numbers", "A contradiction is a review prompt, not proof that management is misleading.", "search")
    display = checks[["Theme", "Financial check", "Status", "Analyst interpretation"]].copy()
    st.dataframe(display, width="stretch", hide_index=True)

    for _, row in checks.iterrows():
        status = str(row["Status"])
        if status == "Contradicts":
            st.warning(f"**{row['Theme']} — Contradiction:** {row['Analyst interpretation']}")
        elif status == "Mixed":
            st.info(f"**{row['Theme']} — Mixed:** {row['Analyst interpretation']}")
        elif status == "Supports":
            st.success(f"**{row['Theme']} — Supports:** {row['Analyst interpretation']}")

commentary = result.get("commentary")
if commentary is not None and not commentary.empty:
    section("Management commentary evidence", "Short locating quotes are shown with the annual-report page so an analyst can verify the original wording.", "description")
    commentary_display = commentary[["Theme", "Tone", "Page", "Statement"]].copy()
    commentary_display["Page"] = commentary_display["Page"].map(
        lambda v: "N/A" if pd.isna(v) else str(v)
    )
    st.dataframe(
        commentary_display,
        width="stretch",
        hide_index=True,
    )
else:
    notice("N/A — management discussion / directors' report language was not located in the extracted annual-report text.")

section("How to use this", "This is a screening layer for equity research, not an accusation engine.", "info")
render(
    '<div class="rf-card flat">'
    '<b>1. Read the claim.</b> What is management saying about growth, margins, cash, leverage or expansion?<br><br>'
    '<b>2. Check the numbers.</b> Compare the statement with revenue growth, EBITDA margin, CFO/PAT, CCC, debt/equity and capex intensity.<br><br>'
    '<b>3. Investigate contradictions.</b> Open the cited annual-report page and then drill into notes, auditor observations and the relevant financial red flags.<br><br>'
    '<b>Important:</b> A contradiction can have a valid business explanation. The dashboard highlights where an analyst should investigate further.'
    '</div>'
)

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
