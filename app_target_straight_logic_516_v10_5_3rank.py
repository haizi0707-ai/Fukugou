# -*- coding: utf-8 -*-
"""
TARGET直線ロジック採点アプリ
５．１６直線２.csv 実データ列順対応版 + 推奨馬SVG + 買い目表示 + 重賞モード v10_5

実行:
    streamlit run app.py

更新点:
- 日本語フォント検出を強化（fc-match対応）
- 画像の文字サイズを全体的に拡大
- 画像レイアウトをスマホ閲覧向けに調整
- 馬名が長い場合の自動縮小に対応
"""

import io
import re
import unicodedata
import subprocess
import html
from pathlib import Path
from typing import Any, Optional, Tuple, List, Dict

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
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

INTERNAL_EXTRA_COLUMNS = ["間隔", "休み明け戦目"]

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
    "間隔",
    "休み明け戦目",
]
TARGET_COLUMNS = TARGET_COLUMNS_37
EXPECTED_TARGET_COLS = len(TARGET_COLUMNS_37)

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
# 10年検証結果から追加する補正
# =========================================================
# 追加補正:
# ・前4角相対45%以内：+4
# ・前3角相対45%以内：+2
# ・同競馬場：+3
# ・芝ダ替わり：-10
# ・前4角相対85%超：-6
# ・前走から距離延長：-3
# ・間隔4週以内：+2
# ・間隔8週以上：-3
# ・休み明け1戦目：-4
#
# 買いレース基準:
# ・総合評価点78点以上
# ・1位と2位の差8点以上
# ・展開予想評価 普通以上
# ・直線相性評価 普通以上
# ・芝ダ替わりではない
# ・前4角相対85%超ではない

def calc_added_corrections(row: pd.Series) -> Tuple[int, List[str], List[str]]:
    """
    10年検証結果から追加する補正点を計算。
    戻り値: 追加補正点, 補正理由リスト, 危険理由リスト
    """
    point = 0
    reasons = []
    dangers = []

    prev_field = to_int(row.get("前走頭数", ""))
    p3 = to_int(row.get("前3角通過順", ""))
    p4 = to_int(row.get("前4角通過順", ""))

    prev_track = norm(row.get("前走競馬場", ""))
    cur_track = norm(row.get("場所", ""))

    prev_surface = norm(row.get("前走芝ダ", ""))
    cur_surface = norm(row.get("芝ダ", ""))

    prev_dist = to_int(row.get("前走距離数値", ""))
    cur_dist = to_int(row.get("距離", ""))

    interval = to_int(row.get("間隔", ""))
    layoff_n = to_int(row.get("休み明け戦目", ""))

    # 前4角相対位置
    if prev_field and p4:
        r4 = p4 / prev_field
        if r4 <= 0.45:
            point += 4
            reasons.append("前4角45%以内+4")
        elif r4 > 0.85:
            point -= 6
            reasons.append("前4角85%超-6")
            dangers.append("前4角85%超")

    # 前3角相対位置
    if prev_field and p3:
        r3 = p3 / prev_field
        if r3 <= 0.45:
            point += 2
            reasons.append("前3角45%以内+2")

    # 同競馬場
    if prev_track and cur_track and prev_track == cur_track:
        point += 3
        reasons.append("同競馬場+3")

    # 芝ダ替わり
    if prev_surface and cur_surface and prev_surface != cur_surface:
        point -= 10
        reasons.append("芝ダ替わり-10")
        dangers.append("芝ダ替わり")

    # 距離延長
    if prev_dist and cur_dist and cur_dist > prev_dist:
        point -= 3
        reasons.append("距離延長-3")
        dangers.append("距離延長")

    # ローテ補正
    if interval is not None:
        if interval <= 4:
            point += 2
            reasons.append("間隔4週以内+2")
        elif interval >= 8:
            point -= 3
            reasons.append("間隔8週以上-3")
            dangers.append("間隔8週以上")

    if layoff_n == 1:
        point -= 4
        reasons.append("休み明け1戦目-4")
        dangers.append("休み明け1戦目")

    return int(point), reasons, dangers


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
            # 10年検証で前走1着の過大評価傾向が出たため +18 → +14
            score += 14
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
            base += 1 if style in ["差し", "追込", "好位"] else -1
        elif prev_type == "長い" and cur_type == "短い":
            base += 1 if style in ["逃げ", "先行", "好位"] else -1

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
    """
    TARGETのヘッダーなしCSVに列名を付ける。
    今回の標準は39列:
    37列目=前頭数、38列目=間隔、39列目=休み明け戦目。
    列数が増減しても、存在する列だけを使い、不足列は後段で空欄扱いにする。
    """
    df = df.copy()
    n = df.shape[1]

    cols = TARGET_COLUMNS_37[:n]
    if n > len(cols):
        cols += [f"未使用{i}" for i in range(n - len(cols))]

    df.columns = cols
    return df


