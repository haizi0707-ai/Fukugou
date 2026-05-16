# -*- coding: utf-8 -*-
"""
TARGET前走データ → 直線ロジック採点CSV変換アプリ
v3: ヘッダーなし / 今回のTARGET実出力順 / 手動列割当対応

実行:
    streamlit run app.py
"""

import io
import re
import unicodedata
from typing import Any, Optional, Tuple, List, Dict
import pandas as pd
import streamlit as st

OUTPUT_COLUMNS = [
    "日付","場所","芝ダ","距離","レース","レース名","馬番","馬名",
    "前走競馬場","前走芝ダ","前走距離数値","前走頭数",
    "前3角通過順","前4角通過順","前3角位置カテゴリ","前4角位置カテゴリ",
    "前走場所","前走直線ロジック点","前々走直線ロジック点",
    "展開予想評価","直線相性評価"
]

TRACK_CODE_MAP = {
    "東":"東京","中":"中山","京":"京都","阪":"阪神","名":"中京",
    "新":"新潟","福":"福島","小":"小倉","札":"札幌","函":"函館"
}
TRACK_STRAIGHT_TYPE = {
    "東京":"長い","新潟":"長い","中京":"長い",
    "阪神":"標準","京都":"標準",
    "中山":"短い","福島":"短い","小倉":"短い","札幌":"短い","函館":"短い",
}

PRESETS = {
    "今回推奨：TARGET実出力順21列": [
        "日付","場所","場R","芝ダ","距離","馬番","枠番","馬名","騎手","性齢","斤量",
        "前走場所","前芝ダ","前距離","前クラス","前頭数","前通過順",
        "前走着順","前走着差","前走馬場状態","前走上3F順位"
    ],
    "基本：日付場所場R+芝ダ距離一体20列": [
        "日付","場所","場R","芝ダ距離","レース名","馬番","馬名","枠番","騎手","斤量",
        "前走場所","前芝ダ","前距離","前クラス","前頭数","前通過順",
        "前走着順","前走着差","前走馬場状態","前走上3F順位"
    ],
    "短縮：場R統合18列": [
        "場R","芝ダ距離","レース名","馬番","馬名","枠番","騎手","斤量",
        "前走場所","前芝ダ","前距離","前クラス","前頭数","前通過順",
        "前走着順","前走着差","前走馬場状態","前走上3F順位"
    ],
}

REQUIRED_KEYS = [
    "日付","場所","場R","芝ダ","距離","芝ダ距離","レース名","馬番","馬名",
    "前走場所","前芝ダ","前距離","前クラス","前頭数","前通過順",
    "前走着順","前走着差","前走馬場状態","前走上3F順位"
]

def norm(x: Any) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return unicodedata.normalize("NFKC", str(x)).strip()

def to_int(x: Any, default: Optional[int]=None) -> Optional[int]:
    s = norm(x).replace(",", "")
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else default

def to_float(x: Any, default: Optional[float]=None) -> Optional[float]:
    s = norm(x).replace(",", "")
    if not s:
        return default
    if any(k in s for k in ["同","ハナ","クビ","アタマ","タイム差なし"]):
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else default

def normalize_place(x: Any) -> str:
    s = norm(x)
    for p in ["東京","中山","京都","阪神","中京","新潟","福島","小倉","札幌","函館"]:
        if p in s:
            return p
    for k, v in TRACK_CODE_MAP.items():
        if k in s:
            return v
    return s

def normalize_surface(x: Any) -> str:
    s = norm(x)
    if "ダ" in s or "D" in s.upper():
        return "ダ"
    if "芝" in s:
        return "芝"
    return ""

def parse_surface_distance(x: Any) -> Tuple[str, Optional[int]]:
    s = norm(x)
    return normalize_surface(s), to_int(s)

