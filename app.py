"""Application entry point and router.

The dashboard uses the Premium Institutional Light design system. The Welcome page is
also the company-selection screen: choose an NSE/BSE company there and the app
moves directly to Company Overview. The selected ticker is then shared by all
analysis pages through ``st.session_state['ticker']``.
"""
from __future__ import annotations

# Bootstrap required runtime dependencies when the dashboard is launched directly
# with `streamlit run app.py`. This prevents a confusing ModuleNotFoundError when
# the user skips the optional batch installer.
import importlib.util
import subprocess
import sys

def _ensure_runtime_dependencies() -> None:
    required = {
        "streamlit": "streamlit>=1.50,<2",
        "pandas": "pandas>=2.2,<4",
        "numpy": "numpy>=1.26,<3",
        "plotly": "plotly>=5.20,<7",
        "requests": "requests>=2.31,<3",
        "yfinance": "yfinance>=1.7.0,<2",
        "pypdf": "pypdf>=5.0,<7",
        "pdfplumber": "pdfplumber>=0.11,<1",
        "selenium": "selenium>=4.25,<5",
        "bs4": "beautifulsoup4>=4.12,<5",
        "lxml": "lxml>=5.0,<7",
    }
    missing = [spec for module, spec in required.items() if importlib.util.find_spec(module) is None]
    if not missing:
        return
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    except Exception as exc:
        raise RuntimeError(
            "Missing project dependency: yfinance. "
            "Run `python -m pip install -r requirements.txt` and restart Streamlit. "
            f"Automatic installation failed: {exc}"
        ) from exc

_ensure_runtime_dependencies()

import streamlit as st

from core.config import ROOT
from utils.custom_css import inject_css

st.set_page_config(
    page_title="Red Flag Intelligence",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# The single Premium Institutional Light theme is injected before the routed page renders.
# Use a PNG logo for compatibility with Streamlit versions that reject SVG files in st.logo.
LOGO_PNG = ROOT / "assets" / "logo.png"
if LOGO_PNG.exists():
    st.logo(str(LOGO_PNG), size="large")
else:
    # Never let a missing/unsupported logo crash the entire dashboard.
    pass

nav = st.navigation(
    {
        "Start": [
            st.Page("pages/0_Welcome.py", title="Welcome", icon=":material/home:", default=True),
            st.Page("pages/1_Home_Dashboard.py", title="Executive Intelligence Dashboard", icon=":material/dashboard:"),
        ],
        "Company analysis": [
            st.Page("pages/2_Company_Overview.py", title="Company Overview", icon=":material/business:"),
            st.Page("pages/3_Forensic_Red_Flags.py", title="Forensic Red Flags", icon=":material/policy:"),
            st.Page("pages/4_Governance_DeepDive.py", title="Governance Deep Dive", icon=":material/account_balance:"),
            st.Page("pages/5_ESG_Scorecard.py", title="ESG Scorecard", icon=":material/eco:"),
            st.Page("pages/6_Credit_Rating.py", title="Credit Rating", icon=":material/credit_score:"),
            st.Page("pages/10_Annual_Report_Intelligence.py", title="Annual Report & Management Intelligence", icon=":material/description:"),
            st.Page("pages/12_Corporate_Regulatory_Intelligence.py", title="Corporate & Regulatory Intelligence", icon=":material/gavel:"),
            st.Page("pages/13_Final_Investment_Summary.py", title="Summary", icon=":material/task_alt:"),
        ],
        "Portfolio": [
            st.Page("pages/7_Portfolio_Risk.py", title="Portfolio Risk", icon=":material/pie_chart:"),
            st.Page("pages/8_Compare_Companies.py", title="Compare Companies", icon=":material/compare_arrows:"),
            st.Page("pages/9_Yahoo_Finance_Data.py", title="Yahoo Finance Data", icon=":material/cloud_download:"),
        ],
    }
)

# Do not put a company selector in app.py. It made the Welcome page and every
# other page carry duplicate selectors. Welcome owns the initial selection.
# Company-specific pages read the shared ticker from session state.
with st.sidebar:
    st.markdown("#### Workspace")
    st.caption("Premium Institutional · Light theme")
    if st.session_state.get("ticker"):
        st.caption(f"Selected: {st.session_state['ticker']}")
        if st.button("Change company", use_container_width=True):
            st.session_state.pop("ticker", None)
            st.session_state.pop("welcome_ticker", None)
            st.switch_page("pages/0_Welcome.py")
    else:
        st.caption("Select a company from the Welcome screen.")

# Apply the Premium Institutional Light theme globally before the routed page renders.
inject_css()
nav.run()
