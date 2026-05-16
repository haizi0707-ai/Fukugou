# -*- coding: utf-8 -*-
"""
TARGET直線ロジック採点アプリ
５．１６直線２.csv 実データ列順対応版

実行:
    streamlit run app.py

今回の更新点:
- ５．１６直線２.csv の37列に対応
- 追加された「前頭数」を実数として使用
- 前3角/前4角が空欄の馬は空欄扱いのまま出力
- 前々走直線ロジック点は 0 固定
- オッズ、人気、予想印、AI指数は使用しません
"""

import io
import re
import unicodedata
from typing import Any, Optional, Tuple, List, Dict

import pandas as pd
import streamlit as st


# =========================================================
# v12.2互換 出力列
# =========================================================

OUTPUT_COLUMNS = [
    "日付",
    "場所",
    "芝ダ",
    "距離",
    "レース",
    "レース名",
    "馬番",
    "馬名",
    "前走競馬場",
    "前走芝ダ",
    "前走距離数値",
    "前走頭数",
    "前3角通過順",
    "前4角通過順",
    "前3角位置カテゴリ",
    "前4角位置カテゴリ",
    "前走場所",
    "前走直線ロジック点",
    "前々走直線ロジック点",
    "展開予想評価",
    "直線相性評価",
]


# =========================================================
# 今回のTARGET実CSV列順 37列
# =========================================================
# ５．１６直線２.csv を確認した実列順です。
#
# 0  日付
# 1  場所
# 2  場R
# 3  芝ダ
# 4  距離
# 5  レース名
# 6  馬番
# 7  馬名
# 8  枠番
# 9  騎手
# 10 斤量
# 11 性別
# 12 年齢
# 13 前走場所
# 14 前走同場/別場/前無
# 15 前芝ダ
# 16 前走芝ダ系1
# 17 前走芝ダ系2
# 18 前距離
# 19 前クラス
# 20 前1角
# 21 前2角
# 22 前3角
# 23 前4角
# 24 前走着順
# 25 前走着差
# 26 前走馬場状態
# 27 前走上3F順位
# 28 前走開催R
# 29 前走騎手
# 30 前走斤量
# 31 前走馬体重
# 32 前走馬体重増減
# 33 前走人気らしき列 ※不使用
# 34 空列
# 35 空列
# 36 前頭数 ← 今回追加された列

TARGET_COLUMNS_37 = [
    "日付_raw",
    "場所",
    "場R",
    "芝ダ",
    "距離",
    "レース名",
    "馬番",
    "馬名",
    "枠番",
    "騎手",
    "斤量",
    "性別",
    "年齢",
    "前走場所",
    "前走場替",
    "前芝ダ",
    "前芝ダ_補助1",
    "前芝ダ_補助2",
    "前距離",
    "前クラス",
    "前1角",
    "前2角",
    "前3角",
    "前4角",
    "前走着順",
    "前走着差",
    "前走馬場状態",
    "前走上3F順位",
    "前走開催R",
    "前走騎手",
    "前走斤量",
    "前走馬体重",
    "前走馬体重増減",
    "前走人気_不使用",
    "空列1",
    "空列2",
    "前頭数",
]


TRACK_STRAIGHT_TYPE = {
    "東京": "長い",
    "新潟": "長い",
    "中京": "長い",
    "阪神": "標準",
    "京都": "標準",
    "中山": "短い",
    "福島": "短い",
    "小倉": "短い",
    "札幌": "短い",
    "函館": "短い",
}

TRACK_CODE_MAP = {
    "東": "東京",
    "中": "中山",
    "京": "京都",
    "阪": "阪神",
    "名": "中京",
    "新": "新潟",
    "福": "福島",
    "小": "小倉",
    "札": "札幌",
    "函": "函館",
}


# =========================================================
# 基本関数
# =========================================================

def norm(x: Any) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return unicodedata.normalize("NFKC", str(x)).strip()