def parse_race_combo(x: Any) -> Tuple[str, str, str]:
    s = norm(x)
    date = ""
    place = ""
    race = ""

    m_date = re.search(r"\b(\d{6})\b", s)
    if m_date:
        yymmdd = m_date.group(1)
        date = f"{2000+int(yymmdd[:2])}.{int(yymmdd[2:4])}.{int(yymmdd[4:6])}"

    m_place = re.search(r"\d*([東中京阪名新福小札函])\d*", s)
    if m_place:
        place = TRACK_CODE_MAP.get(m_place.group(1), "")

    m_r = re.search(r"(\d{1,2})\s*R", s, flags=re.I)
    if m_r:
        race = f"{int(m_r.group(1))}R"

    return date, place, race

def parse_race_no(x: Any) -> str:
    s = norm(x)
    m = re.search(r"(\d{1,2})\s*R", s, flags=re.I)
    if m:
        return f"{int(m.group(1))}R"
    n = to_int(s)
    if n is not None and 1 <= n <= 12:
        return f"{n}R"
    return ""

def parse_passing(x: Any) -> Tuple[Optional[int], Optional[int]]:
    nums = [int(n) for n in re.findall(r"\d+", norm(x))]
    if len(nums) >= 2:
        return nums[-2], nums[-1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None

def position_category(order: Optional[int], field: Optional[int]) -> str:
    if order is None or field is None or field <= 0:
        return ""
    if order <= 1:
        return "1番手"
    r = order / field
    if r <= 0.25:
        return "2-3番手"
    if r <= 0.45:
        return "4-6番手"
    if r <= 0.85:
        return "7-10番手"
    return "11番手以下"

def style_from_pos(p4: Optional[int], field: Optional[int]) -> str:
    if p4 is None or field is None or field <= 0:
        return "不明"
    if p4 == 1:
        return "逃げ"
    r = p4 / field
    if r <= 0.25:
        return "先行"
    if r <= 0.45:
        return "好位"
    if r <= 0.75:
        return "差し"
    return "追込"

def race_flow(styles: List[str]) -> str:
    esc = styles.count("逃げ")
    front = styles.count("逃げ") + styles.count("先行")
    if esc == 0 and front <= 2:
        return "D"
    if esc == 1 and front <= 4:
        return "A"
    if front >= 6:
        return "C"
    return "B"

def dev_eval(style: str, flow: str) -> str:
    if style == "不明":
        return "普通"
    table = {
        "A":{"逃げ":"かなり向く","先行":"かなり向く","好位":"向く","差し":"普通","追込":"やや不向き"},
        "B":{"逃げ":"向く","先行":"向く","好位":"向く","差し":"普通","追込":"やや不向き"},
        "C":{"逃げ":"やや不向き","先行":"普通","好位":"向く","差し":"向く","追込":"普通"},
        "D":{"逃げ":"かなり向く","先行":"かなり向く","好位":"向く","差し":"やや不向き","追込":"不向き"},
    }
    return table.get(flow, {}).get(style, "普通")

def prev_score(finish, margin, p4, field, agari, prev_class, prev_surface, prev_dist, cur_surface, cur_dist, prev_track, cur_track, going) -> int:
    score = 50.0

    if finish is not None:
        if finish == 1:
            score += 18
        elif finish <= 3:
            score += 13
        elif finish <= 5:
            score += 8
        elif finish <= 8:
            score += 2
        else:
            score -= 6

    if margin is not None:
        if margin <= 0:
            score += 8
        elif margin <= 0.2:
            score += 6
        elif margin <= 0.5:
            score += 3
        elif margin <= 1.0:
            score -= 2
        elif margin <= 1.5:
            score -= 6
        else:
            score -= 10

    if p4 is not None and field:
        r = p4 / field
        if finish is not None:
            if r >= 0.65 and finish <= 5:
                score += 10
            elif r >= 0.45 and finish <= 3:
                score += 7
            elif r <= 0.25 and finish <= 3:
                score += 6
            elif r <= 0.45 and finish <= 5:
                score += 4
            if r >= 0.75 and finish >= 9:
                score -= 6

    if agari is not None:
        if agari == 1:
            score += 12
        elif agari <= 3:
            score += 9
        elif agari <= 5:
            score += 5
        elif agari <= 8:
            score += 1
        else:
            score -= 4

    cls = norm(prev_class)
    if any(k in cls for k in ["G1","GI","GⅠ","Ｇ１"]):
        score += 8
    elif any(k in cls for k in ["G2","GII","GⅡ","Ｇ２"]):
        score += 6
    elif any(k in cls for k in ["G3","GIII","GⅢ","Ｇ３"]):
        score += 4
    elif any(k in cls for k in ["OP","L","リステッド","オープン"]):
        score += 2

    if prev_surface and cur_surface and prev_surface != cur_surface:
        score -= 4

    if prev_dist and cur_dist:
        diff = abs(cur_dist - prev_dist)
        if diff <= 200:
            score += 4
        elif diff <= 400:
            score += 1
        elif diff >= 800:
            score -= 5

    pt = TRACK_STRAIGHT_TYPE.get(prev_track, "")
    ct = TRACK_STRAIGHT_TYPE.get(cur_track, "")
    if pt and ct:
        if pt == ct:
            score += 4
        elif pt == "短い" and ct == "長い":
            if p4 is not None and field and (p4 / field) >= 0.45 and finish is not None and finish <= 5:
                score += 5
            else:
                score -= 1
        elif pt == "長い" and ct == "短い":
            if p4 is not None and field and (p4 / field) <= 0.45 and finish is not None and finish <= 5:
                score += 3
            else:
                score -= 2

    if any(k in norm(going) for k in ["重","不良"]) and finish is not None and finish <= 3:
        score -= 1

    return int(max(0, min(100, round(score))))

def straight_eval(score: int, style: str, prev_track: str, cur_track: str, prev_dist, cur_dist) -> str:
    base = 2 if score >= 88 else 1 if score >= 75 else 0 if score >= 55 else -1 if score >= 40 else -2
    pt = TRACK_STRAIGHT_TYPE.get(prev_track, "")
    ct = TRACK_STRAIGHT_TYPE.get(cur_track, "")
    if pt and ct:
        if pt == ct:
            base += 1
        elif pt == "短い" and ct == "長い":
            base += 1 if style in ["差し","追込","好位"] else -1
        elif pt == "長い" and ct == "短い":
            base += 1 if style in ["逃げ","先行","好位"] else -1
    if prev_dist and cur_dist:
        diff = abs(cur_dist - prev_dist)
        if diff <= 200:
            base += 1
        elif diff >= 800:
            base -= 1
    base = max(-2, min(2, base))
    return {2:"かなり向く",1:"向く",0:"普通",-1:"やや不向き",-2:"不向き"}[base]

def read_csv_any(uploaded, header_mode: str, preset_cols: List[str]) -> pd.DataFrame:
    raw = uploaded.read()
    last = None
    for enc in ["utf-8-sig","cp932","shift_jis","utf-8"]:
        try:
            if header_mode == "ヘッダーあり":
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, header=None)
            cols = preset_cols[:len(df.columns)]
            if len(cols) < len(df.columns):
                cols += [f"未使用{i}" for i in range(len(df.columns)-len(cols))]
            df.columns = cols
            return df
        except Exception as e:
            last = e
    raise last

