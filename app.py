import io
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

st.set_page_config(page_title="重賞×直線 複合判定アプリ", page_icon="⭐", layout="wide")

st.title("⭐ 重賞フィルター × 直線ロジック 複合判定アプリ")
st.caption("2つのアプリのCSVを読み込み、共通キーで結合して最終判定を作成します。")

# -----------------------------
# Helpers
# -----------------------------

def read_csv_flexible(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    raw = uploaded_file.read()
    for enc in ["utf-8-sig", "utf-8", "cp932", "shift_jis"]:
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except Exception:
            pass
    # last resort
    return pd.read_csv(io.BytesIO(raw), encoding="cp932", errors="ignore")


def normalize_text(x) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    s = s.replace("　", " ")
    s = re.sub(r"\s+", "", s)
    return s


def normalize_r(x) -> str:
    s = normalize_text(x).upper()
    s = s.replace("Ｒ", "R")
    if s and not s.endswith("R") and s.isdigit():
        s = f"{int(s)}R"
    return s


def detect_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    norm_map = {normalize_text(c): c for c in cols}
    for cand in candidates:
        key = normalize_text(cand)
        if key in norm_map:
            return norm_map[key]
    for c in cols:
        nc = normalize_text(c)
        for cand in candidates:
            if normalize_text(cand) in nc:
                return c
    return None


def make_key(df: pd.DataFrame, mapping: Dict[str, Optional[str]], prefix: str) -> pd.Series:
    parts = []
    for logical in ["日付", "場所", "R", "レース名", "馬番", "馬名"]:
        col = mapping.get(logical)
        if col and col in df.columns:
            if logical == "R":
                parts.append(df[col].map(normalize_r))
            else:
                parts.append(df[col].map(normalize_text))
        else:
            parts.append(pd.Series([""] * len(df), index=df.index))
    # If 日付/場所/R are missing, still allow レース名+馬番+馬名 matching.
    return parts[0] + "|" + parts[1] + "|" + parts[2] + "|" + parts[3] + "|" + parts[4] + "|" + parts[5]


def to_num(s):
    return pd.to_numeric(s, errors="coerce")


def star_base_score(label: str, s_count=None, a_count=None, k_count=None) -> int:
    text = normalize_text(label)
    if any(x in text for x in ["危険", "消し"]):
        return -999
    if any(x in text for x in ["単独⭐", "単独星", "⭐", "星", "本命該当", "候補"]):
        # 準⭐を除外して単独寄りを優先
        if "準" not in text:
            return 70
    if "準" in text:
        return 55
    # fallback by counts
    try:
        s = float(s_count) if pd.notna(s_count) else 0
        a = float(a_count) if pd.notna(a_count) else 0
        k = float(k_count) if pd.notna(k_count) else 0
        if k > 0:
            return -999
        if s >= 3:
            return 70
        if s >= 2 or (s >= 1 and a >= 2):
            return 55
    except Exception:
        pass
    return 0


def straight_rank_score(rank: str, point=None, affinity: str = "") -> int:
    r = normalize_text(rank).upper()
    aff = normalize_text(affinity)
    # explicit rank
    if "S" == r or "Ｓ" == r or "S評価" in r:
        return 30
    if "A" == r or "Ａ" == r or "A評価" in r:
        return 25
    if "B" == r or "Ｂ" == r or "B評価" in r:
        return 15
    if "C" == r or "Ｃ" == r or "C評価" in r:
        return 5
    if "D" == r or "Ｄ" == r or "D評価" in r:
        return -10
    # affinity words
    if "かなり向く" in aff:
        return 30
    if "向く" in aff:
        return 25
    if "普通" in aff:
        return 15
    if "やや不向き" in aff:
        return 5
    if "不向き" in aff:
        return -10
    # numeric score fallback
    try:
        p = float(point)
        if p >= 85:
            return 30
        if p >= 75:
            return 25
        if p >= 65:
            return 15
        if p >= 55:
            return 5
        return -10
    except Exception:
        return 0


def straight_rank_label(score: int) -> str:
    if score >= 30:
        return "S"
    if score >= 25:
        return "A"
    if score >= 15:
        return "B"
    if score >= 5:
        return "C"
    if score < 0:
        return "D"
    return "未判定"


def final_label(star_score: int, straight_score: int, star_label: str) -> str:
    total = star_score + straight_score
    star_text = normalize_text(star_label)
    if star_score <= -999 or "危険" in star_text:
        return "危険⭐"
    if star_score >= 70 and straight_score >= 25:
        return "⭐S"
    if star_score >= 70 and straight_score >= 15:
        return "⭐A"
    if star_score >= 70 and straight_score < 5:
        return "危険⭐"
    if star_score >= 55 and straight_score >= 25:
        return "準⭐昇格"
    if star_score >= 55:
        return "準⭐"
    if star_score == 0 and straight_score >= 25:
        return "直線単独注目"
    if total >= 90:
        return "⭐S"
    if total >= 80:
        return "⭐A"
    return "見送り"


def comment(row) -> str:
    f = row.get("複合判定", "")
    if f == "⭐S":
        return "重賞傾向と直線条件が両方強く一致"
    if f == "⭐A":
        return "重賞傾向に該当し、直線も一定以上に合う"
    if f == "準⭐昇格":
        return "重賞側は準候補だが直線評価が高く昇格"
    if f == "準⭐":
        return "重賞側は準候補。相手・押さえ向き"
    if f == "危険⭐":
        return "重賞側は該当しても直線または消し条件に不安"
    if f == "直線単独注目":
        return "重賞フィルター外だが直線ロジックは高評価"
    return "複合条件では強調材料不足"


def csv_download(df: pd.DataFrame, filename: str, label: str):
    data = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, data=data, file_name=filename, mime="text/csv")