def to_int(x: Any, default: Optional[int] = None) -> Optional[int]:
    s = norm(x).replace(",", "")
    m = re.search(r"-?\d+", s)
    if not m:
        return default
    try:
        return int(float(m.group()))
    except Exception:
        return default


def to_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    s = norm(x).replace(",", "")
    if not s:
        return default
    if any(k in s for k in ["同", "タイム差なし", "ハナ", "クビ", "アタマ"]):
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return default
    try:
        return float(m.group())
    except Exception:
        return default


def normalize_place(x: Any) -> str:
    s = norm(x)
    for place in ["東京", "中山", "京都", "阪神", "中京", "新潟", "福島", "小倉", "札幌", "函館"]:
        if place in s:
            return place
    for code, place in TRACK_CODE_MAP.items():
        if code in s:
            return place
    return s


def normalize_surface(x: Any) -> str:
    s = norm(x)
    if "ダ" in s or "D" in s.upper():
        return "ダ"
    if "芝" in s:
        return "芝"
    if "障" in s:
        return "障"
    return ""


def parse_date(raw: Any, year: int) -> str:
    """
    TARGETの 516 → 2026.5.16 のように変換。
    """
    s = norm(raw)
    n = to_int(s)
    if n is None:
        return s

    if 101 <= n <= 1231:
        month = n // 100
        day = n % 100
        return f"{year}.{month}.{day}"

    if len(str(n)) == 6:
        ss = str(n)
        yy = int(ss[:2])
        return f"{2000 + yy}.{int(ss[2:4])}.{int(ss[4:6])}"

    return s


def parse_race_number(raw: Any) -> str:
    """
    新1 → 1R
    東12 → 12R
    12R → 12R
    """
    s = norm(raw)
    m = re.search(r"(\d{1,2})\s*R", s, flags=re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}R"

    m = re.search(r"[東中京阪名新福小札函]?(\d{1,2})$", s)
    if m:
        return f"{int(m.group(1))}R"

    n = to_int(s)
    if n is not None and 1 <= n <= 12:
        return f"{n}R"

    return s


def position_category(order: Optional[int], field_size: Optional[int]) -> str:
    """
    前走頭数補正カテゴリ。
    1番手は無条件で1番手。
    2番手以下は相対位置で判定。
    空欄は空欄のまま。
    """
    if order is None or field_size is None or field_size <= 0:
        return ""

    if order <= 1:
        return "1番手"

    ratio = order / field_size

    if ratio <= 0.25:
        return "2-3番手"
    if ratio <= 0.45:
        return "4-6番手"
    if ratio <= 0.85:
        return "7-10番手"
    return "11番手以下"


def style_from_position(p4: Optional[int], field_size: Optional[int]) -> str:
    if p4 is None or field_size is None or field_size <= 0:
        return "不明"

    if p4 == 1:
        return "逃げ"

    ratio = p4 / field_size

    if ratio <= 0.25:
        return "先行"
    if ratio <= 0.45:
        return "好位"
    if ratio <= 0.75:
        return "差し"
    return "追込"


def fallback_field_size(
    finish: Optional[int],
    p1: Optional[int],
    p2: Optional[int],
    p3: Optional[int],
    p4: Optional[int],
    agari_rank: Optional[int],
    min_field: int,
) -> int:
    """
    前頭数が空欄の場合だけ、最低限の補完。
    ただし今回のCSVでは基本的に前頭数を実数として使う。
    """
    nums = [x for x in [finish, p1, p2, p3, p4, agari_rank] if isinstance(x, int) and x > 0]
    base = max(nums) if nums else min_field
    return max(base, min_field)


# =========================================================
# 採点ロジック
# =========================================================