# =========================================================
# 変換
# =========================================================

def convert_target_to_v12(df: pd.DataFrame, year: int, filter_7_12: bool, min_field_if_blank: int):
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

        interval = to_int(row.get("間隔", ""))
        layoff_n = to_int(row.get("休み明け戦目", ""))

        field_size = to_int(row.get("前頭数", ""))
        if field_size is None:
            field_size = fallback_field_size(finish, p1, p2, p3, p4, agari_rank, min_field_if_blank)

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
            "間隔": interval if interval is not None else "",
            "休み明け戦目": layoff_n if layoff_n is not None else "",
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
            "間隔": r.get("間隔", ""),
            "休み明け戦目": r.get("休み明け戦目", ""),
            "前走着順": r["_finish"] if r["_finish"] is not None else "",
            "前走着差": r["_margin"] if r["_margin"] is not None else "",
            "上3F順位": r["_agari_rank"] if r["_agari_rank"] is not None else "",
            "脚質推定": r["_style"],
            "前走直線ロジック点": prev_score,
            "展開予想評価": development_eval,
            "直線相性評価": straight_eval,
        })

    return pd.DataFrame(output_rows, columns=OUTPUT_COLUMNS + INTERNAL_EXTRA_COLUMNS), pd.DataFrame(debug_rows), flow


