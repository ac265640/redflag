from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parent
required = [
    ROOT / 'app.py',
    ROOT / 'core' / 'scoring_engine.py',
    ROOT / 'forensic_hidden' / '__init__.py',
    ROOT / 'forensic_hidden' / 'off_balance_sheet.py',
    ROOT / 'data' / 'public_sources.py',
    ROOT / 'pages' / '4_Governance_DeepDive.py',
    ROOT / 'pages' / '2_Company_Overview.py',
    ROOT / 'intelligence' / 'sector_intelligence.py',
    ROOT / 'financial_redflags' / 'sector_engine.py',
    ROOT / 'pages' / '3_Forensic_Red_Flags.py',
    ROOT / 'data' / 'fetch_live.py',
]
missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
if missing:
    print('PROJECT CHECK FAILED')
    print('Missing files:')
    for item in missing:
        print('  -', item)
    raise SystemExit(1)

spec = importlib.util.spec_from_file_location('off_balance_sheet', ROOT / 'forensic_hidden' / 'off_balance_sheet.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print('PROJECT CHECK OK')
print('All required governance and forensic modules are present.')