def calc_prev_score(
    finish: Optional[int],
    margin: Optional[float],
    p4: Optional[int],
    field_size: Optional[int],
    agari_rank: Optional[int],
    prev_class: str,
    prev_surface: str,
    prev_distance: Optional[int],
    current_surface: str,
    current_distance: Optional[int],
    prev_track: str,
    current_track: str,
    going: str,
) -> int:
    """
    前走直線ロジック点 100点満点。
    TARGETから取得できる前走情報のみで機械的に採点。
    """
    score = 50.0

    # 着順
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

    # 着差
    if margin is not None:
        if margin <= 0.0:
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

    # 4角位置×結果
    if p4 is not None and field_size:
        ratio4 = p4 / field_size

        if finish is not None:
            # 後方から伸びて好走
            if ratio4 >= 0.65 and finish <= 5:
                score += 10
            elif ratio4 >= 0.45 and finish <= 3:
                score += 7

            # 前で粘る
            elif ratio4 <= 0.25 and finish <= 3:
                score += 6
            elif ratio4 <= 0.45 and finish <= 5:
                score += 4

            # 後方のまま大敗
            if ratio4 >= 0.75 and finish >= 9:
                score -= 6

    # 上がり順位
    if agari_rank is not None:
        if agari_rank == 1:
            score += 12
        elif agari_rank <= 3:
            score += 9
        elif agari_rank <= 5:
            score += 5
        elif agari_rank <= 8:
            score += 1
        else:
            score -= 4

    # クラス補正
    cls = norm(prev_class)
    if any(k in cls for k in ["G1", "GI", "GⅠ", "Ｇ１"]):
        score += 8
    elif any(k in cls for k in ["G2", "GII", "GⅡ", "Ｇ２"]):
        score += 6
    elif any(k in cls for k in ["G3", "GIII", "GⅢ", "Ｇ３"]):
        score += 4
    elif any(k in cls for k in ["OP", "L", "リステッド", "オープン"]):
        score += 2

    # 芝ダ替わり
    if prev_surface and current_surface and prev_surface != current_surface:
        score -= 4

    # 距離差
    if prev_distance and current_distance:
        diff = abs(current_distance - prev_distance)
        if diff <= 200:
            score += 4
        elif diff <= 400:
            score += 1
        elif diff >= 800:
            score -= 5

    # 直線長の再現性
    prev_type = TRACK_STRAIGHT_TYPE.get(prev_track, "")
    cur_type = TRACK_STRAIGHT_TYPE.get(current_track, "")

    if prev_type and cur_type:
        if prev_type == cur_type:
            score += 4
        elif prev_type == "短い" and cur_type == "長い":
            if p4 is not None and field_size and (p4 / field_size) >= 0.45 and finish is not None and finish <= 5:
                score += 5
            else:
                score -= 1
        elif prev_type == "長い" and cur_type == "短い":
            if p4 is not None and field_size and (p4 / field_size) <= 0.45 and finish is not None and finish <= 5:
                score += 3
            else:
                score -= 2

    # 重・不良好走の特殊性を少し控えめ
    if any(k in norm(going) for k in ["重", "不良"]) and finish is not None and finish <= 3:
        score -= 1

    return int(max(0, min(100, round(score))))


def classify_race_flow(styles: List[str]) -> str:
    esc = styles.count("逃げ")
    front = styles.count("逃げ") + styles.count("先行")

    if esc == 0 and front <= 2:
        return "D"
    if esc == 1 and front <= 4:
        return "A"
    if front >= 6:
        return "C"
    return "B"


def calc_development_eval(style: str, flow: str) -> str:
    if style == "不明":
        return "普通"

    table = {
        "A": {
            "逃げ": "かなり向く",
            "先行": "かなり向く",
            "好位": "向く",
            "差し": "普通",
            "追込": "やや不向き",
        },
        "B": {
            "逃げ": "向く",
            "先行": "向く",
            "好位": "向く",
            "差し": "普通",
            "追込": "やや不向き",
        },
        "C": {
            "逃げ": "やや不向き",
            "先行": "普通",
            "好位": "向く",
            "差し": "向く",
            "追込": "普通",
        },
        "D": {
            "逃げ": "かなり向く",
            "先行": "かなり向く",
            "好位": "向く",
            "差し": "やや不向き",
            "追込": "不向き",
        },
    }

    return table.get(flow, {}).get(style, "普通")