def make_quality_report(out_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in OUTPUT_COLUMNS:
        if col not in out_df.columns:
            rows.append({"列名": col, "空欄数": "列なし", "状態": "要確認"})
            continue

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
# 推奨馬抽出
# =========================================================

def build_ranking_df(v12_df: pd.DataFrame) -> pd.DataFrame:
    df = v12_df.copy()
    df["前走直線ロジック点"] = pd.to_numeric(df["前走直線ロジック点"], errors="coerce").fillna(0)
    df["展開補正点"] = df["展開予想評価"].map(EVAL_POINT_MAP).fillna(0)
    df["直線補正点"] = df["直線相性評価"].map(EVAL_POINT_MAP).fillna(0)

    correction_points = []
    correction_reasons = []
    danger_reasons = []

    for _, r in df.iterrows():
        p, reasons, dangers = calc_added_corrections(r)
        correction_points.append(p)
        correction_reasons.append(" / ".join(reasons))
        danger_reasons.append(" / ".join(dangers))

    df["追加補正点"] = correction_points
    df["補正理由"] = correction_reasons
    df["危険理由"] = danger_reasons

    # 10年検証後の新総合評価点
    df["総合評価点"] = (
        df["前走直線ロジック点"]
        + df["展開補正点"]
        + df["直線補正点"]
        + df["追加補正点"]
    ).clip(0, 100)

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
    df["印"] = df["順位"].map({1: "◎", 2: "○", 3: "▲", 4: "△", 5: "他1", 6: "他2"}).fillna("")
    return df


def pick_recommended_races(rank_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for race_key, g in rank_df.groupby("race_key"):
        g = g.sort_values(by=["順位", "総合評価点"], ascending=[True, False]).reset_index(drop=True)
        top = g.iloc[0]
        second_score = float(g.iloc[1]["総合評価点"]) if len(g) >= 2 else 0.0
        gap = float(top["総合評価点"]) - second_score
        top_score = float(top["総合評価点"])

        dev_ok = EVAL_ORDER.get(str(top["展開予想評価"]), -1) >= EVAL_ORDER["普通"]
        str_ok = EVAL_ORDER.get(str(top["直線相性評価"]), -1) >= EVAL_ORDER["普通"]

        danger_text = str(top.get("危険理由", ""))
        no_surface_change = "芝ダ替わり" not in danger_text
        no_deep_closer_risk = "前4角85%超" not in danger_text

        # 3段階表示
        candidate_flag = (
            top_score >= 75 and
            gap >= 4 and
            no_surface_change
        )
        normal_flag = (
            top_score >= 78 and
            gap >= 6 and
            dev_ok and
            str_ok and
            no_surface_change
        )
        strong_flag = (
            top_score >= 78 and
            gap >= 8 and
            dev_ok and
            str_ok and
            no_surface_change and
            no_deep_closer_risk
        )

        if not candidate_flag:
            continue

        if strong_flag:
            if gap >= 12:
                recommend_rank = "超強推奨"
            elif gap >= 10:
                recommend_rank = "強推奨"
            else:
                recommend_rank = "勝負候補"
        elif normal_flag:
            recommend_rank = "通常推奨"
        else:
            recommend_rank = "候補"

        item = {
            "推奨ランク": recommend_rank,
            "race_key": race_key,
            "日付": top["日付"],
            "場所": top["場所"],
            "レース": top["レース"],
            "レース名": top["レース名"],
            "馬番": top["馬番"],
            "馬名": top["馬名"],
            "総合評価点": round(top_score, 1),
            "2位との差": round(gap, 1),
            "展開予想評価": top["展開予想評価"],
            "直線相性評価": top["直線相性評価"],
            "追加補正点": top.get("追加補正点", 0),
            "補正理由": top.get("補正理由", ""),
            "危険理由": top.get("危険理由", ""),
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
            "相手表示": build_partner_text(r),
            "推奨ランク": r.get("推奨ランク", ""),
            "追加補正点": r.get("追加補正点", ""),
            "補正理由": r.get("補正理由", ""),
            "危険理由": r.get("危険理由", ""),
            "買い方ランク": r.get("買い方ランク", ""),
            "馬連買い目": r.get("馬連買い目", ""),
            "三連複買い目": r.get("三連複買い目", ""),
            "三連単買い目": r.get("三連単買い目", ""),
            "買い目点数": r.get("買い目点数", ""),
            "検証ROI": r.get("検証ROI", ""),
            "買い方コメント": r.get("買い方コメント", ""),
        })
    return pd.DataFrame(rows)


def build_buy_advice_columns(rec_df: pd.DataFrame) -> pd.DataFrame:
    """
    10年検証から得た買い方ロジックを通常推奨データに付与する。
    直線ロジックの点数補正ではなく、最終出力用の買い目情報として扱う。
    """
    out = rec_df.copy()

    buy_ranks = []
    exacta_bets = []
    trio_bets = []
    trifecta_bets = []
    bet_points = []
    rois = []
    comments = []

    for _, r in out.iterrows():
        rank = str(r.get("推奨ランク", ""))
        reasons = str(r.get("補正理由", ""))
        dangers = str(r.get("危険理由", ""))

        exacta = "◎-○▲△"
        trio = "◎-2〜6位"
        trifecta = ""
        points = ""
        roi = ""
        buy_rank = "参考"
        comment = "候補表示レース"

        if rank in ["超強推奨", "強推奨", "勝負候補"]:
            trifecta = "◎軸M2〜5位"
            points = "36点"

            if rank == "超強推奨":
                if "間隔4週以内+2" in reasons:
                    buy_rank = "激アツ"
                    roi = "148.2%"
                    comment = "超強推奨＋間隔4週以内"
                elif ("前4角45%以内+4" in reasons) and ("距離延長" not in dangers):
                    buy_rank = "激アツ"
                    roi = "140.9%"
                    comment = "超強推奨＋前4角45%以内＋距離延長なし"
                elif "距離延長" not in dangers:
                    buy_rank = "激アツ"
                    roi = "137.8%"
                    comment = "超強推奨＋距離延長なし"
                else:
                    buy_rank = "勝負候補"
                    roi = "115.3%"
                    comment = "超強推奨の三連単長期回収型"
            elif rank == "強推奨":
                if ("前4角45%以内+4" in reasons) and ("同競馬場+3" in reasons):
                    buy_rank = "安定候補"
                    trio = "◎-2〜4位"
                    trifecta = ""
                    points = "3点"
                    roi = "106.0%"
                    comment = "強推奨＋前4角45%以内＋同競馬場"
                else:
                    buy_rank = "攻め候補"
                    roi = "100.7%"
                    comment = "強推奨の三連単長期回収型"
            else:
                buy_rank = "勝負候補"
                roi = "参考"
                comment = "勝負候補レース"

        elif rank == "通常推奨":
            buy_rank = "通常推奨"
            comment = "馬連・三連複を基本表示"
        else:
            buy_rank = "候補"
            comment = "候補表示のみ"

        buy_ranks.append(buy_rank)
        exacta_bets.append(exacta)
        trio_bets.append(trio)
        trifecta_bets.append(trifecta)
        bet_points.append(points)
        rois.append(roi)
        comments.append(comment)

    out["買い方ランク"] = buy_ranks
    out["馬連買い目"] = exacta_bets
    out["三連複買い目"] = trio_bets
    out["三連単買い目"] = trifecta_bets
    out["買い目点数"] = bet_points
    out["検証ROI"] = rois
    out["買い方コメント"] = comments
    return out


# =========================================================
# 重賞モード
# =========================================================

def is_major_race_name(name: Any) -> bool:
    s = norm(name).upper()
    patterns = [
        "G1", "G2", "G3", "Ｇ１", "Ｇ２", "Ｇ３",
        "GⅠ", "GⅡ", "GⅢ", "JPN", "重賞",
        "ステークス", "カップ", "賞", "記念", "杯",
    ]
    return any(p in s for p in patterns)


def build_major_race_ranking(rank_df: pd.DataFrame, only_major_name: bool = True) -> pd.DataFrame:
    rows = []
    for race_key, g in rank_df.groupby("race_key"):
        g = g.sort_values(by=["順位", "総合評価点"], ascending=[True, False]).reset_index(drop=True)
        if len(g) == 0:
            continue

        race_name = str(g.iloc[0].get("レース名", ""))
        if only_major_name and not is_major_race_name(race_name):
            continue

        top = g.iloc[0]
        second_score = float(g.iloc[1]["総合評価点"]) if len(g) >= 2 else 0.0
        gap = float(top["総合評価点"]) - second_score
        danger = str(top.get("危険理由", ""))

        if "芝ダ替わり" in danger or "前4角85%超" in danger:
            reliability = "D"
            comment = "本命に危険条件あり。軸には慎重。"
        elif gap >= 12:
            reliability = "S"
            comment = "抜けた本命候補。"
        elif gap >= 8:
            reliability = "A"
            comment = "本命候補。"
        elif gap >= 4:
            reliability = "B"
            comment = "軸候補だが相手広め。"
        else:
            reliability = "C"
            comment = "混戦。単独本命は危険。"

        mark_map = {1: "◎", 2: "○", 3: "▲", 4: "△", 5: "☆", 6: "注"}

        for _, r in g.head(6).iterrows():
            rows.append({
                "race_key": race_key,
                "日付": r["日付"],
                "場所": r["場所"],
                "レース": r["レース"],
                "レース名": r["レース名"],
                "印": mark_map.get(int(r["順位"]), ""),
                "馬番": r["馬番"],
                "馬名": r["馬名"],
                "総合評価点": round(float(r["総合評価点"]), 1),
                "順位": int(r["順位"]),
                "重賞信頼度": reliability,
                "2位との差": round(gap, 1),
                "短評": comment if int(r["順位"]) == 1 else "",
                "補正理由": r.get("補正理由", ""),
                "危険理由": r.get("危険理由", ""),
            })

    return pd.DataFrame(rows)


def create_major_svg(major_df: pd.DataFrame) -> str:
    bg = "#020B1D"
    gold = "#E3BF4D"
    white = "#F6F6F6"
    gray = "#8D96A6"
    line = "#1E2A3F"
    accent = "#E6EAF2"

    width = 1080
    margin_x = 72
    header_h = 180
    race_header_h = 94
    row_h = 96
    bottom_pad = 60

    if len(major_df) == 0:
        height = 520
    else:
        groups = list(major_df.groupby("race_key"))
        height = 48 + header_h + bottom_pad
        for _, g in groups:
            height += race_header_h + row_h * len(g)

    font_family = "-apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', 'Noto Sans CJK JP', 'Noto Sans JP', sans-serif"

    date_code = ""
    if len(major_df) > 0:
        date_code = date_code_from_text(str(major_df.iloc[0]["日付"]))

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    parts.append(f'<rect width="100%" height="100%" fill="{bg}"/>')
    parts.append(f'<text x="{margin_x}" y="80" fill="{gold}" font-family="{font_family}" font-size="30" font-weight="700" letter-spacing="6">GRADE RACE</text>')
    parts.append(f'<text x="{margin_x}" y="165" fill="{white}" font-family="{font_family}" font-size="72" font-weight="800">重賞ランキング</text>')

    if date_code:
        parts.append(f'<text x="{width - margin_x}" y="150" fill="{gold}" font-family="{font_family}" font-size="44" font-weight="500" text-anchor="end" letter-spacing="10">{svg_escape_text(date_code)}</text>')

    y = 48 + header_h

    if len(major_df) == 0:
        parts.append(f'<text x="{margin_x}" y="{y + 100}" fill="{white}" font-family="{font_family}" font-size="44" font-weight="700">重賞候補が見つかりませんでした</text>')
    else:
        for _, g in major_df.groupby("race_key"):
            first = g.iloc[0]
            race_title = f'{first["場所"]} {first["レース"]} {first["レース名"]}'
            rel = first["重賞信頼度"]
            gap = first["2位との差"]

            parts.append(f'<line x1="{margin_x}" y1="{y}" x2="{width - margin_x}" y2="{y}" stroke="{line}" stroke-width="2"/>')
            parts.append(f'<text x="{margin_x}" y="{y + 48}" fill="{gold}" font-family="{font_family}" font-size="38" font-weight="800">{svg_escape_text(race_title)}</text>')
            parts.append(f'<text x="{width - margin_x}" y="{y + 48}" fill="{white}" font-family="{font_family}" font-size="34" font-weight="800" text-anchor="end">信頼度{svg_escape_text(rel)} / 差{svg_escape_text(gap)}</text>')
            y += race_header_h

            for _, r in g.iterrows():
                mark = svg_escape_text(r["印"])
                no = svg_escape_text(int(r["馬番"]) if str(r["馬番"]) != "" else "")
                name = svg_escape_text(r["馬名"])
                score = svg_escape_text(r["総合評価点"])

                parts.append(f'<text x="{margin_x}" y="{y + 58}" fill="{gold}" font-family="{font_family}" font-size="42" font-weight="800">{mark}</text>')
                parts.append(f'<circle cx="{margin_x + 92}" cy="{y + 45}" r="34" fill="{gold}"/>')
                parts.append(f'<text x="{margin_x + 92}" y="{y + 58}" fill="{bg}" font-family="{font_family}" font-size="32" font-weight="800" text-anchor="middle">{no}</text>')
                parts.append(f'<text x="{margin_x + 150}" y="{y + 58}" fill="{white}" font-family="{font_family}" font-size="42" font-weight="800">{name}</text>')
                parts.append(f'<text x="{width - margin_x}" y="{y + 58}" fill="{accent}" font-family="{font_family}" font-size="34" font-weight="700" text-anchor="end">{score}</text>')
                y += row_h

            if str(first.get("短評", "")):
                parts.append(f'<text x="{margin_x}" y="{y - 18}" fill="{gray}" font-family="{font_family}" font-size="28" font-weight="500">{svg_escape_text(first["短評"])}</text>')

    parts.append("</svg>")
    return "\\n".join(parts)


# =========================================================
# SVG画像生成：iPhone/Streamlit Cloud向け
# =========================================================

def svg_escape_text(x: Any) -> str:
    return html.escape(str(x), quote=True)


def create_picks_svg(rec_df: pd.DataFrame) -> str:
    # SVG版の推奨馬画像。買い目・点数・検証ROIも表示する。
    bg = "#020B1D"
    gold = "#E3BF4D"
    white = "#F6F6F6"
    gray = "#8D96A6"
    line = "#1E2A3F"
    soft = "#C9D2E3"

    width = 1080
    margin_x = 72
    top_pad = 48
    header_h = 190
    row_h = 238
    bottom_pad = 56
    count = max(len(rec_df), 1)
    height = top_pad + header_h + row_h * count + bottom_pad

    date_code = ""
    if len(rec_df) > 0:
        date_code = date_code_from_text(str(rec_df.iloc[0]["日付"]))

    font_family = "-apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', 'Noto Sans CJK JP', 'Noto Sans JP', sans-serif"

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    parts.append(f'<rect width="100%" height="100%" fill="{bg}"/>')
    parts.append(f'<text x="{margin_x}" y="80" fill="{gold}" font-family="{font_family}" font-size="30" font-weight="700" letter-spacing="6">TODAY&apos;S PICKS</text>')
    parts.append(f'<text x="{margin_x}" y="170" fill="{white}" font-family="{font_family}" font-size="74" font-weight="800">本日の推奨馬</text>')

    if date_code:
        parts.append(f'<text x="{width - margin_x}" y="155" fill="{gold}" font-family="{font_family}" font-size="44" font-weight="500" text-anchor="end" letter-spacing="10">{svg_escape_text(date_code)}</text>')

    y = top_pad + header_h

    for _, row in rec_df.iterrows():
        track = svg_escape_text(row["場所"])
        race = svg_escape_text(row["レース"])
        horse_no = svg_escape_text(int(row["馬番"]) if str(row["馬番"]) != "" else "")
        horse_name = svg_escape_text(row["馬名"])
        partner = svg_escape_text(build_partner_text(row))
        buy_rank = svg_escape_text(row.get("買い方ランク", ""))
        exacta = svg_escape_text(row.get("馬連買い目", ""))
        trio = svg_escape_text(row.get("三連複買い目", ""))
        trifecta = svg_escape_text(row.get("三連単買い目", ""))
        points = svg_escape_text(row.get("買い目点数", ""))
        roi = svg_escape_text(row.get("検証ROI", ""))
        comment = svg_escape_text(row.get("買い方コメント", ""))

        parts.append(f'<line x1="{margin_x}" y1="{y}" x2="{width - margin_x}" y2="{y}" stroke="{line}" stroke-width="2"/>')
        parts.append(f'<text x="{margin_x}" y="{y + 58}" fill="{gold}" font-family="{font_family}" font-size="44" font-weight="800">{track}</text>')
        parts.append(f'<text x="{margin_x}" y="{y + 108}" fill="{gold}" font-family="{font_family}" font-size="42" font-weight="800">{race}</text>')

        cx = 245
        cy = y + 78
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="46" fill="{gold}"/>')
        parts.append(f'<text x="{cx}" y="{cy + 15}" fill="{bg}" font-family="{font_family}" font-size="42" font-weight="800" text-anchor="middle">{horse_no}</text>')

        parts.append(f'<text x="340" y="{y + 72}" fill="{white}" font-family="{font_family}" font-size="56" font-weight="800">{horse_name}</text>')
        parts.append(f'<text x="340" y="{y + 118}" fill="{gray}" font-family="{font_family}" font-size="30" font-weight="500">{partner}</text>')
        parts.append(f'<text x="340" y="{y + 156}" fill="{soft}" font-family="{font_family}" font-size="28" font-weight="700">買い方ランク：{buy_rank}</text>')
        parts.append(f'<text x="340" y="{y + 190}" fill="{soft}" font-family="{font_family}" font-size="27" font-weight="500">馬連：{exacta}｜3複：{trio}</text>')

        third_line = comment
        if trifecta:
            third_line = f'3単：{trifecta}'
            if points:
                third_line += f'｜{points}'
            if roi:
                third_line += f'｜ROI{roi}'
        elif roi:
            third_line = f'ROI{roi}｜{comment}'

        parts.append(f'<text x="340" y="{y + 222}" fill="{gold}" font-family="{font_family}" font-size="27" font-weight="700">{svg_escape_text(third_line)}</text>')

        y += row_h

    parts.append("</svg>")
    return "\n".join(parts)


def svg_to_bytes(svg_text: str) -> bytes:
    return svg_text.encode("utf-8")

# =========================================================
# Streamlit UI
# =========================================================


st.set_page_config(page_title="TARGET直線ロジック採点", page_icon="🏇", layout="wide")

st.title("🏇 TARGET直線ロジック採点アプリ")
st.caption("v12.2互換CSV + 通常推奨SVG（買い目表示付き）+ 重賞ランキングSVG v10_5")

with st.expander("今回の抽出基準", expanded=True):
    st.write("""
    【候補】
    - 1位馬の総合評価点が **75点以上**
    - 1位と2位の差が **4点以上**
    - 本命馬が **芝ダ替わりではない**

    【通常推奨】
    - 1位馬の総合評価点が **78点以上**
    - 1位と2位の差が **6点以上**
    - 1位馬の **展開予想評価 = 普通以上**
    - 1位馬の **直線相性評価 = 普通以上**
    - 本命馬が **芝ダ替わりではない**

    【勝負候補】
    - 1位馬の総合評価点が **78点以上**
    - 1位と2位の差が **8点以上**
    - 1位馬の **展開予想評価 = 普通以上**
    - 1位馬の **直線相性評価 = 普通以上**
    - 本命馬が **芝ダ替わりではない**
    - 本命馬が **前4角相対85%超ではない**

    【重賞ランキング】
    - 重賞は買い条件を満たさなくてもランキング表示
    - 信頼度S/A/B/C/Dで表示
    - A以上は買い候補、Bは相手広め、C以下は混戦・見送り寄り

    【追加補正】
    - 間隔4週以内:+2、間隔8週以上:-3、休み明け1戦目:-4
    - 追加項目はCSVの最後列に置けば読み込みます
    """)

uploaded = st.file_uploader("TARGETから出力したCSVをアップロードしてください", type=["csv"])

min_field_if_blank = 12  # 安全用初期値。ウィジェットが未生成でもNameErrorを防止

col1, col2, col3, col4 = st.columns(4)
with col1:
    target_year = st.number_input("年", min_value=2020, max_value=2035, value=2026, step=1)
with col2:
    filter_7_12 = st.checkbox("7〜12Rのみ抽出", value=True)
with col3:
    min_field_if_blank = st.number_input("前頭数が空欄の時だけ使う最低頭数", min_value=1, max_value=18, value=12, step=1)
with col4:
    output_mode = st.selectbox("出力モード", ["両方", "通常推奨", "重賞ランキング"], index=0)

major_only_name = st.checkbox("重賞ランキングは重賞っぽいレース名だけ表示", value=True)

if uploaded is not None:
    try:
        raw_df = read_target_csv(uploaded)
        df = apply_columns(raw_df)
    except Exception as e:
        st.error(f"CSVを読み込めませんでした: {e}")
        st.stop()

    st.subheader("① 読み込み確認")
    st.write(f"行数: {len(df)} / 列数: {df.shape[1]}")
    if df.shape[1] < EXPECTED_TARGET_COLS:
        st.warning(f"想定列数 {EXPECTED_TARGET_COLS}列に対して、このCSVは {df.shape[1]}列です。不足列は空欄扱いになります。")
    elif df.shape[1] > EXPECTED_TARGET_COLS:
        st.info(f"想定列数 {EXPECTED_TARGET_COLS}列より多い列があります。余分な列は未使用列として読み込みます。")
    st.dataframe(df.head(30), use_container_width=True)

    v12_df, debug_df, flow = convert_target_to_v12(
        df=df,
        year=int(target_year),
        filter_7_12=filter_7_12,
        min_field_if_blank=int(min_field_if_blank) if "min_field_if_blank" in globals() or "min_field_if_blank" in locals() else 12,
    )

    flow_label = {"A": "A：単騎逃げ濃厚", "B": "B：先行争い軽め", "C": "C：先行争い激化", "D": "D：逃げ馬不在スロー"}.get(flow, flow)

    st.subheader("② v12.2互換CSV生成")
    st.info(f"展開タイプ：{flow_label}")
    st.dataframe(debug_df, use_container_width=True)

    st.subheader("③ v12.2互換CSVプレビュー")
    st.dataframe(v12_df, use_container_width=True)

    st.subheader("④ 空欄チェック")
    st.dataframe(make_quality_report(v12_df), use_container_width=True)

    st.download_button(
        label="📥 v12.2互換CSVをダウンロード",
        data=csv_bytes(v12_df[OUTPUT_COLUMNS]),
        file_name="straight_logic_v12_2_input.csv",
        mime="text/csv",
    )

    st.subheader("⑤ レース別ランキング")
    rank_df = build_ranking_df(v12_df)
    rank_view_cols = [
        "日付", "場所", "レース", "馬番", "馬名",
        "前走直線ロジック点", "展開予想評価", "直線相性評価",
        "間隔", "休み明け戦目", "追加補正点", "総合評価点",
        "順位", "印", "補正理由", "危険理由"
    ]
    rank_view_cols = [c for c in rank_view_cols if c in rank_df.columns]
    st.dataframe(rank_df[rank_view_cols].copy(), use_container_width=True)

    if output_mode in ["両方", "通常推奨"]:
        st.subheader("⑥ 本日の候補・推奨馬一覧")
        rec_df = pick_recommended_races(rank_df)
        rec_df = build_buy_advice_columns(rec_df)

        if len(rec_df) == 0:
            st.warning("候補・推奨基準を満たすレースはありませんでした。")
        else:
            export_df = build_export_csv(rec_df)
            view_cols = [
                "推奨ランク", "日付", "場所", "レース", "レース名", "馬番", "馬名",
                "総合評価点", "2位との差", "展開予想評価", "直線相性評価",
                "追加補正点", "補正理由", "危険理由",
                "買い方ランク", "馬連買い目", "三連複買い目", "三連単買い目", "買い目点数", "検証ROI", "買い方コメント",
                "○", "▲", "△", "他1", "他2"
            ]
            view_cols = [c for c in view_cols if c in rec_df.columns]
            st.dataframe(rec_df[view_cols].copy(), use_container_width=True)

            st.download_button(
                label="📥 推奨馬CSVをダウンロード",
                data=csv_bytes(export_df),
                file_name="todays_picks.csv",
                mime="text/csv",
            )

            st.subheader("⑦ 通常推奨SVG")
            svg_text = create_picks_svg(rec_df)

            components.html(
                f"""
                <div style="width:100%; max-width:720px; margin:0 auto;">
                    {svg_text}
                </div>
                """,
                height=min(1800, 320 + 250 * len(rec_df)),
                scrolling=True,
            )

            st.download_button(
                label="📥 通常推奨SVGをダウンロード",
                data=svg_to_bytes(svg_text),
                file_name="todays_picks.svg",
                mime="image/svg+xml",
            )

    if output_mode in ["両方", "重賞ランキング"]:
        st.subheader("⑧ 重賞ランキング")
        major_df = build_major_race_ranking(rank_df, only_major_name=major_only_name)

        if len(major_df) == 0:
            st.warning("重賞候補が見つかりませんでした。チェックを外すと全レースをランキング画像化できます。")
        else:
            st.dataframe(major_df, use_container_width=True)

            st.download_button(
                label="📥 重賞ランキングCSVをダウンロード",
                data=csv_bytes(major_df),
                file_name="major_race_ranking.csv",
                mime="text/csv",
            )

            major_svg = create_major_svg(major_df)

            components.html(
                f"""
                <div style="width:100%; max-width:720px; margin:0 auto;">
                    {major_svg}
                </div>
                """,
                height=min(1600, 320 + 115 * len(major_df)),
                scrolling=True,
            )

            st.download_button(
                label="📥 重賞ランキングSVGをダウンロード",
                data=svg_to_bytes(major_svg),
                file_name="major_race_ranking.svg",
                mime="image/svg+xml",
            )

else:
    st.info("CSVをアップロードすると、v12.2互換CSV・通常推奨SVG・重賞ランキングSVGを出力します。")