def get(row, col):
    if not col or col == "なし":
        return ""
    try:
        v = row[col]
        return "" if pd.isna(v) else v
    except Exception:
        return ""

def convert(df: pd.DataFrame, m: Dict[str,str], filter_7_12: bool):
    rows = []
    debug = []

    for _, row in df.iterrows():
        combo_date, combo_place, combo_race = parse_race_combo(get(row, m.get("場R")))

        date = norm(get(row, m.get("日付"))) or combo_date
        place = normalize_place(get(row, m.get("場所"))) or combo_place
        race = parse_race_no(get(row, m.get("場R"))) or combo_race

        cur_surface = ""
        cur_dist = None
        if m.get("芝ダ距離") and m.get("芝ダ距離") != "なし":
            cur_surface, cur_dist = parse_surface_distance(get(row, m.get("芝ダ距離")))
        else:
            cur_surface = normalize_surface(get(row, m.get("芝ダ")))
            cur_dist = to_int(get(row, m.get("距離")))

        race_num = to_int(race)
        if filter_7_12 and race_num is not None and not (7 <= race_num <= 12):
            continue

        prev_track = normalize_place(get(row, m.get("前走場所")))
        prev_surface = normalize_surface(get(row, m.get("前芝ダ")))
        prev_dist = to_int(get(row, m.get("前距離")))
        field = to_int(get(row, m.get("前頭数")))
        p3, p4 = parse_passing(get(row, m.get("前通過順")))
        finish = to_int(get(row, m.get("前走着順")))
        margin = to_float(get(row, m.get("前走着差")))
        agari = to_int(get(row, m.get("前走上3F順位")))
        style = style_from_pos(p4, field)

        base = {
            "日付": date,
            "場所": place,
            "芝ダ": cur_surface,
            "距離": cur_dist if cur_dist is not None else "",
            "レース": race,
            "レース名": norm(get(row, m.get("レース名"))),
            "馬番": to_int(get(row, m.get("馬番"))) or "",
            "馬名": norm(get(row, m.get("馬名"))),
            "前走競馬場": prev_track,
            "前走芝ダ": prev_surface,
            "前走距離数値": prev_dist if prev_dist is not None else "",
            "前走頭数": field if field is not None else "",
            "前3角通過順": p3 if p3 is not None else "",
            "前4角通過順": p4 if p4 is not None else "",
            "前3角位置カテゴリ": position_category(p3, field),
            "前4角位置カテゴリ": position_category(p4, field),
            "前走場所": prev_track,
            "_finish": finish,
            "_margin": margin,
            "_agari": agari,
            "_class": norm(get(row, m.get("前クラス"))),
            "_going": norm(get(row, m.get("前走馬場状態"))),
            "_style": style,
        }
        rows.append(base)

    flow = race_flow([r["_style"] for r in rows])
    out_rows = []
    for r in rows:
        score = prev_score(
            r["_finish"], r["_margin"],
            r["前4角通過順"] if isinstance(r["前4角通過順"], int) else None,
            r["前走頭数"] if isinstance(r["前走頭数"], int) else None,
            r["_agari"], r["_class"], r["前走芝ダ"],
            r["前走距離数値"] if isinstance(r["前走距離数値"], int) else None,
            r["芝ダ"], r["距離"] if isinstance(r["距離"], int) else None,
            r["前走競馬場"], r["場所"], r["_going"]
        )
        out = {k: r.get(k, "") for k in OUTPUT_COLUMNS}
        out["前走直線ロジック点"] = score
        out["前々走直線ロジック点"] = 0
        out["展開予想評価"] = dev_eval(r["_style"], flow)
        out["直線相性評価"] = straight_eval(
            score, r["_style"], r["前走競馬場"], r["場所"],
            r["前走距離数値"] if isinstance(r["前走距離数値"], int) else None,
            r["距離"] if isinstance(r["距離"], int) else None,
        )
        out_rows.append(out)
        debug.append({
            "日付": r["日付"], "場所": r["場所"], "R": r["レース"], "芝ダ": r["芝ダ"], "距離": r["距離"],
            "馬番": r["馬番"], "馬名": r["馬名"], "前走場所": r["前走場所"], "前距離": r["前走距離数値"],
            "前頭数": r["前走頭数"], "前通過": f'{r["前3角通過順"]}-{r["前4角通過順"]}',
            "脚質": r["_style"], "点": score,
            "展開": out["展開予想評価"], "直線": out["直線相性評価"]
        })

    return pd.DataFrame(out_rows, columns=OUTPUT_COLUMNS), pd.DataFrame(debug), flow