def calc_straight_eval(
    score: int,
    style: str,
    prev_track: str,
    current_track: str,
    prev_distance: Optional[int],
    current_distance: Optional[int],
) -> str:
    base = 2 if score >= 88 else 1 if score >= 75 else 0 if score >= 55 else -1 if score >= 40 else -2

    prev_type = TRACK_STRAIGHT_TYPE.get(prev_track, "")
    cur_type = TRACK_STRAIGHT_TYPE.get(current_track, "")

    if prev_type and cur_type:
        if prev_type == cur_type:
            base += 1
        elif prev_type == "短い" and cur_type == "長い":
            if style in ["差し", "追込", "好位"]:
                base += 1
            else:
                base -= 1
        elif prev_type == "長い" and cur_type == "短い":
            if style in ["逃げ", "先行", "好位"]:
                base += 1
            else:
                base -= 1

    if prev_distance and current_distance:
        diff = abs(current_distance - prev_distance)
        if diff <= 200:
            base += 1
        elif diff >= 800:
            base -= 1

    base = max(-2, min(2, base))

    return {
        2: "かなり向く",
        1: "向く",
        0: "普通",
        -1: "やや不向き",
        -2: "不向き",
    }[base]


# =========================================================
# CSV読み込み
# =========================================================

def read_target_csv(uploaded_file) -> pd.DataFrame:
    raw = uploaded_file.read()
    last_error = None

    for enc in ["cp932", "shift_jis", "utf-8-sig", "utf-8"]:
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, header=None)
        except Exception as e:
            last_error = e

    raise last_error


