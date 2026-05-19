# -*- coding: utf-8 -*-
"""
新ペースロジック判定アプリ 完全版

主な更新:
- 開催日目・開催週区分をペース点に反映
- 開催日目から開催週区分を自動判定
- 前4角率から簡易脚質を自動推定
- 全頭ランキングを1枚画像風SVGで表示・保存
- CSV / TARGET HTML / HTM / TXT アップロード対応

同じフォルダに置く推奨ファイル:
- app.py
- ペース１０年.csv
- 調教師１０年.csv
"""

from __future__ import annotations

import io
import math
import re
import html
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

st.set_page_config(page_title="新ペースロジック判定アプリ", layout="wide")

APP_DIR = Path(__file__).resolve().parent
PACE_FILE_CANDIDATES = [
    "ペース１０年.csv", "ペース10年.csv", "pace_10years.csv", "pace.csv"
]
TRAINER_FILE_CANDIDATES = [
    "調教師１０年.csv", "調教師10年.csv", "trainer_10years.csv", "trainer.csv"
]

# ============================================================
# 基本ユーティリティ
# ============================================================

def read_csv_auto(src) -> pd.DataFrame:
    """cp932/utf-8-sig/utf-8を自動判定してCSVを読む。"""
    if src is None:
        return pd.DataFrame()
    if hasattr(src, "getvalue"):
        raw = src.getvalue()
        for enc in ["cp932", "utf-8-sig", "utf-8"]:
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except Exception:
                pass
        return pd.read_csv(io.BytesIO(raw), encoding="cp932", encoding_errors="ignore")
    path = Path(src)
    for enc in ["cp932", "utf-8-sig", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            pass
    return pd.read_csv(path, encoding="cp932", encoding_errors="ignore")


def find_existing_file(candidates: list[str]) -> Optional[Path]:
    for name in candidates:
        p = APP_DIR / name
        if p.exists():
            return p
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rename = {}
    for c in df.columns:
        cc = str(c).strip()
        if cc == "Ｒ":
            rename[c] = "R"
        elif cc in ["レース番号", "レースNo", "レースＮｏ"]:
            rename[c] = "R"
        elif cc == "芝・ダ":
            rename[c] = "芝ダ"
        elif cc == "芝ダート":
            rename[c] = "芝ダ"
        elif cc == "走破タイム":
            rename[c] = "走破時計"
        elif cc == "前PCI":
            rename[c] = "前走PCI"
        elif cc == "前走Ave-3F":
            rename[c] = "前走Ave3F"
        elif cc == "Ave-3F":
            rename[c] = "Ave3F"
        elif cc == "上り3F":
            rename[c] = "上がり3F"
        elif cc == "上り3F順":
            rename[c] = "上がり3F順"
        elif cc in ["開催日", "開催何日目", "何日目", "開催日数"]:
            rename[c] = "開催日目"
        elif cc in ["開催週", "開催区分", "週区分"]:
            rename[c] = "開催週区分"
        else:
            rename[c] = cc
    df = df.rename(columns=rename)
    return df


def to_num(s):
    return pd.to_numeric(s, errors="coerce")


def normalize_race_no(x):
    if pd.isna(x):
        return np.nan
    m = re.search(r"\d+", str(x))
    return int(m.group()) if m else np.nan


def normalize_surface(x: object) -> str:
    s = str(x).strip()
    if "ダ" in s:
        return "ダ"
    if "芝" in s:
        return "芝"
    return s


def finish_to_int(x) -> float:
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    zmap = str.maketrans("０１２３４５６７８９", "0123456789")
    s = s.translate(zmap)
    m = re.search(r"\d+", s)
    return float(m.group()) if m else np.nan


def safe_div(a, b):
    try:
        if pd.isna(a) or pd.isna(b) or float(b) == 0:
            return np.nan
        return float(a) / float(b)
    except Exception:
        return np.nan


def percentile_scores(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """0〜100のパーセンタイル点。"""
    s = pd.to_numeric(values, errors="coerce")
    if s.notna().sum() <= 1:
        return pd.Series(50, index=s.index, dtype=float)

    if higher_is_better:
        rank = s.rank(method="average", pct=True, ascending=True)
    else:
        rank = s.rank(method="average", pct=True, ascending=False)
    return (rank * 100).clip(0, 100)


def pace_type_from_rpci(x) -> str:
    try:
        v = float(x)
    except Exception:
        return "不明"
    if v <= 46:
        return "ハイ/持続"
    if v < 50:
        return "やや速い"
    if v < 54:
        return "標準〜やや上がり"
    return "スロー上がり"


def score_fit(value, target, scale, neutral=60.0) -> float:
    if pd.isna(value) or pd.isna(target):
        return neutral
    return float(np.clip(100 - abs(float(value) - float(target)) * scale, 0, 100))


def decode_text_auto(raw: bytes) -> str:
    """TARGET HTML/CSVの文字コードをざっくり自動判定してテキスト化。"""
    for enc in ["cp932", "shift_jis", "utf-8-sig", "utf-8"]:
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("cp932", errors="ignore")


def parse_corner_from_passage(x) -> float:
    """TARGETの通過順 06-07 / 09-09-08 などから最後の数字=4角相当を抜く。"""
    if pd.isna(x):
        return np.nan
    s = str(x).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    nums = re.findall(r"\d+", s)
    if not nums:
        return np.nan
    try:
        return float(nums[-1])
    except Exception:
        return np.nan


def _get_first_existing(row: pd.Series, names: list[str]):
    for name in names:
        if name in row.index:
            return row.get(name)
    return np.nan


# ============================================================
# 開催日目・開催週区分ロジック
# ============================================================

def infer_kaisai_week(day_value, week_value="") -> str:
    """
    開催日目から開催週区分を自動判定。
    すでに開催週区分が入っている場合はそれを優先。
    """
    week = "" if pd.isna(week_value) else str(week_value).strip()
    week = week.replace(" ", "").replace("　", "")

    valid = ["開幕週", "前半", "中盤", "終盤", "最終週"]
    if week in valid:
        return week

    try:
        day = int(float(day_value))
    except Exception:
        return "不明"

    if day <= 2:
        return "開幕週"
    if day <= 4:
        return "前半"
    if day <= 6:
        return "中盤"
    if day <= 8:
        return "終盤"
    return "最終週"


def style_from_position_rate(rate) -> str:
    """
    前4角率から簡易脚質を推定。
    前4角率 = 前4角順位 / 前走頭数
    """
    try:
        r = float(rate)
    except Exception:
        return "不明"

    if pd.isna(r):
        return "不明"
    if r <= 0.12:
        return "逃げ"
    if r <= 0.35:
        return "先行"
    if r <= 0.60:
        return "好位差し"
    if r <= 0.85:
        return "差し"
    return "追込"


def calc_kaisai_pace_bonus(row: pd.Series) -> float:
    """
    開催週区分 × 簡易脚質でペーススコアに補正を入れる。
    補正は強すぎないように最大±5程度。
    """
    week = row.get("開催週区分_使用", "不明")
    style = row.get("想定脚質", row.get("簡易脚質", "不明"))
    style = "" if pd.isna(style) else str(style)

    bonus = 0.0

    if week == "開幕週":
        if any(x in style for x in ["逃げ", "先行", "好位"]):
            bonus += 5
        elif any(x in style for x in ["差し", "追込", "追い込み"]):
            bonus -= 2

    elif week == "前半":
        if any(x in style for x in ["逃げ", "先行", "好位"]):
            bonus += 3
        elif any(x in style for x in ["追込", "追い込み"]):
            bonus -= 1

    elif week == "中盤":
        bonus += 0

    elif week == "終盤":
        if any(x in style for x in ["差し", "追込", "追い込み", "捲り", "まくり"]):
            bonus += 4
        elif any(x in style for x in ["逃げ", "先行"]):
            bonus -= 1

    elif week == "最終週":
        if any(x in style for x in ["差し", "追込", "追い込み", "捲り", "まくり"]):
            bonus += 5
        elif any(x in style for x in ["逃げ", "先行"]):
            bonus -= 2

    return float(np.clip(bonus, -5, 5))


# ============================================================
# TARGET HTML読み込み
# ============================================================

def extract_horse_headers_from_target_html(text: str) -> list[dict]:
    """TARGET出力HTMLから、現レースの馬番・馬名・騎手・調教師を順番に抜く。"""
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(text, "html.parser")
    body = soup.body or soup
    headers = []
    for hr in body.find_all("hr"):
        parts = []
        node = hr.next_sibling
        while node is not None and getattr(node, "name", None) != "hr":
            parts.append(str(node))
            node = node.next_sibling
        seg_html = "".join(parts)
        seg_soup = BeautifulSoup(seg_html, "html.parser")
        txt = " ".join(seg_soup.get_text(" ", strip=True).split())
        if "枠" not in txt or "番" not in txt:
            continue
        m_no = re.search(r"(\d+)\s*枠\s*(\d+)\s*番", txt)
        b = seg_soup.find("b")
        if not m_no or b is None:
            continue
        horse_name = b.get_text(strip=True)
        jockey = ""
        trainer = ""
        weight = np.nan
        pat = re.escape(horse_name) + r"\s+[牡牝セ]\s*\d+歳\s+(.+?)\(\d+歳\)\s+([0-9.]+)?\s+\([^)]+\)(.+?)\(\d+歳\)"
        m = re.search(pat, txt)
        if m:
            jockey = m.group(1).strip()
            weight = m.group(2).strip() if m.group(2) else np.nan
            trainer = m.group(3).strip()
        else:
            m_tr = re.search(r"\([美栗地外]\)\s*([^\s()]+)", txt)
            if m_tr:
                trainer = m_tr.group(1).strip()
        headers.append({
            "馬番": int(m_no.group(2)),
            "馬名": horse_name,
            "騎手": jockey,
            "調教師": trainer,
            "斤量": weight,
        })
    return headers


def read_target_html_prediction(uploaded_file, race_meta: dict) -> pd.DataFrame:
    """
    TARGETの1レース単位HTML出力から、新ペースロジック用の予想DFを作る。

    対応想定:
    - 1頭ごとに <HR> の見出しがあり、その直後に過去走テーブルがあるHTML
    - 各馬の過去走テーブルから「走前=1」の行を前走として採用
    - RPCI / PCI / Ave-3F / -3F差 / 通過順 / R前3F / ラップ系を取得
    """
    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else Path(uploaded_file).read_bytes()
    text = decode_text_auto(raw)
    headers = extract_horse_headers_from_target_html(text)

    tables = None
    for enc in ["cp932", "shift_jis", "utf-8-sig", "utf-8"]:
        try:
            tables = pd.read_html(io.BytesIO(raw), encoding=enc)
            break
        except Exception:
            pass
    if tables is None:
        tables = pd.read_html(io.StringIO(text))

    # TARGETの1頭ごと過去走テーブルだけに絞る
    race_tables = []
    for tbl in tables:
        if tbl is None or tbl.empty:
            continue
        t = tbl.copy()
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = ["_".join([str(x).strip() for x in col if str(x) != "nan"]).strip() for col in t.columns]
        else:
            t.columns = [str(c).strip() for c in t.columns]
        cols = set(t.columns)
        if ("走前" in cols and ("RPCI" in cols or "PCI" in cols or "Ave-3F" in cols or "通過順" in cols)):
            race_tables.append(t)

    # 絞り込みすぎて空なら元テーブルを使う
    if not race_tables:
        race_tables = []
        for tbl in tables:
            if tbl is None or tbl.empty:
                continue
            t = tbl.copy()
            if isinstance(t.columns, pd.MultiIndex):
                t.columns = ["_".join([str(x).strip() for x in col if str(x) != "nan"]).strip() for col in t.columns]
            else:
                t.columns = [str(c).strip() for c in t.columns]
            race_tables.append(t)

    rows = []
    n = min(len(headers), len(race_tables)) if headers else len(race_tables)

    for i in range(n):
        info = headers[i] if i < len(headers) else {}
        tbl = race_tables[i].copy()
        if tbl.empty:
            continue

        tbl.columns = [str(c).strip() for c in tbl.columns]

        # 走前=1の行を前走として採用
        if "走前" in tbl.columns:
            tmp = tbl.copy()
            tmp["走前_num"] = pd.to_numeric(tmp["走前"], errors="coerce")
            prev = tmp[tmp["走前_num"] == 1]
            r = (prev.iloc[0] if not prev.empty else tbl.iloc[0])
        else:
            r = tbl.iloc[0]

        passage = _get_first_existing(r, ["通過順", "通過順1-4", "通過順１－４"])
        prev4 = parse_corner_from_passage(passage)

        prev_surface = _get_first_existing(r, ["TR", "芝ダ", "芝・ダ"])
        prev_distance = _get_first_existing(r, ["距離"])

        row = {
            "日付": race_meta.get("日付", ""),
            "場所": race_meta.get("場所", ""),
            "R": race_meta.get("R", np.nan),
            "レース名": race_meta.get("レース名", ""),
            "芝ダ": race_meta.get("芝ダ", ""),
            "距離": race_meta.get("距離", np.nan),
            "馬場状態": race_meta.get("馬場状態", "良"),
            "頭数": race_meta.get("頭数", len(headers) if headers else np.nan),
            "開催日目": race_meta.get("開催日目", np.nan),
            "開催週区分": race_meta.get("開催週区分", ""),

            "馬番": info.get("馬番", _get_first_existing(r, ["番", "馬番"])),
            "馬名": info.get("馬名", _get_first_existing(r, ["馬名"])),
            "騎手": info.get("騎手", _get_first_existing(r, ["騎手"])),
            "調教師": info.get("調教師", _get_first_existing(r, ["調教師"])),
            "斤量": info.get("斤量", _get_first_existing(r, ["斤量"])),

            "前走頭数": _get_first_existing(r, ["頭", "R頭", "頭数"]),
            "前4角": prev4,
            "前走通過順": passage,
            "前走脚質": _get_first_existing(r, ["脚質", "決手"]),

            "前走RPCI": _get_first_existing(r, ["RPCI", "前走RPCI"]),
            "前走PCI": _get_first_existing(r, ["PCI", "前走PCI"]),
            "前走PCI3": _get_first_existing(r, ["PCI3", "前走PCI3"]),
            "前走Ave3F": _get_first_existing(r, ["Ave-3F", "Ave3F", "前走Ave-3F", "前走Ave3F"]),
            "前走上3F地点差": _get_first_existing(r, ["-3F差", "上3F地点差", "前走上3F地点差"]),
            "前走上3F": _get_first_existing(r, ["上3F", "上り3F", "前走上3F"]),

            "前走平均1F": _get_first_existing(r, ["平均1F", "前走平均1F"]),
            "前走平速度": _get_first_existing(r, ["平速度", "前走平速度"]),
            "前走-3F速度": _get_first_existing(r, ["-3F速度", "前走-3F速度"]),
            "前走上速度": _get_first_existing(r, ["上速度", "前走上速度"]),

            "前走R前3F": _get_first_existing(r, ["R前3F"]),
            "前走R前4F": _get_first_existing(r, ["R前4F"]),
            "前走R前5F": _get_first_existing(r, ["R前5F"]),
            "前走レースラップタイム": _get_first_existing(r, ["レースラップタイム"]),
            "前走レース通過タイム": _get_first_existing(r, ["レース通過タイム"]),

            "前走着順": _get_first_existing(r, ["着", "着順", "確着"]),
            "前走着差": _get_first_existing(r, ["着差"]),
            "前走場所": _get_first_existing(r, ["場所"]),
            "前走距離": prev_distance,
            "前走芝ダ": prev_surface,
            "前走馬場状態": _get_first_existing(r, ["状", "馬場状態"]),
            "前走レース名": _get_first_existing(r, ["レース名"]),
            "前走クラス": _get_first_existing(r, ["クラス"]),
        }
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    for c in [
        "R", "距離", "頭数", "馬番", "前走頭数", "前4角",
        "前走RPCI", "前走PCI", "前走PCI3", "前走Ave3F",
        "前走上3F地点差", "前走上3F", "開催日目",
        "前走着差", "前走距離"
    ]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    if "前走芝ダ" in out.columns:
        out["前走芝ダ"] = out["前走芝ダ"].apply(normalize_surface)

    return out

def load_prediction_input(uploaded_file, race_meta: dict) -> pd.DataFrame:
    """CSV/HTMLを自動判定して予想用データに変換。"""
    name = getattr(uploaded_file, "name", "").lower()
    if name.endswith(".html") or name.endswith(".htm"):
        return read_target_html_prediction(uploaded_file, race_meta)
    return read_csv_auto(uploaded_file)


# ============================================================
# 前処理
# ============================================================

def prep_common(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)
    if "R" in df.columns:
        df["R"] = df["R"].apply(normalize_race_no)
    for c in ["日付", "場所", "レース名", "馬名", "騎手", "調教師", "馬場状態", "開催週区分"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    if "芝ダ" in df.columns:
        df["芝ダ"] = df["芝ダ"].apply(normalize_surface)
    for c in [
        "距離", "頭数", "馬番", "前走RPCI", "前走PCI", "前走Ave3F",
        "前走上3F地点差", "前走頭数", "開催日目"
    ]:
        if c in df.columns:
            df[c] = to_num(df[c])
    for c in ["RPCI", "PCI", "Ave3F", "上3F地点差", "頭数", "馬番", "3角", "4角", "3角.1", "4角.1"]:
        if c in df.columns:
            df[c] = to_num(df[c])
    if "着順" in df.columns:
        df["着順数値"] = df["着順"].apply(finish_to_int)
    return df


def choose_prev_corner_col(df: pd.DataFrame, base: str) -> Optional[str]:
    candidates = [base, f"{base}.1"]
    for c in candidates:
        if c in df.columns and df[c].notna().sum() > 0:
            return c
    return None


# ============================================================
# 過去データから基準表を作る
# ============================================================

@st.cache_data(show_spinner=False)
def build_reference_tables(pace_df: pd.DataFrame, trainer_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pace = prep_common(pace_df)
    trainer = prep_common(trainer_df) if not trainer_df.empty else pd.DataFrame()

    required = ["場所", "芝ダ", "距離", "馬場状態"]
    for c in required:
        if c not in pace.columns:
            raise ValueError(f"ペース10年CSVに必要項目がありません: {c}")

    if "着順数値" not in pace.columns:
        pace["着順数値"] = np.nan
    pace["is_top3"] = pace["着順数値"].between(1, 3)

    if "4角" in pace.columns:
        pace["四角率"] = pace.apply(lambda r: safe_div(r.get("4角"), r.get("頭数")), axis=1)
    elif "4角.1" in pace.columns:
        pace["四角率"] = pace.apply(lambda r: safe_div(r.get("4角.1"), r.get("頭数")), axis=1)
    else:
        pace["四角率"] = np.nan

    pace["ペース型"] = pace.get("RPCI", pd.Series(index=pace.index, dtype=float)).apply(pace_type_from_rpci)

    top3 = pace[pace["is_top3"]].copy()
    group_cols = ["場所", "芝ダ", "距離", "馬場状態"]
    cond = top3.groupby(group_cols, dropna=False).agg(
        条件出走数=("馬名", "size"),
        基準RPCI=("RPCI", "mean"),
        基準PCI=("PCI", "mean"),
        基準Ave3F=("Ave3F", "mean"),
        基準上3F地点差=("上3F地点差", "mean"),
        基準四角率=("四角率", "mean"),
        基準上がり3F=("上がり3F", "mean") if "上がり3F" in top3.columns else ("馬名", "size"),
    ).reset_index()

    cond2 = top3.groupby(["場所", "芝ダ", "距離"], dropna=False).agg(
        条件出走数2=("馬名", "size"),
        基準RPCI2=("RPCI", "mean"),
        基準PCI2=("PCI", "mean"),
        基準Ave3F2=("Ave3F", "mean"),
        基準上3F地点差2=("上3F地点差", "mean"),
        基準四角率2=("四角率", "mean"),
    ).reset_index()

    j = pace.dropna(subset=["騎手"]).groupby(["騎手", "ペース型"], dropna=False).agg(
        騎手騎乗数=("馬名", "size"),
        騎手複勝数=("is_top3", "sum"),
    ).reset_index()
    j["騎手複勝率"] = j["騎手複勝数"] / j["騎手騎乗数"].replace(0, np.nan)
    base_rate = pace["is_top3"].mean() if len(pace) else 0.22
    k = 30
    j["騎手補正率"] = (j["騎手複勝数"] + base_rate * k) / (j["騎手騎乗数"] + k)
    j["騎手ペース点"] = j.groupby("ペース型")["騎手補正率"].transform(lambda s: percentile_scores(s, True))
    j.loc[j["騎手騎乗数"] < 10, "騎手ペース点"] = 50

    if not trainer.empty and "調教師" in trainer.columns:
        key = ["日付", "場所", "R", "馬番", "馬名"]
        pace_key_cols = [c for c in key if c in pace.columns]
        trainer_key_cols = [c for c in key if c in trainer.columns]
        if set(pace_key_cols) == set(trainer_key_cols) and len(pace_key_cols) >= 4:
            merge_cols = pace_key_cols
            p_small = pace[merge_cols + ["ペース型", "is_top3"]].copy()
            t = trainer.merge(p_small, on=merge_cols, how="left")
        else:
            t = trainer.copy()
            t["ペース型"] = "不明"
            if "着順数値" not in t.columns:
                t["着順数値"] = np.nan
            t["is_top3"] = t["着順数値"].between(1, 3)

        tr = t.dropna(subset=["調教師"]).groupby(["調教師", "ペース型"], dropna=False).agg(
            調教師出走数=("馬名", "size"),
            調教師複勝数=("is_top3", "sum"),
        ).reset_index()
        tr["調教師複勝率"] = tr["調教師複勝数"] / tr["調教師出走数"].replace(0, np.nan)
        tr["調教師補正率"] = (tr["調教師複勝数"] + base_rate * k) / (tr["調教師出走数"] + k)
        tr["調教師ペース点"] = tr.groupby("ペース型")["調教師補正率"].transform(lambda s: percentile_scores(s, True))
        tr.loc[tr["調教師出走数"] < 10, "調教師ペース点"] = 50
    else:
        tr = pd.DataFrame(columns=["調教師", "ペース型", "調教師出走数", "調教師複勝率", "調教師ペース点"])

    cond.attrs["fallback"] = cond2
    return cond, j, tr


# ============================================================
# 予想CSVを判定
# ============================================================

def attach_condition_reference(pred: pd.DataFrame, cond: pd.DataFrame) -> pd.DataFrame:
    out = pred.merge(cond, on=["場所", "芝ダ", "距離", "馬場状態"], how="left")
    fb = cond.attrs.get("fallback")
    if fb is not None:
        out = out.merge(fb, on=["場所", "芝ダ", "距離"], how="left")
        for a, b in [
            ("基準RPCI", "基準RPCI2"), ("基準PCI", "基準PCI2"),
            ("基準Ave3F", "基準Ave3F2"), ("基準上3F地点差", "基準上3F地点差2"),
            ("基準四角率", "基準四角率2"),
        ]:
            if a in out.columns and b in out.columns:
                out[a] = out[a].fillna(out[b])
    return out


def score_prediction(pred_df: pd.DataFrame, cond: pd.DataFrame, jockey_tbl: pd.DataFrame, trainer_tbl: pd.DataFrame) -> pd.DataFrame:
    df = prep_common(pred_df)

    if "R" in df.columns:
        df = df[df["R"].between(7, 12)].copy()

    for c in [
        "前走RPCI", "前走PCI", "前走Ave3F", "前走上3F地点差",
        "前走頭数", "騎手", "調教師", "開催日目", "開催週区分"
    ]:
        if c not in df.columns:
            df[c] = np.nan if c != "開催週区分" else ""

    prev4 = choose_prev_corner_col(df, "前4角")
    if prev4:
        df["前4角_使用"] = to_num(df[prev4])
    else:
        df["前4角_使用"] = np.nan
    df["前4角率"] = df.apply(lambda r: safe_div(r.get("前4角_使用"), r.get("前走頭数")), axis=1)

    df["開催週区分_使用"] = df.apply(lambda r: infer_kaisai_week(r.get("開催日目"), r.get("開催週区分", "")), axis=1)
    df["簡易脚質"] = df["前4角率"].apply(style_from_position_rate)
    if "想定脚質" not in df.columns:
        df["想定脚質"] = df["簡易脚質"]

    df = attach_condition_reference(df, cond)

    df["今回ペース型"] = df["基準RPCI"].apply(pace_type_from_rpci)

    df["RPCI一致点"] = [score_fit(v, t, 5.0, 60) for v, t in zip(df["前走RPCI"], df["基準RPCI"])]
    df["PCI一致点"] = [score_fit(v, t, 4.0, 60) for v, t in zip(df["前走PCI"], df["基準PCI"])]
    df["Ave3F一致点"] = [score_fit(v, t, 12.0, 60) for v, t in zip(df["前走Ave3F"], df["基準Ave3F"])]
    df["上3F地点差一致点"] = [score_fit(v, t, 25.0, 60) for v, t in zip(df["前走上3F地点差"], df["基準上3F地点差"])]
    df["位置一致点"] = [score_fit(v, t, 120.0, 60) for v, t in zip(df["前4角率"], df["基準四角率"])]

    df["ペース基礎点"] = (
        df["RPCI一致点"] * 0.35 +
        df["PCI一致点"] * 0.15 +
        df["Ave3F一致点"] * 0.20 +
        df["上3F地点差一致点"] * 0.10 +
        df["位置一致点"] * 0.20
    ).round(1)

    df["開催週ペース補正"] = df.apply(calc_kaisai_pace_bonus, axis=1).round(1)
    df["ペーススコア"] = (df["ペース基礎点"] + df["開催週ペース補正"]).clip(0, 100).round(1)

    df = df.merge(
        jockey_tbl[["騎手", "ペース型", "騎手騎乗数", "騎手複勝率", "騎手ペース点"]].rename(columns={"ペース型": "今回ペース型"}),
        on=["騎手", "今回ペース型"], how="left"
    )
    df["騎手ペース点"] = df["騎手ペース点"].fillna(50).round(1)
    df["騎手騎乗数"] = df["騎手騎乗数"].fillna(0).astype(int)

    if not trainer_tbl.empty and "調教師" in df.columns:
        df = df.merge(
            trainer_tbl[["調教師", "ペース型", "調教師出走数", "調教師複勝率", "調教師ペース点"]].rename(columns={"ペース型": "今回ペース型"}),
            on=["調教師", "今回ペース型"], how="left"
        )
    else:
        df["調教師出走数"] = 0
        df["調教師複勝率"] = np.nan
        df["調教師ペース点"] = 50

    df["調教師ペース点"] = df["調教師ペース点"].fillna(50).round(1)
    df["調教師出走数"] = df["調教師出走数"].fillna(0).astype(int)

    race_key = ["日付", "場所", "R"]
    df["ペース順位"] = df.groupby(race_key)["ペーススコア"].rank(method="first", ascending=False).astype(int)

    def label_row(r):
        rank = int(r["ペース順位"])
        j70 = float(r.get("騎手ペース点", 0)) >= 70
        t70 = float(r.get("調教師ペース点", 0)) >= 70
        if rank == 1 and j70 and t70:
            return "S評価"
        if rank == 1 and (j70 or t70):
            return "A評価"
        if rank == 1:
            return "B評価"
        if rank in (2, 3) and j70:
            return "相手候補"
        if rank in (2, 3) and t70:
            return "注意候補"
        return ""

    df["評価"] = df.apply(label_row, axis=1)

    def comment_row(r):
        parts = []
        if r["ペース順位"] == 1:
            parts.append("ペース1位")
        elif r["ペース順位"] in (2, 3):
            parts.append(f"ペース{int(r['ペース順位'])}位")
        if r.get("開催週ペース補正", 0) > 0:
            parts.append(f"{r.get('開催週区分_使用')}補正+{r.get('開催週ペース補正'):.1f}")
        elif r.get("開催週ペース補正", 0) < 0:
            parts.append(f"{r.get('開催週区分_使用')}補正{r.get('開催週ペース補正'):.1f}")
        if r.get("騎手ペース点", 0) >= 70:
            parts.append("騎手70+")
        if r.get("調教師ペース点", 0) >= 70:
            parts.append("調教師70+")
        return " / ".join(parts)

    df["判定理由"] = df.apply(comment_row, axis=1)

    return df.sort_values(["日付", "場所", "R", "ペース順位", "馬番"]).reset_index(drop=True)


# ============================================================
# 全頭ランキングSVG
# ============================================================

def _svg_text(x) -> str:
    return html.escape("" if pd.isna(x) else str(x))


def make_ranking_svg(race_df: pd.DataFrame, title: str = "全頭ランキング") -> str:
    """
    レース内全頭ランキングを1枚SVGとして作る。
    Streamlit上で画像風表示・ダウンロード可能。
    """
    d = race_df.sort_values(["ペース順位", "馬番"]).copy()
    n = len(d)
    row_h = 44
    header_h = 104
    footer_h = 42
    w = 760
    h = header_h + row_h * max(n, 1) + footer_h

    place = _svg_text(d["場所"].iloc[0]) if "場所" in d.columns and not d.empty else ""
    rno = int(d["R"].iloc[0]) if "R" in d.columns and not d.empty and pd.notna(d["R"].iloc[0]) else ""
    race_name = _svg_text(d["レース名"].iloc[0]) if "レース名" in d.columns and not d.empty else ""
    surface = _svg_text(d["芝ダ"].iloc[0]) if "芝ダ" in d.columns and not d.empty else ""
    dist = int(d["距離"].iloc[0]) if "距離" in d.columns and not d.empty and pd.notna(d["距離"].iloc[0]) else ""
    baba = _svg_text(d["馬場状態"].iloc[0]) if "馬場状態" in d.columns and not d.empty else ""
    week = _svg_text(d["開催週区分_使用"].iloc[0]) if "開催週区分_使用" in d.columns and not d.empty else ""

    svg = []
    svg.append(f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" rx="24" fill="#ffffff"/>
<rect x="0" y="0" width="{w}" height="{h}" rx="24" fill="#f8fafc"/>
<rect x="24" y="24" width="{w-48}" height="{h-48}" rx="22" fill="#ffffff" stroke="#d9dee7"/>
<text x="52" y="64" font-size="30" font-weight="800" fill="#111827">{_svg_text(title)}</text>
<text x="52" y="92" font-size="18" fill="#64748b">{place}{rno}R　{race_name}　{surface}{dist}m　{baba}　{week}</text>

<rect x="44" y="116" width="{w-88}" height="34" rx="10" fill="#eef2f7"/>
<text x="66" y="139" font-size="16" font-weight="700" fill="#475569">順位</text>
<text x="144" y="139" font-size="16" font-weight="700" fill="#475569">馬番</text>
<text x="232" y="139" font-size="16" font-weight="700" fill="#475569">馬名</text>
<text x="475" y="139" font-size="16" font-weight="700" fill="#475569">補正</text>
<text x="585" y="139" font-size="16" font-weight="700" fill="#475569">ペース点</text>
""")

    y0 = 156
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (_, r) in enumerate(d.iterrows()):
        y = y0 + i * row_h
        rank = int(r.get("ペース順位", i + 1))
        uma = int(r.get("馬番", 0)) if pd.notna(r.get("馬番", np.nan)) else ""
        name = _svg_text(r.get("馬名", ""))
        score = r.get("ペーススコア", np.nan)
        base = r.get("ペース基礎点", np.nan)
        bonus = r.get("開催週ペース補正", 0)
        style = _svg_text(r.get("簡易脚質", ""))
        eval_label = _svg_text(r.get("評価", ""))

        if rank == 1:
            bg = "#fff7d6"
        elif rank == 2:
            bg = "#eef4fb"
        elif rank == 3:
            bg = "#fff0df"
        elif i % 2 == 0:
            bg = "#ffffff"
        else:
            bg = "#f8fafc"

        svg.append(f'<rect x="44" y="{y}" width="{w-88}" height="{row_h}" fill="{bg}" stroke="#e5e7eb"/>')

        rank_label = f"{rank}位"
        icon = medal.get(rank, "")
        svg.append(f'<text x="62" y="{y+28}" font-size="18" font-weight="800" fill="#111827">{icon} {rank_label}</text>')

        badge_fill = "#facc15" if rank == 1 else "#e5e7eb"
        svg.append(f'<circle cx="163" cy="{y+22}" r="15" fill="{badge_fill}" stroke="#cbd5e1"/>')
        svg.append(f'<text x="163" y="{y+28}" font-size="16" font-weight="800" text-anchor="middle" fill="#111827">{uma}</text>')

        svg.append(f'<text x="232" y="{y+20}" font-size="18" font-weight="700" fill="#111827">{name}</text>')
        svg.append(f'<text x="232" y="{y+37}" font-size="12" fill="#64748b">{style}　{eval_label}</text>')

        if bonus > 0:
            bonus_text = f"+{bonus:.1f}"
            bonus_color = "#15803d"
        elif bonus < 0:
            bonus_text = f"{bonus:.1f}"
            bonus_color = "#b91c1c"
        else:
            bonus_text = "0.0"
            bonus_color = "#64748b"

        svg.append(f'<text x="506" y="{y+28}" font-size="17" font-weight="800" text-anchor="middle" fill="{bonus_color}">{bonus_text}</text>')

        score_text = "" if pd.isna(score) else f"{float(score):.1f}"
        base_text = "" if pd.isna(base) else f"基礎 {float(base):.1f}"
        svg.append(f'<text x="640" y="{y+22}" font-size="20" font-weight="900" text-anchor="middle" fill="#111827">{score_text}</text>')
        svg.append(f'<text x="640" y="{y+38}" font-size="11" text-anchor="middle" fill="#64748b">{base_text}</text>')

    fy = y0 + row_h * max(n, 1) + 26
    svg.append(f'<text x="{w/2}" y="{fy}" font-size="15" text-anchor="middle" fill="#64748b">※全頭をペーススコア順に表示。補正＝開催日目・開催週区分×脚質補正</text>')
    svg.append('</svg>')
    return "\n".join(svg)


# ============================================================
# 成績集計: 着順/配当がある場合
# ============================================================

def clean_pay(x):
    if pd.isna(x):
        return 0.0
    s = str(x).replace(",", "").replace("円", "").replace("(", "").replace(")", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def summarize_results(df: pd.DataFrame) -> pd.DataFrame:
    if "着順数値" not in df.columns or df["着順数値"].isna().all():
        return pd.DataFrame()
    d = df[df["評価"].astype(str) != ""].copy()
    if d.empty:
        return pd.DataFrame()
    for c in ["単勝配当", "複勝配当"]:
        if c not in d.columns:
            d[c] = 0
        d[c] = d[c].apply(clean_pay)
    rows = []
    order = ["S評価", "A評価", "B評価", "相手候補", "注意候補"]
    for label in order:
        x = d[d["評価"] == label]
        if x.empty:
            continue
        n = len(x)
        win = (x["着順数値"] == 1).sum()
        top3 = x["着順数値"].between(1, 3).sum()
        rows.append({
            "評価": label,
            "頭数": n,
            "勝率": round(win / n * 100, 1),
            "複勝率": round(top3 / n * 100, 1),
            "単勝回収率": round(x["単勝配当"].sum() / (n * 100) * 100, 1),
            "複勝回収率": round(x["複勝配当"].sum() / (n * 100) * 100, 1),
        })
    return pd.DataFrame(rows)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ============================================================
# Streamlit UI
# ============================================================

st.title("新ペースロジック判定アプリ v開催週補正")
st.caption("CSV / TARGET HTML対応。開催日目・開催週区分をペース点へ反映し、全頭ランキングを1枚画像風で表示します。")
st.caption("ペース1位を主役にして、騎手ペース70以上・調教師ペース70以上で S/A/B/相手候補/注意候補 を判定します。")

with st.expander("このアプリで使う評価ルール", expanded=False):
    st.markdown(
        """
- **ペース基礎点**：RPCI一致点35% + PCI一致点15% + Ave3F一致点20% + 上3F地点差一致点10% + 位置一致点20%
- **開催週ペース補正**：開催週区分 × 簡易脚質で最大±5点
- **ペーススコア**：ペース基礎点 + 開催週ペース補正
- **S評価**：ペース1位 ＋ 騎手ペース70以上 ＋ 調教師ペース70以上
- **A評価**：ペース1位 ＋ 騎手70以上 or 調教師70以上
- **B評価**：ペース1位のみ
- **相手候補**：ペース2〜3位 ＋ 騎手70以上
- **注意候補**：ペース2〜3位 ＋ 調教師70以上 ※騎手70未満

※ 1〜6Rは自動で除外し、7〜12Rだけ判定します。  
※ 開催週区分が空欄の場合は、開催日目から自動判定します。  
※ 欠損値は中立点で処理します。
        """
    )

st.subheader("入力ファイル")
st.info("予想用アップロード欄が『CSV / TARGET HTML』表示になっていれば最新版です。")
col1, col2, col3 = st.columns(3)
with col1:
    pred_file = st.file_uploader(
        "予想用CSV / TARGET HTMLをアップロード（CSV・HTML・HTM対応）",
        type=None,
        key="pred_anyfile",
        help="iPhoneでHTMLが選べない場合があるため、ファイル種別制限を外しています。",
    )
with col2:
    pace_upload = st.file_uploader("ペース10年CSV 任意", type=["csv"], key="pace")
with col3:
    trainer_upload = st.file_uploader("調教師10年CSV 任意", type=["csv"], key="trainer")

st.subheader("HTML用：今回レース条件")
st.caption("TARGET HTMLを使う場合は、HTML内に今回条件が無いことがあるため、ここで指定します。CSVの場合はCSV内の列を優先します。")
meta1, meta2, meta3, meta4, meta5 = st.columns(5)
with meta1:
    meta_date = st.text_input("日付", value="2026.5.18")
    meta_place = st.text_input("場所", value="東京")
with meta2:
    meta_r = st.number_input("R", min_value=1, max_value=12, value=11, step=1)
    meta_name = st.text_input("レース名", value="ヴィクトリアマイル")
with meta3:
    meta_surface = st.selectbox("芝ダ", options=["芝", "ダ"], index=0)
    meta_distance = st.number_input("距離", min_value=800, max_value=4000, value=1600, step=100)
with meta4:
    meta_baba = st.selectbox("馬場状態", options=["良", "稍重", "重", "不良"], index=0)
    meta_heads = st.number_input("頭数", min_value=1, max_value=30, value=18, step=1)
with meta5:
    meta_kaisai_day = st.number_input("開催日目", min_value=1, max_value=16, value=1, step=1)
    auto_week = infer_kaisai_week(meta_kaisai_day, "")
    week_options = ["自動判定", "開幕週", "前半", "中盤", "終盤", "最終週"]
    meta_week_select = st.selectbox("開催週区分", options=week_options, index=0)
    meta_week = auto_week if meta_week_select == "自動判定" else meta_week_select
    st.caption(f"使用区分：{meta_week}")

race_meta = {
    "日付": meta_date,
    "場所": meta_place,
    "R": int(meta_r),
    "レース名": meta_name,
    "芝ダ": meta_surface,
    "距離": int(meta_distance),
    "馬場状態": meta_baba,
    "頭数": int(meta_heads),
    "開催日目": int(meta_kaisai_day),
    "開催週区分": meta_week,
}

pace_path = find_existing_file(PACE_FILE_CANDIDATES)
trainer_path = find_existing_file(TRAINER_FILE_CANDIDATES)

try:
    if pace_upload is not None:
        pace_df = read_csv_auto(pace_upload)
        pace_source = "アップロード"
    elif pace_path is not None:
        pace_df = read_csv_auto(pace_path)
        pace_source = pace_path.name
    else:
        pace_df = pd.DataFrame()
        pace_source = "未読込"

    if trainer_upload is not None:
        trainer_df = read_csv_auto(trainer_upload)
        trainer_source = "アップロード"
    elif trainer_path is not None:
        trainer_df = read_csv_auto(trainer_path)
        trainer_source = trainer_path.name
    else:
        trainer_df = pd.DataFrame()
        trainer_source = "未読込"
except Exception as e:
    st.error(f"過去データの読み込みでエラー: {e}")
    st.stop()

st.info(f"過去ペースCSV: {pace_source} / 調教師CSV: {trainer_source}")

if pace_df.empty:
    st.warning("ペース10年CSVが必要です。同じフォルダに『ペース１０年.csv』を置くか、画面からアップロードしてください。")
    st.stop()

try:
    cond_tbl, jockey_tbl, trainer_tbl = build_reference_tables(pace_df, trainer_df)
except Exception as e:
    st.error(f"基準表の作成でエラー: {e}")
    st.stop()

st.success(f"基準表作成完了：条件 {len(cond_tbl):,}件 / 騎手 {len(jockey_tbl):,}件 / 調教師 {len(trainer_tbl):,}件")

if pred_file is None:
    st.warning("まず予想用CSV、またはTARGET HTMLをアップロードしてください。")
    st.stop()

try:
    pred_df = load_prediction_input(pred_file, race_meta)
    if pred_df.empty:
        st.error("アップロードファイルから馬データを読み取れませんでした。")
        st.stop()

    for c in ["開催日目", "開催週区分"]:
        if c not in pred_df.columns:
            pred_df[c] = race_meta[c]
        else:
            if c == "開催日目":
                pred_df[c] = pd.to_numeric(pred_df[c], errors="coerce").fillna(race_meta[c])
            else:
                pred_df[c] = pred_df[c].replace(["", "nan", "None"], np.nan).fillna(race_meta[c])

    result = score_prediction(pred_df, cond_tbl, jockey_tbl, trainer_tbl)
except Exception as e:
    st.error(f"判定中にエラー: {e}")
    st.stop()

# サマリー
st.subheader("評価サマリー")
summary = result[result["評価"].astype(str) != ""].groupby("評価").agg(
    頭数=("馬名", "size"),
    平均ペーススコア=("ペーススコア", "mean"),
    平均開催週補正=("開催週ペース補正", "mean"),
    平均騎手点=("騎手ペース点", "mean"),
    平均調教師点=("調教師ペース点", "mean"),
).reset_index()
order = pd.CategoricalDtype(["S評価", "A評価", "B評価", "相手候補", "注意候補"], ordered=True)
if not summary.empty:
    summary["評価"] = summary["評価"].astype(order)
    summary = summary.sort_values("評価")
    for c in ["平均ペーススコア", "平均開催週補正", "平均騎手点", "平均調教師点"]:
        summary[c] = summary[c].round(1)
    st.dataframe(summary, use_container_width=True)
else:
    st.warning("評価対象馬がありませんでした。")

perf = summarize_results(result)
if not perf.empty:
    st.subheader("成績集計 ※着順・配当がある場合")
    st.dataframe(perf, use_container_width=True)

# 全頭ランキング画像風表示
st.subheader("全頭ランキング画像")
rank_groups = list(result.groupby(["日付", "場所", "R"], dropna=False))
for idx, ((dt, pl, rr), g) in enumerate(rank_groups):
    svg = make_ranking_svg(g, title="全頭ランキング")
    st.markdown(svg, unsafe_allow_html=True)
    st.download_button(
        f"{pl}{int(rr) if pd.notna(rr) else ''}R ランキングSVGを保存",
        data=svg.encode("utf-8"),
        file_name=f"全頭ランキング_{pl}_{int(rr) if pd.notna(rr) else ''}R.svg",
        mime="image/svg+xml",
        key=f"svg_download_{idx}",
    )

# レース別表示
st.subheader("レース別 推奨馬")
show_cols = [
    "日付", "場所", "R", "レース名", "馬番", "馬名", "騎手", "調教師",
    "評価", "判定理由",
    "ペース順位", "ペーススコア", "ペース基礎点", "開催週ペース補正",
    "開催日目", "開催週区分_使用", "簡易脚質",
    "今回ペース型", "騎手ペース点", "調教師ペース点",
    "前走RPCI", "前走PCI", "前走Ave3F", "前走上3F地点差", "前4角_使用", "前走頭数"
]
show_cols = [c for c in show_cols if c in result.columns]
recommended = result[result["評価"].astype(str) != ""].copy()
st.dataframe(recommended[show_cols], use_container_width=True, height=520)

with st.expander("全馬順位を見る", expanded=True):
    all_cols = show_cols.copy()
    st.dataframe(result[all_cols], use_container_width=True, height=600)

# ダウンロード
st.subheader("CSV保存")
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.download_button(
        "評価付き全馬CSVを保存",
        data=to_csv_bytes(result),
        file_name="新ペースロジック_全馬判定.csv",
        mime="text/csv",
    )
with col_b:
    st.download_button(
        "推奨馬CSVを保存",
        data=to_csv_bytes(recommended),
        file_name="新ペースロジック_推奨馬.csv",
        mime="text/csv",
    )
with col_c:
    if not perf.empty:
        st.download_button(
            "評価別成績CSVを保存",
            data=to_csv_bytes(perf),
            file_name="新ペースロジック_評価別成績.csv",
            mime="text/csv",
        )

st.caption("注：騎手70・調教師70は、過去データ内のペース型別成績をパーセンタイル化した信頼度です。開催週補正は最大±5点で、直線/ペース本体を大きく壊さない補助ロジックです。")
