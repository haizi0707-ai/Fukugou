# -*- coding: utf-8 -*-
"""
TARGET前走データ → 直線ロジック採点CSV変換アプリ
前走のみ版 / 前々走直線ロジック点は 0 固定

使い方:
    streamlit run app.py

入力想定:
TARGETの項目設定で抜き取ったCSV
推奨項目:
日付,場所,場R,芝ダ・距離,レース名(クラス),馬番,馬名,枠番,騎手,斤量,
性別,年齢,前走場所,前芝ダ,前距離,前クラス,前頭数,前通過順,
前走着順,前走着差,前走馬場状態,前走上3F順位,前走開催,
前走騎手,前走斤量,前走馬体重,前走馬体重増減
"""

import io
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st


# =========================================================
# 基本設定
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

POSITION_CATEGORIES = ["1番手", "2-3番手", "4-6番手", "7-10番手", "11番手以下"]
EVAL_WORDS = ["かなり向く", "向く", "普通", "やや不向き", "不向き"]

TRACK_STRAIGHT_TYPE = {
    # 芝/ダや内外までは厳密に分けず、前走→今回の再現性用の大まかな分類
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


# =========================================================
# 汎用ユーティリティ
# =========================================================

def norm_text(x: Any) -> str:
    """文字列を正規化。nan/Noneは空文字。"""
    if x is None:
        return ""
    if pd.isna(x):
        return ""
    s = str(x).strip()
    s = unicodedata.normalize("NFKC", s)
    return s


def to_int(x: Any, default: Optional[int] = None) -> Optional[int]:
    """文字列から最初の整数を抽出。"""
    s = norm_text(x)
    if s == "":
        return default
    s = s.replace(",", "")
    m = re.search(r"-?\d+", s)
    if not m:
        return default
    try:
        return int(m.group())
    except Exception:
        return default


def to_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    """文字列から最初の小数を抽出。"""
    s = norm_text(x)
    if s == "":
        return default
    s = s.replace(",", "")
    # TARGETの着差で「タイム差なし」「同」「クビ」などが来る可能性は0扱い寄り
    if any(k in s for k in ["同", "タイム差なし", "アタマ", "ハナ", "クビ"]):
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return default
    try:
        return float(m.group())
    except Exception:
        return default


def normalize_place(s: Any) -> str:
    s = norm_text(s)
    for p in ["東京", "中山", "京都", "阪神", "中京", "新潟", "福島", "小倉", "札幌", "函館"]:
        if p in s:
            return p
    return s


def normalize_surface(s: Any) -> str:
    s = norm_text(s)
    if "ダ" in s or "D" in s.upper():
        return "ダ"
    if "芝" in s:
        return "芝"
    return ""


def parse_surface_distance(value: Any) -> Tuple[str, Optional[int]]:
    """
    「芝ダ・距離」や「ダ1800」「芝 1600」から芝ダ・距離を抽出。
    """
    s = norm_text(value)
    surface = normalize_surface(s)
    dist = to_int(s)
    return surface, dist


def parse_race_number(value: Any) -> str:
    """
    「場R」や「レース」から 12R 形式に整える。
    """
    s = norm_text(value)
    m = re.search(r"(\d{1,2})\s*R", s, flags=re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}R"
    n = to_int(s)
    if n is not None:
        return f"{n}R"
    return s


def parse_passing_order(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    TARGETの「前通過順」を前3角・前4角へ分解。
    例:
      "3-4" -> 3,4
      "12-10-8-7" -> 8,7
      "4角 5" -> 5,5
      "1" -> 1,1
    """
    s = norm_text(value)
    if not s:
        return None, None
    nums = [int(n) for n in re.findall(r"\d+", s)]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return nums[-2], nums[-1]
    return nums[0], nums[0]


def position_category(order: Optional[int], field_size: Optional[int]) -> str:
    """
    総頭数補正カテゴリ。
    通過順1番手は必ず「1番手」。
    2番手以下は相対位置で5カテゴリへ寄せる。
    """
    if order is None or field_size is None or field_size <= 0:
        return ""
    if order <= 1:
        return "1番手"

    ratio = order / field_size

    # アプリ側の5カテゴリへ変換
    # 0.25以下 → 2-3番手
    # 0.45以下 → 4-6番手
    # 0.85以下 → 7-10番手
    # 0.85超 → 11番手以下
    if ratio <= 0.25:
        return "2-3番手"
    if ratio <= 0.45:
        return "4-6番手"
    if ratio <= 0.85:
        return "7-10番手"
    return "11番手以下"


def safe_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    候補名から実在列を探す。
    表記ゆれに少し強くする。
    """
    cols = list(df.columns)
    normalized_map = {norm_text(c).replace(" ", "").replace("　", ""): c for c in cols}

    for cand in candidates:
        key = norm_text(cand).replace(" ", "").replace("　", "")
        if key in normalized_map:
            return normalized_map[key]

    # 部分一致
    for cand in candidates:
        key = norm_text(cand).replace(" ", "").replace("　", "")
        for nk, real in normalized_map.items():
            if key and key in nk:
                return real

    return None


def get_value(row: pd.Series, col: Optional[str], default: Any = "") -> Any:
    if col is None:
        return default
    try:
        v = row[col]
        if pd.isna(v):
            return default
        return v
    except Exception:
        return default


def read_csv_auto(uploaded_file) -> pd.DataFrame:
    """
    UTF-8 / CP932 / SHIFT_JIS を自動試行。
    """
    raw = uploaded_file.read()
    encodings = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except Exception as e:
            last_err = e
    raise last_err


# =========================================================
# 採点ロジック
# =========================================================

def calc_prev_run_score(
    finish: Optional[int],
    margin: Optional[float],
    passing4: Optional[int],
    field_size: Optional[int],
    agari_rank: Optional[int],
    prev_class: str,
    prev_surface: str,
    prev_distance: Optional[int],
    current_surface: str,
    current_distance: Optional[int],
    prev_track: str,
    current_track: str,
    prev_going: str,
) -> int:
    """
    前走直線ロジック点 100点満点。
    TARGET項目だけで機械的に再現しやすい簡易版。
    """
    score = 50.0

    # 1) 着順・着差
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
        # 着差は小さいほど評価。負値は勝ち扱い寄り。
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

    # 2) 4角位置と結果の組み合わせ
    if passing4 is not None and field_size:
        ratio4 = passing4 / field_size

        if finish is not None:
            # 後方から好走 → 直線評価を上げる
            if ratio4 >= 0.65 and finish <= 5:
                score += 10
            elif ratio4 >= 0.45 and finish <= 3:
                score += 7
            # 前で粘る → 短直線・再現型として評価
            elif ratio4 <= 0.25 and finish <= 3:
                score += 6
            elif ratio4 <= 0.45 and finish <= 5:
                score += 4

            # 後方のまま大敗
            if ratio4 >= 0.75 and finish >= 9:
                score -= 6

    # 3) 上がり順位
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

    # 4) クラス補正
    cls = norm_text(prev_class)
    if any(k in cls for k in ["G1", "GI", "Ｇ１", "GⅠ"]):
        score += 8
    elif any(k in cls for k in ["G2", "GII", "Ｇ２", "GⅡ"]):
        score += 6
    elif any(k in cls for k in ["G3", "GIII", "Ｇ３", "GⅢ"]):
        score += 4
    elif any(k in cls for k in ["OP", "オープン", "L", "リステッド"]):
        score += 2

    # 5) 距離・芝ダ替わりの減点/微調整
    if prev_surface and current_surface and prev_surface != current_surface:
        score -= 4

    if prev_distance and current_distance:
        diff = abs(current_distance - prev_distance)
        if diff <= 200:
            score += 4
        elif diff <= 400:
            score += 1
        elif diff >= 800:
            score -= 5

    # 6) 直線長の再現性
    prev_type = TRACK_STRAIGHT_TYPE.get(prev_track, "")
    cur_type = TRACK_STRAIGHT_TYPE.get(current_track, "")
    if prev_type and cur_type:
        if prev_type == cur_type:
            score += 4
        elif prev_type == "短い" and cur_type == "長い":
            # 短直線で差して好走ならプラス、前受け楽ならやや注意
            if passing4 is not None and field_size and (passing4 / field_size) >= 0.45 and finish is not None and finish <= 5:
                score += 5
            else:
                score -= 1
        elif prev_type == "長い" and cur_type == "短い":
            if passing4 is not None and field_size and (passing4 / field_size) <= 0.45 and finish is not None and finish <= 5:
                score += 3
            else:
                score -= 2

    # 7) 馬場状態補正
    going = norm_text(prev_going)
    if any(k in going for k in ["重", "不良"]):
        # 特殊馬場の好走は少し控えめ。ただし大きくは下げない。
        if finish is not None and finish <= 3:
            score -= 1

    # 0〜100に丸める
    score = max(0, min(100, round(score)))
    return int(score)


def calc_pace_style(passing4: Optional[int], field_size: Optional[int]) -> str:
    if passing4 is None or not field_size:
        return "不明"
    if passing4 <= 1:
        return "逃げ"
    ratio = passing4 / field_size
    if ratio <= 0.25:
        return "先行"
    if ratio <= 0.45:
        return "好位"
    if ratio <= 0.75:
        return "差し"
    return "追込"


def classify_race_flow(styles: List[str]) -> str:
    """
    全体の脚質数から展開タイプを簡易推定。
    A:単騎逃げ濃厚
    B:先行争い軽め
    C:先行争い激化
    D:逃げ馬不在スロー
    """
    n_escape = styles.count("逃げ")
    n_front = styles.count("逃げ") + styles.count("先行")
    n_close = styles.count("差し") + styles.count("追込")

    if n_escape == 0 and n_front <= 2:
        return "D"
    if n_escape == 1 and n_front <= 4:
        return "A"
    if n_front >= 6:
        return "C"
    return "B"


def calc_development_eval(style: str, race_flow: str) -> str:
    """
    展開予想評価。
    """
    if style == "不明":
        return "普通"

    if race_flow == "A":  # 単騎逃げ濃厚
        if style in ["逃げ", "先行"]:
            return "かなり向く"
        if style == "好位":
            return "向く"
        if style == "差し":
            return "普通"
        return "やや不向き"

    if race_flow == "B":  # 先行争い軽め
        if style in ["逃げ", "先行", "好位"]:
            return "向く"
        if style == "差し":
            return "普通"
        return "やや不向き"

    if race_flow == "C":  # 先行争い激化
        if style in ["差し", "好位"]:
            return "向く"
        if style == "追込":
            return "普通"
        if style == "逃げ":
            return "やや不向き"
        return "普通"

    if race_flow == "D":  # 逃げ馬不在スロー
        if style in ["逃げ", "先行"]:
            return "かなり向く"
        if style == "好位":
            return "向く"
        if style == "差し":
            return "やや不向き"
        return "不向き"

    return "普通"


def calc_straight_fit_eval(
    score: int,
    style: str,
    prev_track: str,
    current_track: str,
    prev_distance: Optional[int],
    current_distance: Optional[int],
) -> str:
    """
    直線相性評価。
    前走直線ロジック点と前走→今回の直線長・距離差で5段階化。
    """
    base = 0
    if score >= 88:
        base = 2
    elif score >= 75:
        base = 1
    elif score >= 55:
        base = 0
    elif score >= 40:
        base = -1
    else:
        base = -2

    prev_type = TRACK_STRAIGHT_TYPE.get(prev_track, "")
    cur_type = TRACK_STRAIGHT_TYPE.get(current_track, "")

    if prev_type and cur_type:
        if prev_type == cur_type:
            base += 1
        elif prev_type == "短い" and cur_type == "長い":
            if style in ["差し", "追込", "好位"]:
                base += 1
            elif style in ["逃げ", "先行"]:
                base -= 1
        elif prev_type == "長い" and cur_type == "短い":
            if style in ["逃げ", "先行", "好位"]:
                base += 1
            elif style in ["追込"]:
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
# 変換処理
# =========================================================

def build_column_map(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    TARGET出力の列名表記ゆれに対応。
    """
    return {
        "日付": safe_col(df, ["日付", "年月日"]),
        "場所": safe_col(df, ["場所", "競馬場", "場名"]),
        "場R": safe_col(df, ["場R", "場Ｒ", "レース", "R", "Ｒ"]),
        "芝ダ距離": safe_col(df, ["芝ダ・距離", "芝ダ距離", "芝・ダ距離", "距離", "芝ダ"]),
        "レース名": safe_col(df, ["レース名(クラス)", "レース名", "クラス"]),
        "馬番": safe_col(df, ["馬番"]),
        "馬名": safe_col(df, ["馬名"]),
        "枠番": safe_col(df, ["枠番", "枠"]),
        "騎手": safe_col(df, ["騎手"]),
        "斤量": safe_col(df, ["斤量"]),

        "前走場所": safe_col(df, ["前走場所", "前場所", "前走競馬場"]),
        "前芝ダ": safe_col(df, ["前芝ダ", "前走芝ダ", "前芝・ダ", "前走芝・ダ"]),
        "前距離": safe_col(df, ["前距離", "前走距離", "前距離数値"]),
        "前クラス": safe_col(df, ["前クラス", "前走クラス"]),
        "前頭数": safe_col(df, ["前頭数", "前走頭数"]),
        "前通過順": safe_col(df, ["前通過順", "前走通過順", "前走通過", "通過順"]),
        "前走着順": safe_col(df, ["前走着順", "前着順", "前着"]),
        "前走着差": safe_col(df, ["前走着差", "前着差"]),
        "前走馬場状態": safe_col(df, ["前走馬場状態", "前馬場状態", "前馬場"]),
        "前走上3F順位": safe_col(df, ["前走上3F順位", "前走上３F順位", "前上3F順位", "前走上り3F順位", "前走上り順位", "前走上がり順位"]),
    }


def convert_df(df: pd.DataFrame, race_filter_7_12: bool = True) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    cm = build_column_map(df)

    rows: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []

    # 一旦全馬のstyleを作る
    temp: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        date = norm_text(get_value(row, cm["日付"]))
        place = normalize_place(get_value(row, cm["場所"]))
        race = parse_race_number(get_value(row, cm["場R"]))

        # 7〜12Rだけ
        race_num = to_int(race)
        if race_filter_7_12 and race_num is not None and not (7 <= race_num <= 12):
            continue

        surface, distance = parse_surface_distance(get_value(row, cm["芝ダ距離"]))
        race_name = norm_text(get_value(row, cm["レース名"]))
        horse_no = to_int(get_value(row, cm["馬番"]))
        horse_name = norm_text(get_value(row, cm["馬名"]))

        prev_track = normalize_place(get_value(row, cm["前走場所"]))
        prev_surface = normalize_surface(get_value(row, cm["前芝ダ"]))
        prev_distance = to_int(get_value(row, cm["前距離"]))
        prev_class = norm_text(get_value(row, cm["前クラス"]))
        prev_field = to_int(get_value(row, cm["前頭数"]))
        p3, p4 = parse_passing_order(get_value(row, cm["前通過順"]))
        finish = to_int(get_value(row, cm["前走着順"]))
        margin = to_float(get_value(row, cm["前走着差"]))
        going = norm_text(get_value(row, cm["前走馬場状態"]))
        agari_rank = to_int(get_value(row, cm["前走上3F順位"]))

        cat3 = position_category(p3, prev_field)
        cat4 = position_category(p4, prev_field)
        style = calc_pace_style(p4, prev_field)

        temp.append({
            "日付": date,
            "場所": place,
            "芝ダ": surface,
            "距離": distance if distance is not None else "",
            "レース": race,
            "レース名": race_name,
            "馬番": horse_no if horse_no is not None else "",
            "馬名": horse_name,
            "前走競馬場": prev_track,
            "前走芝ダ": prev_surface,
            "前走距離数値": prev_distance if prev_distance is not None else "",
            "前走頭数": prev_field if prev_field is not None else "",
            "前3角通過順": p3 if p3 is not None else "",
            "前4角通過順": p4 if p4 is not None else "",
            "前3角位置カテゴリ": cat3,
            "前4角位置カテゴリ": cat4,
            "前走場所": prev_track,
            "_finish": finish,
            "_margin": margin,
            "_agari_rank": agari_rank,
            "_prev_class": prev_class,
            "_going": going,
            "_style": style,
        })

    styles = [r["_style"] for r in temp]
    race_flow = classify_race_flow(styles)

    for r in temp:
        prev_score = calc_prev_run_score(
            finish=r["_finish"],
            margin=r["_margin"],
            passing4=r["前4角通過順"] if isinstance(r["前4角通過順"], int) else None,
            field_size=r["前走頭数"] if isinstance(r["前走頭数"], int) else None,
            agari_rank=r["_agari_rank"],
            prev_class=r["_prev_class"],
            prev_surface=r["前走芝ダ"],
            prev_distance=r["前走距離数値"] if isinstance(r["前走距離数値"], int) else None,
            current_surface=r["芝ダ"],
            current_distance=r["距離"] if isinstance(r["距離"], int) else None,
            prev_track=r["前走競馬場"],
            current_track=r["場所"],
            prev_going=r["_going"],
        )

        development_eval = calc_development_eval(r["_style"], race_flow)
        straight_fit_eval = calc_straight_fit_eval(
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
        out["直線相性評価"] = straight_fit_eval
        rows.append(out)

        debug_rows.append({
            "馬番": r["馬番"],
            "馬名": r["馬名"],
            "脚質推定": r["_style"],
            "展開タイプ": race_flow,
            "前走着順": r["_finish"] if r["_finish"] is not None else "",
            "前走着差": r["_margin"] if r["_margin"] is not None else "",
            "前走上3F順位": r["_agari_rank"] if r["_agari_rank"] is not None else "",
            "前走直線ロジック点": prev_score,
            "展開予想評価": development_eval,
            "直線相性評価": straight_fit_eval,
        })

    out_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    debug_df = pd.DataFrame(debug_rows)
    return out_df, debug_df, race_flow


def make_quality_report(out_df: pd.DataFrame) -> pd.DataFrame:
    checks = []
    for col in OUTPUT_COLUMNS:
        blank_count = int(out_df[col].isna().sum() + (out_df[col].astype(str).str.strip() == "").sum())
        checks.append({
            "列名": col,
            "空欄数": blank_count,
            "状態": "OK" if blank_count == 0 or col in ["レース名"] else "要確認",
        })
    return pd.DataFrame(checks)


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# =========================================================
# Streamlit UI
# =========================================================

st.set_page_config(
    page_title="TARGET前走データ → 直線ロジックCSV",
    page_icon="🏇",
    layout="wide",
)

st.title("🏇 TARGET前走データ → 直線ロジック採点CSV")
st.caption("前走のみ版。前々走直線ロジック点は 0 固定で出力します。")

with st.expander("このアプリでできること", expanded=True):
    st.write(
        """
        TARGETから抜き取った前走データCSVを読み込み、
        競馬ランクアプリ v12.2 Relative SNS Save 互換のCSVに変換します。

        - 7〜12Rだけ抽出可能
        - 前通過順を 前3角通過順 / 前4角通過順 に分解
        - 前走頭数を使って位置カテゴリを総頭数補正
        - 前走直線ロジック点を100点満点で自動採点
        - 前々走直線ロジック点は 0 固定
        - 展開予想評価 / 直線相性評価を5段階で自動判定
        """
    )

uploaded = st.file_uploader("TARGETから出力したCSVをアップロードしてください", type=["csv"])

race_filter = st.checkbox("7〜12Rのみ抽出する", value=True)

if uploaded is not None:
    try:
        src_df = read_csv_auto(uploaded)
    except Exception as e:
        st.error(f"CSVを読み込めませんでした: {e}")
        st.stop()

    st.subheader("① 読み込みデータ")
    st.write(f"行数: {len(src_df)} / 列数: {len(src_df.columns)}")
    st.dataframe(src_df.head(50), use_container_width=True)

    cm = build_column_map(src_df)
    st.subheader("② 認識した列")
    cm_df = pd.DataFrame([{"必要項目": k, "認識列": v if v else "未検出"} for k, v in cm.items()])
    st.dataframe(cm_df, use_container_width=True)

    missing_core = [k for k, v in cm.items() if v is None and k in [
        "日付", "場所", "場R", "芝ダ距離", "馬番", "馬名",
        "前走場所", "前芝ダ", "前距離", "前頭数", "前通過順",
        "前走着順", "前走着差"
    ]]
    if missing_core:
        st.warning("重要列が一部見つかりません。列名が違う場合は、CSVの列名を確認してください。")
        st.write(missing_core)

    out_df, debug_df, race_flow = convert_df(src_df, race_filter_7_12=race_filter)

    st.subheader("③ 展開タイプ")
    flow_label = {
        "A": "A：単騎逃げ濃厚",
        "B": "B：先行争い軽め",
        "C": "C：先行争い激化",
        "D": "D：逃げ馬不在スロー",
    }.get(race_flow, race_flow)
    st.info(flow_label)

    st.subheader("④ 採点確認")
    st.dataframe(debug_df, use_container_width=True)

    st.subheader("⑤ 出力CSVプレビュー")
    st.dataframe(out_df, use_container_width=True)

    st.subheader("⑥ 空欄チェック")
    q_df = make_quality_report(out_df)
    st.dataframe(q_df, use_container_width=True)

    if len(out_df) == 0:
        st.error("出力対象が0行です。7〜12R抽出を外すか、場R列を確認してください。")
    else:
        # ファイル名作成
        date_str = norm_text(out_df["日付"].iloc[0]) if "日付" in out_df.columns and len(out_df) else "target"
        place_str = norm_text(out_df["場所"].iloc[0]) if "場所" in out_df.columns and len(out_df) else "race"
        race_str = norm_text(out_df["レース"].iloc[0]) if "レース" in out_df.columns and len(out_df) else ""
        safe_name = re.sub(r"[^\w一-龥ぁ-んァ-ヶー]+", "_", f"{date_str}_{place_str}_{race_str}_straight_logic.csv")

        st.download_button(
            label="📥 v12.2互換CSVをダウンロード",
            data=df_to_csv_bytes(out_df),
            file_name=safe_name,
            mime="text/csv",
        )

else:
    st.info("CSVをアップロードすると、採点と変換結果が表示されます。")
