import pandas as pd


def test_company_picker_labels_include_every_search_identifier():
    rows = pd.DataFrame([
        {"key": "RELIANCE.NS", "name": "Reliance Industries Limited", "symbol": "RELIANCE", "exchange": "NSE"},
        {"key": "500325.BO", "name": "Reliance Industries Limited", "symbol": "500325", "exchange": "BSE"},
    ])
    labels = [
        f"{r.name}  ·  {r.symbol}  ·  {r.exchange}  ·  {r.key}"
        for r in rows.itertuples(index=False)
    ]
    assert "Reliance Industries Limited" in labels[0]
    assert "RELIANCE" in labels[0]
    assert "NSE" in labels[0]
    assert "RELIANCE.NS" in labels[0]
    assert "500325" in labels[1]
    assert "500325.BO" in labels[1]


def test_each_dropdown_label_maps_to_a_unique_canonical_ticker():
    keys = ["RELIANCE.NS", "500325.BO"]
    labels = [f"Reliance Industries Limited  ·  {key.split('.')[0]}  ·  {key.split('.')[-1]}  ·  {key}" for key in keys]
    label_to_ticker = dict(zip(labels, keys))
    assert len(label_to_ticker) == 2
    assert label_to_ticker[labels[0]] == "RELIANCE.NS"
    assert label_to_ticker[labels[1]] == "500325.BO"