# -----------------------------
# Upload
# -----------------------------

with st.sidebar:
    st.header("CSVアップロード")
    star_file = st.file_uploader("① 重賞⭐️フィルターアプリの結果CSV", type=["csv"], key="star")
    straight_file = st.file_uploader("② 直線ロジックアプリの結果CSV", type=["csv"], key="straight")
    st.divider()
    st.caption("結合キーは基本：日付＋場所＋R＋レース名＋馬番＋馬名。列が無い場合はある列だけで補助結合します。")

star_df = read_csv_flexible(star_file) if star_file else pd.DataFrame()
straight_df = read_csv_flexible(straight_file) if straight_file else pd.DataFrame()

if star_df.empty or straight_df.empty:
    st.info("左のサイドバーから、重賞⭐️CSVと直線ロジックCSVをアップロードしてください。")
    st.stop()

st.subheader("1. 読み込み確認")
c1, c2 = st.columns(2)
with c1:
    st.write("重賞⭐️CSV")
    st.dataframe(star_df.head(10), use_container_width=True)
with c2:
    st.write("直線ロジックCSV")
    st.dataframe(straight_df.head(10), use_container_width=True)

# Auto mappings
common_candidates = {
    "日付": ["日付", "年月日", "date"],
    "場所": ["場所", "競馬場", "場", "開催"],
    "R": ["R", "Ｒ", "レース", "レース番号"],
    "レース名": ["レース名", "重賞名", "競走名"],
    "馬番": ["馬番", "番", "馬番号"],
    "馬名": ["馬名", "馬名S", "競走馬名"],
}
star_special = {
    "重賞判定": ["重賞判定", "判定", "フィルター判定", "最終判定", "⭐️判定", "星判定"],
    "S条件該当数": ["S条件該当数", "S該当数", "S条件数"],
    "A条件該当数": ["A条件該当数", "A該当数", "A条件数"],
    "消し条件数": ["消し条件数", "消し条件該当数", "消し該当数"],
}
straight_special = {
    "直線ランク": ["直線ランク", "ランク", "実力ランク", "相対ランク", "最終ランク", "評価"],
    "直線点": ["直線点", "最終点", "総合点", "点", "score", "前走直線ロジック点"],
    "直線相性評価": ["直線相性評価", "直線相性", "展開予想評価", "適性", "補正評価"],
}

star_map = {k: detect_col(star_df, v) for k, v in {**common_candidates, **star_special}.items()}
straight_map = {k: detect_col(straight_df, v) for k, v in {**common_candidates, **straight_special}.items()}

with st.expander("2. 列の自動判定・手動修正", expanded=False):
    st.write("必要に応じて列を選び直してください。")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("#### 重賞⭐️CSV")
        for k in star_map:
            options = [None] + list(star_df.columns)
            default = options.index(star_map[k]) if star_map[k] in options else 0
            star_map[k] = st.selectbox(f"重賞CSV：{k}", options, index=default, key=f"star_{k}")
    with cc2:
        st.markdown("#### 直線ロジックCSV")
        for k in straight_map:
            options = [None] + list(straight_df.columns)
            default = options.index(straight_map[k]) if straight_map[k] in options else 0
            straight_map[k] = st.selectbox(f"直線CSV：{k}", options, index=default, key=f"straight_{k}")

# Add keys
star_df = star_df.copy()
straight_df = straight_df.copy()
star_df["__key"] = make_key(star_df, star_map, "star")
straight_df["__key"] = make_key(straight_df, straight_map, "straight")

# Try full key merge, but if low match, try fallback keys
merged = star_df.merge(straight_df, on="__key", how="outer", suffixes=("_重賞", "_直線"), indicator=True)
match_rate = (merged["_merge"].eq("both").sum() / max(len(merged), 1))