def apply_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    37列に列名を付与。
    37列未満・超過でも落ちないように調整。
    """
    df = df.copy()
    n = df.shape[1]

    cols = TARGET_COLUMNS_37[:n]
    if n > len(cols):
        cols += [f"未使用{i}" for i in range(n - len(cols))]

    df.columns = cols
    return df


# =========================================================
# 変換本体
# =========================================================

def convert_target_to_v12(
    df: pd.DataFrame,
    year: int,
    filter_7_12: bool,
    min_field_if_blank: int,
) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    temp_rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        date = parse_date(row.get("日付_raw", ""), year)
        place = normalize_place(row.get("場所", ""))
        race = parse_race_number(row.get("場R", ""))

        race_num = to_int(race)
        if filter_7_12 and race_num is not None and not (7 <= race_num <= 12):
            continue

        surface = normalize_surface(row.get("芝ダ", ""))
        distance = to_int(row.get("距離", ""))

        horse_no = to_int(row.get("馬番", ""))
        horse_name = norm(row.get("馬名", ""))

        prev_track = normalize_place(row.get("前走場所", ""))
        prev_surface = normalize_surface(row.get("前芝ダ", ""))
        prev_distance = to_int(row.get("前距離", ""))
        prev_class = norm(row.get("前クラス", ""))

        p1 = to_int(row.get("前1角", ""))
        p2 = to_int(row.get("前2角", ""))
        p3 = to_int(row.get("前3角", ""))
        p4 = to_int(row.get("前4角", ""))

        finish = to_int(row.get("前走着順", ""))
        margin = to_float(row.get("前走着差", ""))
        going = norm(row.get("前走馬場状態", ""))
        agari_rank = to_int(row.get("前走上3F順位", ""))

        # 今回追加された前頭数を実数として使用
        field_size = to_int(row.get("前頭数", ""))

        # 前頭数がない馬だけ補完
        if field_size is None:
            field_size = fallback_field_size(
                finish=finish,
                p1=p1,
                p2=p2,
                p3=p3,
                p4=p4,
                agari_rank=agari_rank,
                min_field=min_field_if_blank,
            )

        cat3 = position_category(p3, field_size)
        cat4 = position_category(p4, field_size)
        style = style_from_position(p4, field_size)

        temp_rows.append({
            "日付": date,
            "場所": place,
            "芝ダ": surface,
            "距離": distance if distance is not None else "",
            "レース": race,
            "レース名": norm(row.get("レース名", "")),
            "馬番": horse_no if horse_no is not None else "",
            "馬名": horse_name,
            "前走競馬場": prev_track,
            "前走芝ダ": prev_surface,
            "前走距離数値": prev_distance if prev_distance is not None else "",
            "前走頭数": field_size if field_size is not None else "",
            "前3角通過順": p3 if p3 is not None else "",
            "前4角通過順": p4 if p4 is not None else "",
            "前3角位置カテゴリ": cat3,
            "前4角位置カテゴリ": cat4,
            "前走場所": prev_track,
            "_前1角": p1,
            "_前2角": p2,
            "_finish": finish,
            "_margin": margin,
            "_going": going,
            "_agari_rank": agari_rank,
            "_prev_class": prev_class,
            "_style": style,
        })

    flow = classify_race_flow([r["_style"] for r in temp_rows])

    output_rows: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []

    for r in temp_rows:
        prev_score = calc_prev_score(
            finish=r["_finish"],
            margin=r["_margin"],
            p4=r["前4角通過順"] if isinstance(r["前4角通過順"], int) else None,
            field_size=r["前走頭数"] if isinstance(r["前走頭数"], int) else None,
            agari_rank=r["_agari_rank"],
            prev_class=r["_prev_class"],
            prev_surface=r["前走芝ダ"],
            prev_distance=r["前走距離数値"] if isinstance(r["前走距離数値"], int) else None,
            current_surface=r["芝ダ"],
            current_distance=r["距離"] if isinstance(r["距離"], int) else None,
            prev_track=r["前走競馬場"],
            current_track=r["場所"],
            going=r["_going"],
        )

        development_eval = calc_development_eval(r["_style"], flow)

        straight_eval = calc_straight_eval(
            score=prev_score,
            style=r["_style"],
            prev_track=r["前走競馬場"],
            current_track=r["場所"],
            prev_distance=r["前走距離数値"] if isinstance(r["前走距離数値"], int) else None,
            current_distance=r["距離"] if isinstance(r["距離"], int) else None,
        )

        out = {k: r.get(k, "") for k in OUTPUT_COLUMNS}
        out["前走直線ロジック点"] = prev_score
        out["前々走直線ロジック点"] = 0
        out["展開予想評価"] = development_eval
        out["直線相性評価"] = straight_eval

        output_rows.append(out)

        debug_rows.append({
            "日付": r["日付"],
            "場所": r["場所"],
            "R": r["レース"],
            "馬番": r["馬番"],
            "馬名": r["馬名"],
            "今回": f'{r["芝ダ"]}{r["距離"]}',
            "前走": f'{r["前走競馬場"]}{r["前走芝ダ"]}{r["前走距離数値"]}',
            "前3角": r["前3角通過順"],
            "前4角": r["前4角通過順"],
            "前走頭数": r["前走頭数"],
            "前3角カテゴリ": r["前3角位置カテゴリ"],
            "前4角カテゴリ": r["前4角位置カテゴリ"],
            "前走着順": r["_finish"] if r["_finish"] is not None else "",
            "前走着差": r["_margin"] if r["_margin"] is not None else "",
            "上3F順位": r["_agari_rank"] if r["_agari_rank"] is not None else "",
            "脚質推定": r["_style"],
            "前走直線ロジック点": prev_score,
            "展開予想評価": development_eval,
            "直線相性評価": straight_eval,
        })

    out_df = pd.DataFrame(output_rows, columns=OUTPUT_COLUMNS)
    debug_df = pd.DataFrame(debug_rows)

    return out_df, debug_df, flow


def make_quality_report(out_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in OUTPUT_COLUMNS:
        blank = int(out_df[col].isna().sum() + (out_df[col].astype(str).str.strip() == "").sum())

        # 前3角・前4角系は、新潟1000/地方/障害/前走データ欠損などで空欄があり得るので警告扱い
        if col in ["前3角通過順", "前4角通過順", "前3角位置カテゴリ", "前4角位置カテゴリ"]:
            status = "空欄あり/許容" if blank > 0 else "OK"
        else:
            status = "OK" if blank == 0 or col == "レース名" else "要確認"

        rows.append({
            "列名": col,
            "空欄数": blank,
            "状態": status,
        })

    return pd.DataFrame(rows)


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# =========================================================
# Streamlit UI
# =========================================================

st.set_page_config(
    page_title="TARGET直線ロジック採点",
    page_icon="🏇",
    layout="wide",
)

st.title("🏇 TARGET直線ロジック採点アプリ")
st.caption("５．１６直線２.csv 実データ列順対応版 / 前走頭数実数対応 / 前々走点は0固定")

with st.expander("このアプリの前提", expanded=True):
    st.write(
        """
        今回送ってもらった **５．１６直線２.csv** を確認し、37列の実データ列順に合わせています。

        - 追加された **前頭数** を実数として使用します。
        - 前3角/前4角が空欄の馬は、TARGET側にデータが無いものとして空欄扱いのまま出力します。
        - 前々走直線ロジック点は 0 固定です。
        - オッズ、人気、予想印、AI指数は使いません。
        """
    )

uploaded = st.file_uploader("TARGETから出力したCSVをアップロードしてください", type=["csv"])

col1, col2, col3 = st.columns(3)

with col1:
    target_year = st.number_input("年", min_value=2020, max_value=2035, value=2026, step=1)

with col2:
    filter_7_12 = st.checkbox("7〜12Rのみ抽出", value=True)

with col3:
    min_field_if_blank = st.number_input(
        "前頭数が空欄の時だけ使う最低頭数",
        min_value=1,
        max_value=18,
        value=12,
        step=1,
    )

if uploaded is not None:
    try:
        raw_df = read_target_csv(uploaded)
        df = apply_columns(raw_df)
    except Exception as e:
        st.error(f"CSVを読み込めませんでした: {e}")
        st.stop()

    st.subheader("① 読み込み確認")
    st.write(f"行数: {len(df)} / 列数: {df.shape[1]}")
    st.dataframe(df.head(30), use_container_width=True)

    if df.shape[1] != 37:
        st.warning(
            f"今回想定は37列ですが、このCSVは {df.shape[1]}列です。列数が変わるとズレる可能性があります。"
        )

    st.subheader("② 変換・採点結果")

    out_df, debug_df, flow = convert_target_to_v12(
        df=df,
        year=int(target_year),
        filter_7_12=filter_7_12,
        min_field_if_blank=int(min_field_if_blank),
    )

    flow_label = {
        "A": "A：単騎逃げ濃厚",
        "B": "B：先行争い軽め",
        "C": "C：先行争い激化",
        "D": "D：逃げ馬不在スロー",
    }.get(flow, flow)

    st.info(f"展開タイプ：{flow_label}")

    st.dataframe(debug_df, use_container_width=True)

    st.subheader("③ v12.2互換CSVプレビュー")
    st.dataframe(out_df, use_container_width=True)

    st.subheader("④ 空欄チェック")
    st.dataframe(make_quality_report(out_df), use_container_width=True)

    if len(out_df) == 0:
        st.error("出力対象が0行です。7〜12Rのみ抽出を外すか、場R列を確認してください。")
    else:
        st.download_button(
            label="📥 v12.2互換CSVをダウンロード",
            data=csv_bytes(out_df),
            file_name="straight_logic_v12_2_input.csv",
            mime="text/csv",
        )

else:
    st.info("CSVをアップロードすると、変換結果が表示されます。")