def csv_bytes(df):
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

st.set_page_config(page_title="TARGET直線ロジック採点 v3", page_icon="🏇", layout="wide")
st.title("🏇 TARGET前走データ → 直線ロジック採点CSV v3")
st.caption("今回のTARGET実出力順に対応。前々走直線ロジック点は0固定。")

uploaded = st.file_uploader("TARGETから出力した元CSVをアップロードしてください", type=["csv"])

c1, c2, c3 = st.columns(3)
with c1:
    header_mode = st.radio("CSV形式", ["ヘッダーなし", "ヘッダーあり"], index=0)
with c2:
    preset_name = st.selectbox("列順プリセット", list(PRESETS.keys()), index=0)
with c3:
    filter_7_12 = st.checkbox("7〜12Rのみ抽出", value=True)

st.info("今回の結果を見る限り、プリセットは **今回推奨：TARGET実出力順21列** が合う可能性が高いです。")

if uploaded:
    try:
        df = read_csv_any(uploaded, header_mode, PRESETS[preset_name])
    except Exception as e:
        st.error(f"CSVを読み込めませんでした: {e}")
        st.stop()

    st.subheader("① 読み込みプレビュー")
    st.write(f"行数: {len(df)} / 列数: {len(df.columns)}")
    st.dataframe(df.head(30), use_container_width=True)

    st.subheader("② 列割当")
    st.caption("ズレている場合は、ここで手動修正できます。特に 馬名・前走場所・前通過順 を確認してください。")
    cols = ["なし"] + list(df.columns)
    defaults = {
        "日付":"日付","場所":"場所","場R":"場R","芝ダ":"芝ダ","距離":"距離","芝ダ距離":"芝ダ距離","レース名":"レース名",
        "馬番":"馬番","馬名":"馬名","前走場所":"前走場所","前芝ダ":"前芝ダ","前距離":"前距離",
        "前クラス":"前クラス","前頭数":"前頭数","前通過順":"前通過順","前走着順":"前走着順",
        "前走着差":"前走着差","前走馬場状態":"前走馬場状態","前走上3F順位":"前走上3F順位",
    }

    mapping = {}
    grid = st.columns(4)
    for i, key in enumerate(REQUIRED_KEYS):
        default_col = defaults.get(key, "なし")
        default_idx = cols.index(default_col) if default_col in cols else 0
        with grid[i % 4]:
            mapping[key] = st.selectbox(key, cols, index=default_idx, key=f"map_{key}")

    out_df, debug_df, flow = convert(df, mapping, filter_7_12)

    st.subheader("③ 採点確認")
    flow_label = {"A":"A：単騎逃げ濃厚","B":"B：先行争い軽め","C":"C：先行争い激化","D":"D：逃げ馬不在スロー"}.get(flow, flow)
    st.info(flow_label)
    st.dataframe(debug_df, use_container_width=True)

    st.subheader("④ v12.2互換CSV")
    st.dataframe(out_df, use_container_width=True)

    blank = []
    for col in OUTPUT_COLUMNS:
        b = int(out_df[col].isna().sum() + (out_df[col].astype(str).str.strip() == "").sum())
        blank.append({"列名": col, "空欄数": b})
    st.subheader("⑤ 空欄チェック")
    st.dataframe(pd.DataFrame(blank), use_container_width=True)

    if len(out_df) == 0:
        st.error("出力対象が0行です。7〜12R抽出を外すか、場R列を確認してください。")
    else:
        st.download_button(
            "📥 v12.2互換CSVをダウンロード",
            data=csv_bytes(out_df),
            file_name="straight_logic_v12_2_input.csv",
            mime="text/csv",
        )
else:
    st.warning("変換済みCSVではなく、TARGETから出した元CSVをアップロードしてください。")