if match_rate < 0.5:
    # fallback レース名+馬番+馬名
    def fallback_key(df, mp):
        parts = []
        for logical in ["レース名", "馬番", "馬名"]:
            col = mp.get(logical)
            if col and col in df.columns:
                parts.append(df[col].map(normalize_text))
            else:
                parts.append(pd.Series([""] * len(df), index=df.index))
        return parts[0] + "|" + parts[1] + "|" + parts[2]
    star_df["__key2"] = fallback_key(star_df, star_map)
    straight_df["__key2"] = fallback_key(straight_df, straight_map)
    merged2 = star_df.merge(straight_df, on="__key2", how="outer", suffixes=("_重賞", "_直線"), indicator=True)
    if merged2["_merge"].eq("both").sum() > merged["_merge"].eq("both").sum():
        merged = merged2
        key_used = "レース名＋馬番＋馬名"
    else:
        key_used = "日付＋場所＋R＋レース名＋馬番＋馬名"
else:
    key_used = "日付＋場所＋R＋レース名＋馬番＋馬名"

st.subheader("3. 結合結果")
mc1, mc2, mc3 = st.columns(3)
mc1.metric("結合できた行", int(merged["_merge"].eq("both").sum()))
mc2.metric("重賞CSVのみ", int(merged["_merge"].eq("left_only").sum()))
mc3.metric("直線CSVのみ", int(merged["_merge"].eq("right_only").sum()))
st.caption(f"使用キー：{key_used}")

# Compose output rows from merged both primarily, but include unmatched too
out = pd.DataFrame()

def pick_col(row, logical, side):
    mp = star_map if side == "star" else straight_map
    suffix = "_重賞" if side == "star" else "_直線"
    col = mp.get(logical)
    if not col:
        return ""
    c1 = col + suffix
    if c1 in row.index:
        return row.get(c1, "")
    return row.get(col, "")

rows = []
for _, row in merged.iterrows():
    base = {}
    for logical in ["日付", "場所", "R", "レース名", "馬番", "馬名"]:
        val = pick_col(row, logical, "star")
        if val == "" or pd.isna(val):
            val = pick_col(row, logical, "straight")
        base[logical] = val
    star_label = pick_col(row, "重賞判定", "star")
    s_count = pick_col(row, "S条件該当数", "star")
    a_count = pick_col(row, "A条件該当数", "star")
    k_count = pick_col(row, "消し条件数", "star")
    straight_rank = pick_col(row, "直線ランク", "straight")
    straight_point = pick_col(row, "直線点", "straight")
    straight_aff = pick_col(row, "直線相性評価", "straight")
    ss = star_base_score(star_label, s_count, a_count, k_count)
    ds = straight_rank_score(straight_rank, straight_point, straight_aff)
    total = ss + ds if ss > -999 else -999
    flabel = final_label(ss, ds, str(star_label))
    base.update({
        "重賞判定": star_label,
        "S条件該当数": s_count,
        "A条件該当数": a_count,
        "消し条件数": k_count,
        "重賞点": ss,
        "直線ランク": straight_rank if str(straight_rank).strip() else straight_rank_label(ds),
        "直線点": straight_point,
        "直線相性評価": straight_aff,
        "直線加点": ds,
        "複合点": total,
        "複合判定": flabel,
        "結合状態": row.get("_merge", ""),
    })
    base["複合コメント"] = comment(base)
    rows.append(base)

out = pd.DataFrame(rows)
order = {"⭐S": 0, "⭐A": 1, "準⭐昇格": 2, "準⭐": 3, "直線単独注目": 4, "危険⭐": 5, "見送り": 6}
out["__sort"] = out["複合判定"].map(order).fillna(9)
out = out.sort_values(["__sort", "複合点"], ascending=[True, False]).drop(columns=["__sort"])

st.subheader("4. 複合判定")
show_only = st.checkbox("結合できた馬だけ表示", value=True)
view = out[out["結合状態"].eq("both")] if show_only else out
st.dataframe(view, use_container_width=True, height=520)

best = view[view["複合判定"].isin(["⭐S", "⭐A", "準⭐昇格"])]
if not best.empty:
    top = best.iloc[0]
    st.success(f"最上位候補：{top.get('複合判定')}　{top.get('馬番', '')} {top.get('馬名', '')}　｜ {top.get('複合コメント', '')}")
else:
    st.warning("⭐S / ⭐A / 準⭐昇格はありません。今回は見送り寄りです。")

st.subheader("5. ダウンロード")
csv_download(out, "複合判定結果.csv", "複合判定結果CSVをダウンロード")

with st.expander("出力CSVの列"):
    st.code(",".join(out.columns), language="text")
