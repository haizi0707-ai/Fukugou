# -*- coding: utf-8 -*-
"""
TARGET直線ロジック採点アプリ
５．１６直線２.csv 実データ列順対応版 + 推奨馬画像出力

実行:
    streamlit run app.py

今回の仕様:
- ５．１６直線２.csv の37列に対応
- 追加された「前頭数」を実数として使用
- 前3角/前4角が空欄の馬は空欄扱いのまま出力
- v12.2互換CSVを出力
- 標準基準で「買いレース」を抽出
- 添付イメージ風の縦長1枚PNGを生成
- PNG保存ボタン付き
"""

import io
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional, Tuple, List, Dict

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


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

EVAL_POINT_MAP = {
    "かなり向く": 8,
    "向く": 4,
    "普通": 0,
    "やや不向き": -4,
    "不向き": -8,
}

EVAL_ORDER = {
    "不向き": 0,
    "やや不向き": 1,
    "普通": 2,
    "向く": 3,
    "かなり向く": 4,
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
    TARGETの 516 → 2026.5.16 のように変換
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


def date_code_from_text(s: str) -> str:
    """
    2026.5.16 -> 516
    """
    t = norm(s)
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", t)
    if m:
        mm = int(m.group(2))
        dd = int(m.group(3))
        return f"{mm}{dd:02d}"
    return t.replace(".", "")


def parse_race_number(raw: Any) -> str:
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

    if p4 is not None and field_size:
        ratio4 = p4 / field_size
        if finish is not None:
            if ratio4 >= 0.65 and finish <= 5:
                score += 10
            elif ratio4 >= 0.45 and finish <= 3:
                score += 7
            elif ratio4 <= 0.25 and finish <= 3:
                score += 6
            elif ratio4 <= 0.45 and finish <= 5:
                score += 4
            if ratio4 >= 0.75 and finish >= 9:
                score -= 6

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

    cls = norm(prev_class)
    if any(k in cls for k in ["G1", "GI", "GⅠ", "Ｇ１"]):
        score += 8
    elif any(k in cls for k in ["G2", "GII", "GⅡ", "Ｇ２"]):
        score += 6
    elif any(k in cls for k in ["G3", "GIII", "GⅢ", "Ｇ３"]):
        score += 4
    elif any(k in cls for k in ["OP", "L", "リステッド", "オープン"]):
        score += 2

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
        "A": {"逃げ": "かなり向く", "先行": "かなり向く", "好位": "向く", "差し": "普通", "追込": "やや不向き"},
        "B": {"逃げ": "向く", "先行": "向く", "好位": "向く", "差し": "普通", "追込": "やや不向き"},
        "C": {"逃げ": "やや不向き", "先行": "普通", "好位": "向く", "差し": "向く", "追込": "普通"},
        "D": {"逃げ": "かなり向く", "先行": "かなり向く", "好位": "向く", "差し": "やや不向き", "追込": "不向き"},
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

    return {2: "かなり向く", 1: "向く", 0: "普通", -1: "やや不向き", -2: "不向き"}[base]


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

        field_size = to_int(row.get("前頭数", ""))
        if field_size is None:
            field_size = fallback_field_size(
                finish=finish, p1=p1, p2=p2, p3=p3, p4=p4, agari_rank=agari_rank, min_field=min_field_if_blank
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
        if col in ["前3角通過順", "前4角通過順", "前3角位置カテゴリ", "前4角位置カテゴリ"]:
            status = "空欄あり/許容" if blank > 0 else "OK"
        else:
            status = "OK" if blank == 0 or col == "レース名" else "要確認"
        rows.append({"列名": col, "空欄数": blank, "状態": status})
    return pd.DataFrame(rows)


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# =========================================================
# 推奨レース集計
# =========================================================

def build_ranking_df(v12_df: pd.DataFrame) -> pd.DataFrame:
    df = v12_df.copy()

    df["前走直線ロジック点"] = pd.to_numeric(df["前走直線ロジック点"], errors="coerce").fillna(0)
    df["展開補正点"] = df["展開予想評価"].map(EVAL_POINT_MAP).fillna(0)
    df["直線補正点"] = df["直線相性評価"].map(EVAL_POINT_MAP).fillna(0)

    # 画像出力用の総合評価点
    df["総合評価点"] = (df["前走直線ロジック点"] + df["展開補正点"] + df["直線補正点"]).clip(0, 100)

    df["race_key"] = (
        df["日付"].astype(str) + "_" +
        df["場所"].astype(str) + "_" +
        df["レース"].astype(str)
    )

    df = df.sort_values(
        by=["race_key", "総合評価点", "前走直線ロジック点", "馬番"],
        ascending=[True, False, False, True]
    ).reset_index(drop=True)

    df["順位"] = df.groupby("race_key").cumcount() + 1

    mark_map = {1: "◎", 2: "○", 3: "▲", 4: "△", 5: "他1", 6: "他2"}
    df["印"] = df["順位"].map(mark_map).fillna("")

    return df


def pick_recommended_races(rank_df: pd.DataFrame) -> pd.DataFrame:
    """
    標準基準:
    ・1位馬の総合評価点が78点以上
    ・1位と2位の差が4点以上
    ・1位馬の展開予想評価が普通以上
    ・1位馬の直線相性評価が普通以上
    """
    rows = []

    for race_key, g in rank_df.groupby("race_key"):
        g = g.sort_values(by=["順位", "総合評価点"], ascending=[True, False]).reset_index(drop=True)
        top = g.iloc[0]
        second_score = float(g.iloc[1]["総合評価点"]) if len(g) >= 2 else 0.0
        gap = float(top["総合評価点"]) - second_score

        dev_ok = EVAL_ORDER.get(str(top["展開予想評価"]), -1) >= EVAL_ORDER["普通"]
        str_ok = EVAL_ORDER.get(str(top["直線相性評価"]), -1) >= EVAL_ORDER["普通"]

        buy_flag = (
            float(top["総合評価点"]) >= 78 and
            gap >= 4 and
            dev_ok and
            str_ok
        )

        if not buy_flag:
            continue

        item = {
            "race_key": race_key,
            "日付": top["日付"],
            "場所": top["場所"],
            "レース": top["レース"],
            "レース名": top["レース名"],
            "馬番": top["馬番"],
            "馬名": top["馬名"],
            "総合評価点": round(float(top["総合評価点"]), 1),
            "前走直線ロジック点": float(top["前走直線ロジック点"]),
            "展開予想評価": top["展開予想評価"],
            "直線相性評価": top["直線相性評価"],
            "2位との差": round(gap, 1),
            "○": "",
            "▲": "",
            "△": "",
            "他1": "",
            "他2": "",
        }

        for _, r in g.iterrows():
            if r["順位"] == 2:
                item["○"] = int(r["馬番"]) if pd.notna(r["馬番"]) and str(r["馬番"]) != "" else ""
            elif r["順位"] == 3:
                item["▲"] = int(r["馬番"]) if pd.notna(r["馬番"]) and str(r["馬番"]) != "" else ""
            elif r["順位"] == 4:
                item["△"] = int(r["馬番"]) if pd.notna(r["馬番"]) and str(r["馬番"]) != "" else ""
            elif r["順位"] == 5:
                item["他1"] = int(r["馬番"]) if pd.notna(r["馬番"]) and str(r["馬番"]) != "" else ""
            elif r["順位"] == 6:
                item["他2"] = int(r["馬番"]) if pd.notna(r["馬番"]) and str(r["馬番"]) != "" else ""

        rows.append(item)

    rec_df = pd.DataFrame(rows)

    if len(rec_df) == 0:
        return rec_df

    rec_df["R数値"] = rec_df["レース"].astype(str).str.extract(r"(\d+)").astype(float)
    rec_df = rec_df.sort_values(by=["日付", "場所", "R数値", "総合評価点"], ascending=[True, True, True, False]).reset_index(drop=True)
    rec_df.drop(columns=["R数値"], inplace=True)

    return rec_df


def build_export_csv(rec_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in rec_df.iterrows():
        marks = []
        if str(r.get("○", "")) != "":
            marks.append(f"○{int(r['○'])}")
        if str(r.get("▲", "")) != "":
            marks.append(f"▲{int(r['▲'])}")
        if str(r.get("△", "")) != "":
            marks.append(f"△{int(r['△'])}")
        others = []
        if str(r.get("他1", "")) != "":
            others.append(str(int(r["他1"])))
        if str(r.get("他2", "")) != "":
            others.append(str(int(r["他2"])))
        if others:
            marks.append("他" + ", ".join(others))

        rows.append({
            "日付": r["日付"],
            "競馬場": r["場所"],
            "R": r["レース"],
            "レース名": r["レース名"],
            "馬番": int(r["馬番"]),
            "馬名": r["馬名"],
            "信頼度": r["総合評価点"],
            "印": "◎",
            "対抗": r["○"],
            "単穴": r["▲"],
            "連下": r["△"],
            "他1": r["他1"],
            "他2": r["他2"],
            "相手表示": " ".join(marks),
        })
    return pd.DataFrame(rows)


# =========================================================
# 画像生成
# =========================================================

def get_font_paths() -> Tuple[Optional[str], Optional[str]]:
    candidates_regular = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansJP-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    candidates_bold = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansJP-Bold.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    regular = None
    bold = None

    for p in candidates_regular:
        if Path(p).exists():
            regular = p
            break

    for p in candidates_bold:
        if Path(p).exists():
            bold = p
            break

    if bold is None:
        bold = regular
    return regular, bold


def load_font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    try:
        if path:
            return ImageFont.truetype(path, size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def text_bbox(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str, font) -> Tuple[int, int, int, int]:
    try:
        return draw.textbbox(xy, text, font=font)
    except Exception:
        w = int(len(text) * font.size)
        h = int(font.size * 1.2)
        return (xy[0], xy[1], xy[0] + w, xy[1] + h)


def build_partner_text(row: pd.Series) -> str:
    parts = []
    if str(row.get("○", "")) != "":
        parts.append(f"○{int(row['○'])}")
    if str(row.get("▲", "")) != "":
        parts.append(f"▲{int(row['▲'])}")
    if str(row.get("△", "")) != "":
        parts.append(f"△{int(row['△'])}")
    others = []
    if str(row.get("他1", "")) != "":
        others.append(str(int(row["他1"])))
    if str(row.get("他2", "")) != "":
        others.append(str(int(row["他2"])))
    if others:
        parts.append("他" + ", ".join(others))
    return " ".join(parts)


def create_picks_image(rec_df: pd.DataFrame) -> Image.Image:
    regular_path, bold_path = get_font_paths()

    bg = "#020B1D"
    gold = "#E3BF4D"
    white = "#F7F7F7"
    gray = "#8F96A3"
    line = "#223047"

    width = 1080
    top_pad = 80
    header_h = 180
    row_h = 155
    bottom_pad = 60
    count = len(rec_df)
    height = top_pad + header_h + row_h * count + bottom_pad

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    font_small_en = load_font(bold_path, 26)
    font_title = load_font(bold_path, 68)
    font_date = load_font(regular_path, 34)
    font_track = load_font(bold_path, 34)
    font_race = load_font(bold_path, 38)
    font_no = load_font(bold_path, 40)
    font_name = load_font(bold_path, 54)
    font_sub = load_font(regular_path, 30)

    # Header
    draw.text((80, 70), "TODAY'S PICKS", fill=gold, font=font_small_en)
    draw.text((80, 125), "本日の推奨馬", fill=white, font=font_title)

    date_code = ""
    if count > 0:
        date_code = date_code_from_text(str(rec_df.iloc[0]["日付"]))
    if date_code:
        bbox = text_bbox(draw, (0, 0), date_code, font_date)
        draw.text((width - 80 - (bbox[2] - bbox[0]), 115), date_code, fill=gold, font=font_date)

    y = top_pad + header_h

    for _, row in rec_df.iterrows():
        draw.line((80, y, width - 80, y), fill=line, width=2)

        # 左: 競馬場 + R
        left_x = 80
        track_y = y + 36
        draw.text((left_x, track_y), str(row["場所"]), fill=gold, font=font_track)
        draw.text((left_x, track_y + 42), str(row["レース"]), fill=gold, font=font_race)

        # 中: 丸い馬番
        cx = 250
        cy = y + 78
        radius = 45
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=gold)
        num_text = str(int(row["馬番"])) if str(row["馬番"]) != "" else ""
        nb = text_bbox(draw, (0, 0), num_text, font_no)
        nw = nb[2] - nb[0]
        nh = nb[3] - nb[1]
        draw.text((cx - nw / 2, cy - nh / 2 - 3), num_text, fill=bg, font=font_no)

        # 右: 馬名 + 相手表示
        name_x = 340
        name_y = y + 28
        draw.text((name_x, name_y), str(row["馬名"]), fill=white, font=font_name)

        sub_text = build_partner_text(row)
        draw.text((name_x, name_y + 70), sub_text, fill=gray, font=font_sub)

        y += row_h

    return img


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


# =========================================================
# Streamlit UI
# =========================================================

st.set_page_config(
    page_title="TARGET直線ロジック採点",
    page_icon="🏇",
    layout="wide",
)

st.title("🏇 TARGET直線ロジック採点アプリ")
st.caption("５．１６直線２.csv 実データ列順対応版 / v12.2互換CSV + 本日の推奨馬PNG")

with st.expander("今回の推奨馬抽出基準（標準）", expanded=True):
    st.write("""
    買いレース基準は、固定で以下を採用しています。

    - 1位馬の総合評価点が **78点以上**
    - 1位と2位の差が **4点以上**
    - 1位馬の **展開予想評価 = 普通以上**
    - 1位馬の **直線相性評価 = 普通以上**

    画像は、添付イメージ風の**縦長1枚PNG**で出力します。
    """)

uploaded = st.file_uploader("TARGETから出力したCSVをアップロードしてください", type=["csv"])

col1, col2, col3 = st.columns(3)
with col1:
    target_year = st.number_input("年", min_value=2020, max_value=2035, value=2026, step=1)
with col2:
    filter_7_12 = st.checkbox("7〜12Rのみ抽出", value=True)
with col3:
    min_field_if_blank = st.number_input("前頭数が空欄の時だけ使う最低頭数", min_value=1, max_value=18, value=12, step=1)

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
        st.warning(f"今回想定は37列ですが、このCSVは {df.shape[1]}列です。列数が変わるとズレる可能性があります。")

    st.subheader("② v12.2互換CSV生成")
    v12_df, debug_df, flow = convert_target_to_v12(
        df=df,
        year=int(target_year),
        filter_7_12=filter_7_12,
        min_field_if_blank=int(min_field_if_blank),
    )

    flow_label = {"A": "A：単騎逃げ濃厚", "B": "B：先行争い軽め", "C": "C：先行争い激化", "D": "D：逃げ馬不在スロー"}.get(flow, flow)
    st.info(f"展開タイプ：{flow_label}")

    st.dataframe(debug_df, use_container_width=True)

    st.subheader("③ v12.2互換CSVプレビュー")
    st.dataframe(v12_df, use_container_width=True)

    st.subheader("④ 空欄チェック")
    st.dataframe(make_quality_report(v12_df), use_container_width=True)

    st.download_button(
        label="📥 v12.2互換CSVをダウンロード",
        data=csv_bytes(v12_df),
        file_name="straight_logic_v12_2_input.csv",
        mime="text/csv",
    )

    st.subheader("⑤ レース別ランキング")
    rank_df = build_ranking_df(v12_df)
    rank_view = rank_df[[
        "日付", "場所", "レース", "馬番", "馬名", "前走直線ロジック点",
        "展開予想評価", "直線相性評価", "総合評価点", "順位", "印"
    ]].copy()
    st.dataframe(rank_view, use_container_width=True)

    st.subheader("⑥ 本日の推奨馬（標準基準）")
    rec_df = pick_recommended_races(rank_df)

    if len(rec_df) == 0:
        st.warning("標準基準を満たす買いレースはありませんでした。")
    else:
        export_df = build_export_csv(rec_df)

        view_df = rec_df[[
            "日付", "場所", "レース", "レース名", "馬番", "馬名",
            "総合評価点", "2位との差", "展開予想評価", "直線相性評価", "○", "▲", "△", "他1", "他2"
        ]].copy()
        st.dataframe(view_df, use_container_width=True)

        st.download_button(
            label="📥 推奨馬CSVをダウンロード",
            data=csv_bytes(export_df),
            file_name="todays_picks.csv",
            mime="text/csv",
        )

        img = create_picks_image(rec_df)
        png_bytes = image_to_png_bytes(img)

        st.subheader("⑦ 最終出力画像")
        st.image(img, caption="本日の推奨馬", use_container_width=True)

        st.download_button(
            label="📥 PNGをダウンロード",
            data=png_bytes,
            file_name="todays_picks.png",
            mime="image/png",
        )
else:
    st.info("CSVをアップロードすると、v12.2互換CSVと本日の推奨馬PNGを出力します。")
