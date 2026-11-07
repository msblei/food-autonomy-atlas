"""Farmed fish that eat feed: their share of each country's fish, per FBS fish item.

FAO FishStat, global production by production source (`atlas download --source fishstat`):
per country, species and source (capture, or aquaculture in fresh, brackish or marine water),
tonnes live weight, the basis of FAO's fish balances. A species counts as fed when it is farmed
and its ISSCAAP group is fed (`mappings/fish_isscaap.csv`), unless it is one of FAO's non-fed
filter feeders (NON_FED_SPECIES). Methodology, '"All food" coverage', "Farmed fish".

Output: data/processed/aquafeed.parquet, iso3 (and EU27), item, production_t, fed_t, fed_share
(fed farmed tonnes over all tonnes of the item, window means).
"""

from __future__ import annotations

import csv
import logging
import zipfile

import pandas as pd

from . import config
from .harmonise import load_countries

log = logging.getLogger(__name__)

OUT = "aquafeed.parquet"
CSV = "Global_production_quantity.csv"
SPECIES = "CL_FI_SPECIES_GROUPS.csv"
MAPPING = "fish_isscaap.csv"
AQUACULTURE = ("FRESHWATER", "BRACKISHWATER", "MARINE")
NON_FED_SPECIES = ("SVC", "BIC")  # silver carp, bighead carp: filter feeders, farmed without feed


def zip_path():
    url = config.SOURCES["fao_fishstat"]["file_url"]
    return config.RAW / "fishstat" / url.rsplit("/", 1)[1]


def mapping() -> pd.DataFrame:
    with (config.MAPPINGS / MAPPING).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(x for x in f if not x.startswith("#")))
    return pd.DataFrame(rows).assign(fed=lambda d: d["fed"] == "yes")


def compute(years: tuple[int, int]) -> pd.DataFrame:
    """Per country (and EU27) and FBS fish item: production, fed farmed production, their ratio."""
    with zipfile.ZipFile(zip_path()) as z:
        with z.open(SPECIES) as fh:
            sp = pd.read_csv(fh, dtype=str, usecols=["3A_Code", "ISSCAAP_Group_En"], keep_default_na=False)
        with z.open(CSV) as fh:
            q = pd.read_csv(fh, dtype={"COUNTRY.UN_CODE": str, "SPECIES.ALPHA_3_CODE": str,
                                       "PRODUCTION_SOURCE_DET.CODE": str, "MEASURE": str})
    q = q[(q["MEASURE"] == "Q_tlw") & q["PERIOD"].between(years[0], years[1])]
    m = mapping().set_index("isscaap_group")
    g = sp.set_index("3A_Code")["ISSCAAP_Group_En"]
    q["group"] = q["SPECIES.ALPHA_3_CODE"].map(g)
    q = q[q["group"].isin(m.index)]
    q["item"] = q["group"].map(m["fbs_item"])
    q["fed"] = (q["group"].map(m["fed"]) & q["PRODUCTION_SOURCE_DET.CODE"].isin(AQUACULTURE)
                & ~q["SPECIES.ALPHA_3_CODE"].isin(NON_FED_SPECIES))
    iso = load_countries().set_index("m49")["iso3"]
    q["iso3"] = q["COUNTRY.UN_CODE"].str.zfill(3).map(iso)
    unmapped = q.loc[q["iso3"].isna(), "VALUE"].sum() / max(q["VALUE"].sum(), 1)
    log.info("fishstat: %.2f%% of tonnes from areas outside our country list (dropped)", 100 * unmapped)
    q = q.dropna(subset=["iso3"])
    q["fed_t"] = q["VALUE"].where(q["fed"], 0.0)
    q = pd.concat([q, q[q["iso3"].isin(config.EU27)].assign(iso3="EU27")], ignore_index=True)
    n = years[1] - years[0] + 1
    out = q.groupby(["iso3", "item"])[["VALUE", "fed_t"]].sum().div(n).reset_index()
    out = out.rename(columns={"VALUE": "production_t"})
    out["fed_share"] = (out["fed_t"] / out["production_t"].where(out["production_t"] > 0)).fillna(0.0).clip(0, 1)
    return out


def load() -> dict[str, dict[str, float]]:
    """{iso3: {FBS fish item: fed farmed share}} from data/processed/aquafeed.parquet ({} without it)."""
    p = config.PROCESSED / OUT
    if not p.exists():
        return {}
    d = pd.read_parquet(p)
    return {iso: dict(zip(s["item"], s["fed_share"])) for iso, s in d.groupby("iso3")}


def run() -> None:
    from .trade import fbs_window

    dest = config.PROCESSED / OUT
    if not zip_path().exists():
        log.warning("no FishStat production; run `atlas download --source fishstat` (farmed fish not feed-adjusted)")
        dest.unlink(missing_ok=True)
        return
    out = compute(fbs_window())
    out.to_parquet(dest, index=False)
    nor = out[(out["iso3"] == "NOR") & (out["item"] == "Freshwater Fish")]
    log.info("wrote %s (%d country-items; Norway's freshwater and diadromous fish %.0f%% fed farmed)",
             dest, len(out), 100 * nor["fed_share"].iloc[0] if len(nor) else float("nan"))
