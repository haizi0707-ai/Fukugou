# -*- coding: utf-8 -*-
"""
新ペースロジック判定アプリ vCOURSE_RACEINFO

同じフォルダに置く推奨ファイル:
- app.py
- ペース１０年.csv
- 調教師１０年.csv
- requirements.txt

対応:
- 出走馬データCSV
- TARGET出走馬HTML
- 今回レース情報CSV/HTML
- 開催日目/開催週区分/芝A-B-C-Dコース区分をペース基準に反映
- pandas.read_html は使わないため lxml 不要
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List

import numpy as np
import pandas as pd
import streamlit as st

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

APP_VERSION = "vCOURSE_RACEINFO_2026_05_20"

st.set_page_config(page_title="新ペースロジック判定アプリ", layout="wide")

APP_DIR = Path(__file__).resolve().parent
PACE_FILE_CANDIDATES = ["ペース１０年.csv", "ペース10年.csv", "pace_10years.csv", "pace.csv"]
TRAINER_FILE_CANDIDATES = ["調教師１０年.csv", "調教師10年.csv", "trainer_10years.csv", "trainer.csv"]


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


def decode_text_auto(raw: bytes) -> str:
    for enc in ["cp932", "shift_jis", "utf-8-sig", "utf-8"]:
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("cp932", errors="ignore")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rename = {}
    for c in df.columns:
        cc = str(c).strip()
        # レース基本
        if cc in ["Ｒ", "レース番号", "レース"]:
            rename[c] = "R"
        elif cc in ["場所名", "競馬場"]:
            rename[c] = "場所"
        elif cc in ["芝・ダ", "芝ダート", "芝ダ別", "トラック"]:
            rename[c] = "芝ダ"
        elif cc in ["馬場", "状"]:
            rename[c] = "馬場状態"
        elif cc in ["頭", "出走頭数", "頭数"]:
            rename[c] = "頭数"
        elif cc in ["区", "コース区", "コース区分", "コース", "コース替", "コース替り", "コース変わり"]:
            rename[c] = "コース区分"
        elif cc in ["開催日", "開催日目", "日目"]:
            rename[c] = "開催日目"
        # 走破・上がり
        elif cc == "走破タイム":
            rename[c] = "走破時計"
        elif cc == "前PCI":
            rename[c] = "前走PCI"
        elif cc == "前走Ave-3F":
            rename[c] = "前走Ave3F"
        elif cc == "Ave-3F":
            rename[c] = "Ave3F"
        elif cc in ["上り3F", "上3F"]:
            rename[c] = "上がり3F"
        elif cc in ["上り3F順", "3F順"]:
            rename[c] = "上がり3F順"
        elif cc in ["-3F差", "上3F地点差"]:
            rename[c] = "上3F地点差"
        # 配当
        elif cc in ["単配当", "単勝払戻", "単勝"]:
            rename[c] = "単勝配当"
        elif cc in ["複配当", "複勝払戻", "複勝"]:
            rename[c] = "複勝配当"
        else:
            rename[c] = cc
    return df.rename(columns=rename)


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


def normalize_baba(x: object) -> str:
    s = str(x).strip()
    if s in ["稍", "稍重"]:
        return "稍重"
    if s in ["良", "重", "不良"]:
        return s
    if "稍" in s:
        return "稍重"
    if "不" in s:
        return "不良"
    if "重" in s:
        return "重"
    if "良" in s:
        return "良"
    return s


def normalize_course_section(x: object, surface: object = None) -> str:
    """芝A/B/C/Dを正規化。ダートや不明は 区分なし。"""
    if surface is not None and normalize_surface(surface) == "ダ":
        return "区分なし"
    if pd.isna(x):
        return "区分なし"
    s = str(x).strip().upper().translate(str.maketrans("ＡＢＣＤ", "ABCD"))
    m = re.search(r"[ABCD]", s)
    return m.group(0) if m else "区分なし"


def finish_to_int(x) -> float:
    if pd.isna(x):
        return np.nan
    s = str(x).strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
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


def parse_corner_from_passage(x) -> float:
    if pd.isna(x):
        return np.nan
    s = str(x).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    nums = re.findall(r"\d+", s)
    return float(nums[-1]) if nums else np.nan


def _get_first_existing(row: pd.Series, names: list[str]):
    for name in names:
        if name in row.index:
            v = row.get(name)
            if not (pd.isna(v) if not isinstance(v, str) else str(v).strip() == ""):
                return v
    return np.nan


def extract_kaisai_day(x) -> float:
    """
    TARGETの開催表記から開催日目を取る。
    例: 2阪5 -> 5、1東2 -> 2、4中9 -> 9
    """
    if pd.isna(x):
        return np.nan
    s = str(x).strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    # 「2阪5」「1東京2」など末尾数字を採用
    m = re.search(r"(\d+)\s*$", s)
    return float(m.group(1)) if m else np.nan


def week_bucket(day) -> str:
    try:
        d = int(float(day))
    except Exception:
        return "不明"
    if d <= 2:
        return "開幕週"
    if d <= 4:
        return "開催前半"
    if d <= 6:
        return "開催中盤"
    if d <= 8:
        return "開催後半"
    return "最終週"


def html_tables_no_lxml(text: str) -> List[pd.DataFrame]:
    """BeautifulSoupだけでHTMLテーブルをDataFrame化。pandas.read_html/lxmlは使わない。"""
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(text, "html.parser")
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            vals = [c.get_text(" ", strip=True).replace("\xa0", " ") for c in cells]
            if vals:
                rows.append(vals)
        if len(rows) < 2:
            continue
        header = rows[0]
        data = rows[1:]
        width = len(header)
        fixed = []
        for r in data:
            if len(r) < width:
                r = r + [""] * (width - len(r))
            elif len(r) > width:
                r = r[:width]
            fixed.append(r)
        tables.append(pd.DataFrame(fixed, columns=header))
    return tables


# ============================================================
# TARGET HTML抽出
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
    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else Path(uploaded_file).read_bytes()
    text = decode_text_auto(raw)
    headers = extract_horse_headers_from_target_html(text)
    tables = html_tables_no_lxml(text)

    rows = []
    n = min(len(headers), len(tables)) if headers else len(tables)
    for i in range(n):
        info = headers[i] if i < len(headers) else {}
        tbl = normalize_columns(tables[i].copy())
        if tbl.empty:
            continue

        if "走前" in tbl.columns:
            tmp = tbl.copy()
            tmp["走前_num"] = pd.to_numeric(tmp["走前"], errors="coerce")
            prev = tmp[tmp["走前_num"] == 1]
            r = (prev.iloc[0] if not prev.empty else tbl.iloc[0])
        else:
            r = tbl.iloc[0]

        passage = _get_first_existing(r, ["通過順", "通過順1-4", "通過順１－４"])
        prev4 = parse_corner_from_passage(passage)

        row = {
            # 今回レース情報
            "日付": race_meta.get("日付", ""),
            "場所": race_meta.get("場所", ""),
            "R": race_meta.get("R", np.nan),
            "レース名": race_meta.get("レース名", ""),
            "芝ダ": race_meta.get("芝ダ", ""),
            "距離": race_meta.get("距離", np.nan),
            "馬場状態": race_meta.get("馬場状態", "良"),
            "頭数": race_meta.get("頭数", len(headers) if headers else np.nan),
            "開催日目": race_meta.get("開催日目", np.nan),
            "開催週区分": race_meta.get("開催週区分", "不明"),
            "コース区分": race_meta.get("コース区分", "区分なし"),
            # 馬情報
            "馬番": info.get("馬番", _get_first_existing(r, ["番", "馬番"])),
            "馬名": info.get("馬名", _get_first_existing(r, ["馬名"])),
            "騎手": info.get("騎手", _get_first_existing(r, ["騎手"])),
            "調教師": info.get("調教師", _get_first_existing(r, ["調教師"])),
            "斤量": info.get("斤量", _get_first_existing(r, ["斤量"])),
            # 前走情報
            "前走頭数": _get_first_existing(r, ["頭", "R頭", "頭数"]),
            "前4角": prev4,
            "前走RPCI": _get_first_existing(r, ["RPCI", "前走RPCI"]),
            "前走PCI": _get_first_existing(r, ["PCI", "前走PCI"]),
            "前走PCI3": _get_first_existing(r, ["PCI3", "前走PCI3"]),
            "前走Ave3F": _get_first_existing(r, ["Ave3F", "前走Ave3F"]),
            "前走上3F地点差": _get_first_existing(r, ["上3F地点差", "前走上3F地点差"]),
            "前走上3F": _get_first_existing(r, ["上がり3F", "前走上3F"]),
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
            "前走場所": _get_first_existing(r, ["場所"]),
            "前走距離": _get_first_existing(r, ["距離"]),
            "前走芝ダ": _get_first_existing(r, ["TR", "芝ダ"]),
            "前走馬場状態": _get_first_existing(r, ["馬場状態"]),
            "前走開催": _get_first_existing(r, ["開催"]),
            "前走コース区分": _get_first_existing(r, ["コース区分"]),
        }
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    for c in [
        "R", "距離", "頭数", "馬番", "前走頭数", "前4角",
        "前走RPCI", "前走PCI", "前走PCI3", "前走Ave3F",
        "前走上3F地点差", "前走上3F", "開催日目"
    ]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


# ============================================================
# 今回レース情報ファイル
# ============================================================

def parse_race_info_file(uploaded_file) -> dict:
    """
    今回レース情報CSV/HTMLから、日付/場所/R/芝ダ/距離/馬場/開催日目/コース区分などを抽出。
    CSVは1行目または該当行を使用。HTMLはテキストからできる範囲で抽出。
    """
    if uploaded_file is None:
        return {}

    name = getattr(uploaded_file, "name", "").lower()
    meta = {}

    try:
        if name.endswith(".csv"):
            df = prep_common(read_csv_auto(uploaded_file))
            if df.empty:
                return {}
            # 基本は最初の行。複数行なら7〜12Rや指定レースが含まれてもまず先頭を採用。
            r = df.iloc[0]
            for col in ["日付", "場所", "R", "レース名", "芝ダ", "距離", "馬場状態", "頭数", "開催日目", "開催週区分", "コース区分", "開催"]:
                if col in df.columns:
                    meta[col] = r.get(col)
        else:
            raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else Path(uploaded_file).read_bytes()
            text = decode_text_auto(raw)
            clean = re.sub(r"\s+", " ", BeautifulSoup(text, "html.parser").get_text(" ", strip=True) if BeautifulSoup else text)
            # TITLE/本文から拾える範囲
            m = re.search(r"(\d{4})[./年]\s*(\d{1,2})[./月]\s*(\d{1,2})", clean)
            if m:
                meta["日付"] = f"{m.group(1)}.{int(m.group(2))}.{int(m.group(3))}"
            for place in ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]:
                if place in clean:
                    meta["場所"] = place
                    break
            m = re.search(r"(\d{1,2})R", clean, flags=re.I)
            if m:
                meta["R"] = int(m.group(1))
            m = re.search(r"(芝|ダート|ダ)\s*(\d{3,4})", clean)
            if m:
                meta["芝ダ"] = normalize_surface(m.group(1))
                meta["距離"] = int(m.group(2))
            m = re.search(r"(良|稍重|稍|重|不良)", clean)
            if m:
                meta["馬場状態"] = normalize_baba(m.group(1))
            m = re.search(r"([1-9]\d*)\s*頭", clean)
            if m:
                meta["頭数"] = int(m.group(1))
            m = re.search(r"([1-9]\d*)\s*日目", clean)
            if m:
                meta["開催日目"] = int(m.group(1))
            m = re.search(r"([ABCDＡＢＣＤ])\s*コース", clean, flags=re.I)
            if m:
                meta["コース区分"] = normalize_course_section(m.group(1), meta.get("芝ダ"))
            m = re.search(r"([1-9]\d*)[^\s]{0,3}(札|函|福|新|東|中|名|京|阪|小)[^\s]{0,3}([1-9]\d*)", clean)
            if m and "開催日目" not in meta:
                meta["開催日目"] = int(m.group(3))
    except Exception:
        return {}

    return normalize_race_meta(meta)


def normalize_race_meta(meta: dict) -> dict:
    out = dict(meta)
    if "R" in out:
        out["R"] = normalize_race_no(out["R"])
    if "芝ダ" in out:
        out["芝ダ"] = normalize_surface(out["芝ダ"])
    if "馬場状態" in out:
        out["馬場状態"] = normalize_baba(out["馬場状態"])
    if "距離" in out:
        out["距離"] = pd.to_numeric(out["距離"], errors="coerce")
    if "頭数" in out:
        out["頭数"] = pd.to_numeric(out["頭数"], errors="coerce")
    if "開催日目" not in out or pd.isna(out.get("開催日目")):
        if "開催" in out:
            out["開催日目"] = extract_kaisai_day(out.get("開催"))
    if "開催日目" in out:
        out["開催日目"] = pd.to_numeric(out.get("開催日目"), errors="coerce")
        out["開催週区分"] = week_bucket(out.get("開催日目"))
    else:
        out["開催週区分"] = out.get("開催週区分", "不明")
    out["コース区分"] = normalize_course_section(out.get("コース区分", out.get("区", np.nan)), out.get("芝ダ"))
    return out


def load_prediction_input(uploaded_file, race_meta: dict) -> pd.DataFrame:
    name = getattr(uploaded_file, "name", "").lower()
    if name.endswith(".html") or name.endswith(".htm"):
        return read_target_html_prediction(uploaded_file, race_meta)
    df = read_csv_auto(uploaded_file)
    df = normalize_columns(df)
    # CSV内に無い今回レース情報はrace_metaで補完
    for k, v in race_meta.items():
        if k not in df.columns or df[k].isna().all() or (df[k].astype(str).str.strip() == "").all():
            df[k] = v
    return df


# ============================================================
# 前処理
# ============================================================

def prep_common(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)
    if "R" in df.columns:
        df["R"] = df["R"].apply(normalize_race_no)
    for c in ["日付", "場所", "レース名", "馬名", "騎手", "調教師"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    if "芝ダ" in df.columns:
        df["芝ダ"] = df["芝ダ"].apply(normalize_surface)
    if "馬場状態" in df.columns:
        df["馬場状態"] = df["馬場状態"].apply(normalize_baba)
    if "開催日目" not in df.columns:
        df["開催日目"] = np.nan
    if "開催" in df.columns:
        df["開催日目"] = df["開催日目"].fillna(df["開催"].apply(extract_kaisai_day))
    df["開催週区分"] = df["開催日目"].apply(week_bucket)
    if "コース区分" not in df.columns:
        df["コース区分"] = np.nan
    if "芝ダ" in df.columns:
        df["コース区分"] = [normalize_course_section(c, s) for c, s in zip(df["コース区分"], df["芝ダ"])]
    else:
        df["コース区分"] = df["コース区分"].apply(normalize_course_section)

    numeric_cols = [
        "距離", "頭数", "馬番", "前走RPCI", "前走PCI", "前走Ave3F",
        "前走上3F地点差", "前走頭数", "開催日目",
        "RPCI", "PCI", "Ave3F", "上3F地点差", "3角", "4角", "3角.1", "4角.1", "上がり3F"
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = to_num(df[c])
    if "着順" in df.columns:
        df["着順数値"] = df["着順"].apply(finish_to_int)
    elif "着" in df.columns:
        df["着順数値"] = df["着"].apply(finish_to_int)
    return df


def choose_prev_corner_col(df: pd.DataFrame, base: str) -> Optional[str]:
    for c in [base, f"{base}.1"]:
        if c in df.columns and df[c].notna().sum() > 0:
            return c
    return None


# ============================================================
# 過去データから基準表を作る
# ============================================================

def make_condition_table(top3: pd.DataFrame, group_cols: list[str], name: str) -> pd.DataFrame:
    agg_dict = {
        "条件件数": ("馬名", "size"),
        "基準RPCI": ("RPCI", "mean"),
        "基準PCI": ("PCI", "mean"),
        "基準Ave3F": ("Ave3F", "mean"),
        "基準上3F地点差": ("上3F地点差", "mean"),
        "基準四角率": ("四角率", "mean"),
    }
    if "上がり3F" in top3.columns:
        agg_dict["基準上がり3F"] = ("上がり3F", "mean")
    out = top3.groupby(group_cols, dropna=False).agg(**agg_dict).reset_index()
    out["基準使用区分"] = name
    out.attrs["group_cols"] = group_cols
    return out


@st.cache_data(show_spinner=False)
def build_reference_tables(pace_df: pd.DataFrame, trainer_df: pd.DataFrame) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
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

    condition_tables = {
        "週区分+コース": make_condition_table(top3, ["場所", "芝ダ", "距離", "馬場状態", "開催週区分", "コース区分"], "週区分+コース"),
        "コース": make_condition_table(top3, ["場所", "芝ダ", "距離", "馬場状態", "コース区分"], "コース"),
        "週区分": make_condition_table(top3, ["場所", "芝ダ", "距離", "馬場状態", "開催週区分"], "週区分"),
        "馬場": make_condition_table(top3, ["場所", "芝ダ", "距離", "馬場状態"], "馬場"),
        "基本": make_condition_table(top3, ["場所", "芝ダ", "距離"], "基本"),
    }

    # 騎手: ペース型ごとの好走率
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

    # 調教師: ペース型ごとの好走率
    if not trainer.empty and "調教師" in trainer.columns:
        key = ["日付", "場所", "R", "馬番", "馬名"]
        merge_cols = [c for c in key if c in pace.columns and c in trainer.columns]
        if len(merge_cols) >= 4:
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

    return condition_tables, j, tr


# ============================================================
# 予想データを判定
# ============================================================

def attach_condition_reference(pred: pd.DataFrame, condition_tables: Dict[str, pd.DataFrame], min_count: int = 30) -> pd.DataFrame:
    out = pred.copy()
    # 初期化
    for c in ["条件件数", "基準RPCI", "基準PCI", "基準Ave3F", "基準上3F地点差", "基準四角率", "基準使用区分"]:
        out[c] = np.nan if c != "基準使用区分" else ""

    # 詳細→粗い順に埋める
    for name in ["週区分+コース", "コース", "週区分", "馬場", "基本"]:
        tbl = condition_tables.get(name)
        if tbl is None or tbl.empty:
            continue
        group_cols = tbl.attrs.get("group_cols", [])
        tmp = out.merge(tbl, on=group_cols, how="left", suffixes=("", "_new"))
        # 条件件数がmin_count以上、または最後の基本なら採用
        use = out["基準RPCI"].isna() & tmp["基準RPCI_new"].notna()
        if name != "基本":
            use = use & (tmp["条件件数_new"].fillna(0) >= min_count)
        for col in ["条件件数", "基準RPCI", "基準PCI", "基準Ave3F", "基準上3F地点差", "基準四角率", "基準使用区分"]:
            new_col = f"{col}_new"
            if new_col in tmp.columns:
                out.loc[use, col] = tmp.loc[use, new_col]
    return out


def score_prediction(pred_df: pd.DataFrame, condition_tables: Dict[str, pd.DataFrame], jockey_tbl: pd.DataFrame, trainer_tbl: pd.DataFrame) -> pd.DataFrame:
    df = prep_common(pred_df)

    if "R" in df.columns:
        df = df[df["R"].between(7, 12)].copy()

    for c in ["前走RPCI", "前走PCI", "前走Ave3F", "前走上3F地点差", "前走頭数", "騎手", "調教師"]:
        if c not in df.columns:
            df[c] = np.nan

    prev4 = choose_prev_corner_col(df, "前4角")
    df["前4角_使用"] = to_num(df[prev4]) if prev4 else np.nan
    df["前4角率"] = df.apply(lambda r: safe_div(r.get("前4角_使用"), r.get("前走頭数")), axis=1)

    df = attach_condition_reference(df, condition_tables, min_count=30)
    df["今回ペース型"] = df["基準RPCI"].apply(pace_type_from_rpci)

    df["RPCI一致点"] = [score_fit(v, t, 5.0, 60) for v, t in zip(df["前走RPCI"], df["基準RPCI"])]
    df["PCI一致点"] = [score_fit(v, t, 4.0, 60) for v, t in zip(df["前走PCI"], df["基準PCI"])]
    df["Ave3F一致点"] = [score_fit(v, t, 12.0, 60) for v, t in zip(df["前走Ave3F"], df["基準Ave3F"])]
    df["上3F地点差一致点"] = [score_fit(v, t, 25.0, 60) for v, t in zip(df["前走上3F地点差"], df["基準上3F地点差"])]
    df["位置一致点"] = [score_fit(v, t, 120.0, 60) for v, t in zip(df["前4角率"], df["基準四角率"])]

    df["ペーススコア"] = (
        df["RPCI一致点"] * 0.35 +
        df["PCI一致点"] * 0.15 +
        df["Ave3F一致点"] * 0.20 +
        df["上3F地点差一致点"] * 0.10 +
        df["位置一致点"] * 0.20
    ).round(1)

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
        if r.get("騎手ペース点", 0) >= 70:
            parts.append("騎手70+")
        if r.get("調教師ペース点", 0) >= 70:
            parts.append("調教師70+")
        if r.get("基準使用区分", ""):
            parts.append(f"基準:{r.get('基準使用区分')}")
        return " / ".join(parts)

    df["判定理由"] = df.apply(comment_row, axis=1)
    return df.sort_values(["日付", "場所", "R", "ペース順位", "馬番"]).reset_index(drop=True)


# ============================================================
# 成績集計
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
    for label in ["S評価", "A評価", "B評価", "相手候補", "注意候補"]:
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

st.title("新ペースロジック判定アプリ vCOURSE_RACEINFO")
st.caption(f"起動中バージョン：{APP_VERSION}")
st.caption("ペース基準に 開催週区分＋芝A/B/C/Dコース区分 を反映。今回レース情報CSV/HTMLの別アップロードに対応。")
st.caption("pandas.read_html は使っていません。lxml不要です。")

with st.expander("評価ルール", expanded=False):
    st.markdown(
        """
- **S評価**：ペース1位 ＋ 騎手ペース70以上 ＋ 調教師ペース70以上
- **A評価**：ペース1位 ＋ 騎手70以上 or 調教師70以上
- **B評価**：ペース1位のみ
- **相手候補**：ペース2〜3位 ＋ 騎手70以上
- **注意候補**：ペース2〜3位 ＋ 調教師70以上

基準の優先順位：
1. 場所×芝ダ×距離×馬場状態×開催週区分×コース区分  
2. 場所×芝ダ×距離×馬場状態×コース区分  
3. 場所×芝ダ×距離×馬場状態×開催週区分  
4. 場所×芝ダ×距離×馬場状態  
5. 場所×芝ダ×距離  
        """
    )

st.subheader("入力ファイル")
col1, col2 = st.columns(2)
with col1:
    horse_file = st.file_uploader(
        "① 出走馬データをアップロード（TARGET HTML / CSV）",
        type=None,
        key="horse_file",
        help="TARGETの馬ごとHTML、または出走馬CSVを入れます。",
    )
with col2:
    race_info_file = st.file_uploader(
        "② 今回レース情報をアップロード（CSV / HTML 任意）",
        type=None,
        key="race_info_file",
        help="開催日目、A/B/C/Dコース、馬場状態、距離などが入ったファイル。無ければ下の手入力を使います。",
    )

col3, col4 = st.columns(2)
with col3:
    pace_upload = st.file_uploader("ペース10年CSV 任意", type=["csv"], key="pace")
with col4:
    trainer_upload = st.file_uploader("調教師10年CSV 任意", type=["csv"], key="trainer")

st.subheader("今回レース条件 手入力・補完")
st.caption("②のレース情報ファイルに項目がある場合は自動優先。不足分だけここを使います。")
m1, m2, m3, m4 = st.columns(4)
with m1:
    meta_date = st.text_input("日付", value="2026.5.18")
    meta_place = st.text_input("場所", value="東京")
with m2:
    meta_r = st.number_input("R", min_value=1, max_value=12, value=11, step=1)
    meta_name = st.text_input("レース名", value="ヴィクトリアマイル")
with m3:
    meta_surface = st.selectbox("芝ダ", options=["芝", "ダ"], index=0)
    meta_distance = st.number_input("距離", min_value=800, max_value=4000, value=1600, step=100)
with m4:
    meta_baba = st.selectbox("馬場状態", options=["良", "稍重", "重", "不良"], index=0)
    meta_heads = st.number_input("頭数", min_value=1, max_value=30, value=18, step=1)

m5, m6 = st.columns(2)
with m5:
    meta_day = st.number_input("開催日目", min_value=1, max_value=12, value=2, step=1)
with m6:
    meta_course = st.selectbox("コース区分", options=["A", "B", "C", "D", "区分なし"], index=0)

manual_meta = {
    "日付": meta_date,
    "場所": meta_place,
    "R": int(meta_r),
    "レース名": meta_name,
    "芝ダ": meta_surface,
    "距離": int(meta_distance),
    "馬場状態": meta_baba,
    "頭数": int(meta_heads),
    "開催日目": int(meta_day),
    "開催週区分": week_bucket(meta_day),
    "コース区分": meta_course if meta_surface == "芝" else "区分なし",
}

file_meta = parse_race_info_file(race_info_file) if race_info_file is not None else {}
race_meta = manual_meta.copy()
for k, v in file_meta.items():
    if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != "":
        race_meta[k] = v
race_meta = normalize_race_meta(race_meta)

with st.expander("今回レース情報の最終反映内容", expanded=True):
    def _json_safe(v):
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        if isinstance(v, np.generic):
            return v.item()
        return v
    st.json({k: _json_safe(v) for k, v in race_meta.items()})

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
    condition_tables, jockey_tbl, trainer_tbl = build_reference_tables(pace_df, trainer_df)
except Exception as e:
    st.error(f"基準表の作成でエラー: {e}")
    st.stop()

st.success(
    "基準表作成完了："
    + " / ".join([f"{k}:{len(v):,}件" for k, v in condition_tables.items()])
    + f" / 騎手:{len(jockey_tbl):,}件 / 調教師:{len(trainer_tbl):,}件"
)

if horse_file is None:
    st.warning("まず ① 出走馬データ（TARGET HTML / CSV）をアップロードしてください。")
    st.stop()

try:
    pred_df = load_prediction_input(horse_file, race_meta)
    if pred_df.empty:
        st.error("出走馬データから馬データを読み取れませんでした。")
        st.stop()
    result = score_prediction(pred_df, condition_tables, jockey_tbl, trainer_tbl)
except Exception as e:
    st.error(f"判定中にエラー: {e}")
    st.exception(e)
    st.stop()

st.subheader("評価サマリー")
summary = result[result["評価"].astype(str) != ""].groupby("評価").agg(
    頭数=("馬名", "size"),
    平均ペーススコア=("ペーススコア", "mean"),
    平均騎手点=("騎手ペース点", "mean"),
    平均調教師点=("調教師ペース点", "mean"),
).reset_index()
order = pd.CategoricalDtype(["S評価", "A評価", "B評価", "相手候補", "注意候補"], ordered=True)
if not summary.empty:
    summary["評価"] = summary["評価"].astype(order)
    summary = summary.sort_values("評価")
    for c in ["平均ペーススコア", "平均騎手点", "平均調教師点"]:
        summary[c] = summary[c].round(1)
    st.dataframe(summary, use_container_width=True)
else:
    st.warning("評価対象馬がありませんでした。")

perf = summarize_results(result)
if not perf.empty:
    st.subheader("成績集計 ※着順・配当がある場合")
    st.dataframe(perf, use_container_width=True)

st.subheader("レース別 推奨馬")
show_cols = [
    "日付", "場所", "R", "レース名", "開催日目", "開催週区分", "コース区分",
    "馬番", "馬名", "騎手", "調教師", "評価", "判定理由",
    "ペース順位", "ペーススコア", "今回ペース型",
    "基準使用区分", "条件件数",
    "騎手ペース点", "調教師ペース点",
    "前走RPCI", "前走PCI", "前走Ave3F", "前走上3F地点差", "前4角_使用", "前走頭数"
]
show_cols = [c for c in show_cols if c in result.columns]
recommended = result[result["評価"].astype(str) != ""].copy()
st.dataframe(recommended[show_cols], use_container_width=True, height=520)

with st.expander("全馬順位を見る", expanded=False):
    st.dataframe(result[show_cols], use_container_width=True, height=600)

st.subheader("CSV保存")
c1, c2, c3 = st.columns(3)
with c1:
    st.download_button(
        "評価付き全馬CSVを保存",
        data=to_csv_bytes(result),
        file_name="新ペースロジック_全馬判定.csv",
        mime="text/csv",
    )
with c2:
    st.download_button(
        "推奨馬CSVを保存",
        data=to_csv_bytes(recommended),
        file_name="新ペースロジック_推奨馬.csv",
        mime="text/csv",
    )
with c3:
    if not perf.empty:
        st.download_button(
            "評価別成績CSVを保存",
            data=to_csv_bytes(perf),
            file_name="新ペースロジック_評価別成績.csv",
            mime="text/csv",
        )

st.caption("注：詳細条件の母数が30件未満の場合は、自動で粗い条件へフォールバックします。")
