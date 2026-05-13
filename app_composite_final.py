import io
import re
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import requests

st.set_page_config(page_title="複合推奨馬SNSアプリ", layout="wide")

# =========================================
# Utility
# =========================================
def read_csv_smart(path_or_buf):
    encodings = ["utf-8-sig", "utf-8", "cp932", "shift_jis"]
    last_err = None
    for enc in encodings:
        try:
            if isinstance(path_or_buf, (str, Path)):
                return pd.read_csv(path_or_buf, encoding=enc)
            path_or_buf.seek(0)
            return pd.read_csv(path_or_buf, encoding=enc)
        except Exception as e:
            last_err = e
    raise last_err


def norm_text(v):
    if pd.isna(v):
        return ""
    s = str(v).strip().replace("\u3000", " ")
    s = re.sub(r"\s+", "", s)
    if s.endswith(".0"):
        s = s[:-2]
    return s


def norm_col(c):
    s = str(c).strip().replace("\u3000", " ")
    s = s.replace("Ｒ", "R").replace("芝・ダ", "芝ダ").replace("～", "〜")
    s = re.sub(r"\s+", "", s)
    return s


def to_int_safe(v):
    if pd.isna(v):
        return None
    s = str(v).strip()
    m = re.search(r"\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def to_float_safe(v):
    if pd.isna(v):
        return None
    s = str(v).strip().replace("%", "").replace("％", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def parse_date_like(v):
    s = norm_text(v)
    if not s:
        return ""
    if re.fullmatch(r"\d{6}", s):
        yy = int(s[:2])
        mm = int(s[2:4])
        dd = int(s[4:6])
        return f"20{yy:02d}.{mm:02d}.{dd:02d}"
    if re.fullmatch(r"\d{8}", s):
        yyyy = s[:4]
        mm = s[4:6]
        dd = s[6:8]
        return f"{yyyy}.{mm}.{dd}"
    s = s.replace("/", ".").replace("-", ".")
    return s


def normalize_image_date(v):
    s = norm_text(v)
    if not s:
        return ""
    s = s.replace("/", ".").replace("-", ".")
    return s


FONT_CACHE_DIR = Path("/tmp/composite_ticket_fonts")


def ensure_japanese_font_path(bold=False):
    FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if bold:
        local_candidates = [
            Path("NotoSansCJKjp-Bold.otf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansJP-Bold.otf"),
        ]
        download_name = "NotoSansCJKjp-Bold.otf"
        download_url = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Japanese/NotoSansCJKjp-Bold.otf"
    else:
        local_candidates = [
            Path("NotoSansCJKjp-Regular.otf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf"),
        ]
        download_name = "NotoSansCJKjp-Regular.otf"
        download_url = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf"

    for p in local_candidates:
        if p.exists():
            return str(p)

    cached = FONT_CACHE_DIR / download_name
    if cached.exists():
        return str(cached)

    try:
        r = requests.get(download_url, timeout=30)
        if r.status_code == 200:
            cached.write_bytes(r.content)
            return str(cached)
    except Exception:
        pass

    return None


def load_font(size, bold=False):
    font_path = ensure_japanese_font_path(bold=bold)
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


VENUE_ORDER = {
    "札幌": 1, "函館": 2, "福島": 3, "新潟": 4, "東京": 5, "中山": 6,
    "中京": 7, "京都": 8, "阪神": 9, "小倉": 10,
}


def venue_priority(v):
    return VENUE_ORDER.get(norm_text(v), 999)


def mark_priority(v):
    v = norm_text(v)
    order = {"◎": 1, "本命": 1, "○": 2, "◯": 2, "対抗": 2, "▲": 3, "単穴": 3, "△": 4, "連下": 4, "他": 5}
    return order.get(v, 9)


def teppan_rank_priority(rank):
    t = norm_text(rank)
    if t == "超鉄板⭐️":
        return 3
    if t == "強鉄板⭐️":
        return 2
    if t == "鉄板⭐️":
        return 1
    return 0


def strongest_teppan_rank(ranks):
    ranks = [r for r in ranks if norm_text(r)]
    if not ranks:
        return ""
    return sorted(ranks, key=teppan_rank_priority, reverse=True)[0]


def teppan_flag_text(rank):
    r = norm_text(rank)
    if r == "超鉄板⭐️":
        return "激"
    if r in ["強鉄板⭐️", "鉄板⭐️"]:
        return "熱"
    return ""


def teppan_flag_color(rank):
    r = norm_text(rank)
    if r == "超鉄板⭐️":
        return "#E83F49"
    if r in ["強鉄板⭐️", "鉄板⭐️"]:
        return "#E8C24A"
    return "#111111"


# =========================================
# Straight CSV normalize
# =========================================
def normalize_straight_df(df):
    df = df.copy()
    df.columns = [norm_col(c) for c in df.columns]

    rename_map = {
        "場所": "競馬場",
        "レース番号": "R",
        "馬番号": "馬番",
        "本命馬番": "馬番",
        "推奨馬番": "馬番",
        "推奨馬": "馬名",
        "本命馬": "馬名",
        "日": "日付",
        "レース": "レース名",
        "信頼率": "信頼度",
        "信頼度%": "信頼度",
        "本命印": "印",
        "総合印": "印",
        "直線印": "印",
        "○": "対抗",
        "▲": "単穴",
        "△": "連下",
        "対抗馬番": "対抗",
        "単穴馬番": "単穴",
        "連下馬番": "連下",
        "○馬名": "対抗馬名",
        "◯馬名": "対抗馬名",
        "▲馬名": "単穴馬名",
        "△馬名": "連下馬名",
        "対抗名": "対抗馬名",
        "単穴名": "単穴馬名",
        "連下名": "連下馬名",
        "対抗馬": "対抗馬名",
        "単穴馬": "単穴馬名",
        "連下馬": "連下馬名",
    }
    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    for c in ["日付", "競馬場", "R", "馬番", "馬名", "対抗", "単穴", "連下", "他", "他1", "他2", "他3", "対抗馬名", "単穴馬名", "連下馬名"]:
        if c in df.columns:
            df[c] = df[c].map(norm_text)

    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date_like)

    if "印" not in df.columns:
        df["印"] = "◎"

    if "信頼度" in df.columns:
        df["信頼度_num"] = df["信頼度"].map(to_float_safe)
    else:
        df["信頼度_num"] = 90.0

    for c in ["他1", "他2", "他3", "他4"]:
        if c not in df.columns:
            df[c] = ""

    def build_opponent_text(row):
        parts = []
        if norm_text(row.get("対抗", "")):
            parts.append(f"○ {norm_text(row.get('対抗', ''))}")
        if norm_text(row.get("単穴", "")):
            parts.append(f"▲ {norm_text(row.get('単穴', ''))}")
        if norm_text(row.get("連下", "")):
            parts.append(f"△ {norm_text(row.get('連下', ''))}")
        others = []
        for c in ["他", "他1", "他2", "他3", "他4"]:
            v = norm_text(row.get(c, ""))
            if v:
                others.append(v)
        if others:
            parts.append("他 " + "、".join(others))
        return " ".join(parts)

    df["相手表示"] = df.apply(build_opponent_text, axis=1)
    return df


# =========================================
# Teppan CSV normalize
# =========================================
def normalize_teppan_df(df):
    df = df.copy()
    df.columns = [norm_col(c) for c in df.columns]
    rename_map = {"場所": "競馬場", "レース番号": "R", "馬番号": "馬番", "ランク": "鉄板ランク"}
    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    for c in ["日付", "競馬場", "R", "馬番", "馬名", "鉄板ランク", "判定", "印"]:
        if c in df.columns:
            df[c] = df[c].map(norm_text)
    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date_like)

    if "鉄板ランク" not in df.columns:
        df["鉄板ランク"] = "鉄板⭐️"
    if "判定" not in df.columns:
        df["判定"] = "採用"
    if "印" not in df.columns:
        df["印"] = ""
    return df


# =========================================
# Composite CSV for download
# =========================================
def composite_label(straight_present, teppan_rank):
    if straight_present and teppan_rank == "超鉄板⭐️":
        return "直線×超鉄板"
    if straight_present and teppan_rank == "強鉄板⭐️":
        return "直線×強鉄板"
    if straight_present and teppan_rank == "鉄板⭐️":
        return "直線×鉄板"
    if straight_present:
        return "直線推奨"
    if teppan_rank == "超鉄板⭐️":
        return "超鉄板単独"
    if teppan_rank == "強鉄板⭐️":
        return "強鉄板単独"
    return "鉄板単独"


def composite_score(row):
    score = 0.0
    if row.get("straight_present", False):
        conf = row.get("信頼度_num", 90.0)
        if conf is None:
            conf = 90.0
        score += conf
        mark = norm_text(row.get("印", ""))
        if mark in ["本命", "◎"]:
            score += 20
        elif mark in ["○", "◯", "対抗"]:
            score += 10
        elif mark in ["▲", "単穴"]:
            score += 7
        elif mark in ["△", "連下"]:
            score += 4

    tr = norm_text(row.get("鉄板ランク", ""))
    if tr == "超鉄板⭐️":
        score += 35
    elif tr == "強鉄板⭐️":
        score += 22
    elif tr == "鉄板⭐️":
        score += 10

    judge = norm_text(row.get("判定", ""))
    if judge == "採用":
        score += 8
    elif judge == "保留":
        score += 3

    if row.get("straight_present", False) and row.get("teppan_present", False):
        score += 18
    return round(score, 1)


def composite_rank_label(score):
    if score >= 145:
        return "SS"
    if score >= 125:
        return "S"
    if score >= 110:
        return "A"
    if score >= 95:
        return "B"
    return "C"


def make_key(df):
    out = df.copy()
    for c in ["日付", "競馬場", "R", "馬番"]:
        if c not in out.columns:
            out[c] = ""
    out["merge_key"] = (
        out["日付"].map(norm_text) + "|" + out["競馬場"].map(norm_text) + "|" + out["R"].map(norm_text) + "|" + out["馬番"].map(norm_text)
    )
    return out


def build_composite(straight_df, teppan_df):
    s = make_key(normalize_straight_df(straight_df))
    t = make_key(normalize_teppan_df(teppan_df))

    s["straight_present"] = True
    t["teppan_present"] = True

    merged = pd.merge(s, t, on="merge_key", how="outer", suffixes=("_straight", "_teppan"))

    def coalesce(row, a, b, default=""):
        va = row.get(a, "")
        vb = row.get(b, "")
        return va if norm_text(va) else (vb if norm_text(vb) else default)

    rows = []
    for _, r in merged.iterrows():
        row = {}
        row["日付"] = coalesce(r, "日付_straight", "日付_teppan")
        row["競馬場"] = coalesce(r, "競馬場_straight", "競馬場_teppan")
        row["R"] = coalesce(r, "R_straight", "R_teppan")
        row["レース名"] = coalesce(r, "レース名", "レース名_teppan")
        row["馬番"] = coalesce(r, "馬番_straight", "馬番_teppan")
        row["馬名"] = coalesce(r, "馬名_straight", "馬名_teppan")
        row["straight_present"] = bool(r.get("straight_present", False)) if pd.notna(r.get("straight_present", False)) else False
        row["teppan_present"] = bool(r.get("teppan_present", False)) if pd.notna(r.get("teppan_present", False)) else False
        row["信頼度_num"] = r.get("信頼度_num", None)
        row["印"] = r.get("印", "")
        row["相手表示"] = r.get("相手表示", "")
        row["鉄板ランク"] = coalesce(r, "鉄板ランク", "鉄板ランク_teppan")
        row["判定"] = coalesce(r, "判定", "判定_teppan", default="採用")
        row["複合ラベル"] = composite_label(row["straight_present"], row["鉄板ランク"])
        row["複合点"] = composite_score(row)
        row["総合ランク"] = composite_rank_label(row["複合点"])
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out, out
    out["R_num"] = out["R"].map(to_int_safe).fillna(99)
    out["馬番_num"] = out["馬番"].map(to_int_safe).fillna(999)
    out = out.sort_values(["日付", "競馬場", "R_num", "複合点", "馬番_num"], ascending=[True, True, True, False, True]).reset_index(drop=True)
    per_race = (
        out.sort_values(["日付", "競馬場", "R_num", "複合点", "馬番_num"], ascending=[True, True, True, False, True])
           .groupby(["日付", "競馬場", "R"], as_index=False)
           .first()
    )
    return per_race, out


def dedupe_composite_rows(df):
    if df.empty:
        return df.copy()
    work = df.copy()
    work["R_num"] = work["R"].map(to_int_safe).fillna(99)
    work["馬番_num"] = work["馬番"].map(to_int_safe).fillna(999)
    work = work.sort_values(["日付", "競馬場", "R_num", "馬番_num", "複合点"], ascending=[True, True, True, True, False]).copy()
    grouped = []
    keys = ["日付", "競馬場", "R", "馬番", "馬名"]
    for _, g in work.groupby(keys, dropna=False, sort=False):
        first = g.iloc[0].copy()
        first["straight_present"] = bool(g["straight_present"].fillna(False).any()) if "straight_present" in g.columns else False
        first["teppan_present"] = bool(g["teppan_present"].fillna(False).any()) if "teppan_present" in g.columns else False
        ranks = [x for x in g.get("鉄板ランク", []).tolist() if norm_text(x)]
        first["鉄板ランク"] = strongest_teppan_rank(ranks)
        opps = [str(x) for x in g.get("相手表示", []).tolist() if norm_text(x)]
        if opps:
            first["相手表示"] = opps[0]
        first["複合ラベル"] = composite_label(first["straight_present"], first["鉄板ランク"])
        first["複合点"] = composite_score(first)
        first["総合ランク"] = composite_rank_label(first["複合点"])
        grouped.append(first)
    out = pd.DataFrame(grouped)
    out["R_num"] = out["R"].map(to_int_safe).fillna(99)
    out["馬番_num"] = out["馬番"].map(to_int_safe).fillna(999)
    out = out.sort_values(["日付", "競馬場", "R_num", "複合点", "馬番_num"], ascending=[True, True, True, False, True]).reset_index(drop=True)
    return out


# =========================================
# Ticket-style race cards
# =========================================
def choose_straight_main(g):
    g = g.copy()
    g["R_num"] = g["R"].map(to_int_safe).fillna(99)
    g["馬番_num"] = g["馬番"].map(to_int_safe).fillna(999)
    g["mark_pri"] = g["印"].map(mark_priority)
    g["信頼度_num"] = g["信頼度_num"].fillna(90)
    g = g.sort_values(["mark_pri", "信頼度_num", "馬番_num"], ascending=[True, False, True])
    return g.iloc[0].copy()


def find_teppan_rank_for_num(t_race, num):
    num = norm_text(num)
    if not num:
        return ""
    x = t_race[t_race["馬番"].map(norm_text) == num]
    if x.empty:
        return ""
    return strongest_teppan_rank(x["鉄板ランク"].tolist())


def build_race_cards(straight_df, teppan_df):
    s = normalize_straight_df(straight_df)
    t = normalize_teppan_df(teppan_df)

    if not s.empty:
        s["R_num"] = s["R"].map(to_int_safe).fillna(99)
        s["venue_order"] = s["競馬場"].map(venue_priority)
    if not t.empty:
        t["R_num"] = t["R"].map(to_int_safe).fillna(99)
        t["venue_order"] = t["競馬場"].map(venue_priority)
        t["馬番_num"] = t["馬番"].map(to_int_safe).fillna(999)
        t["rank_pri"] = t["鉄板ランク"].map(teppan_rank_priority)
        t["mark_pri"] = t["印"].map(mark_priority)
        t = t.sort_values(["venue_order", "R_num", "rank_pri", "mark_pri", "馬番_num"], ascending=[True, True, False, True, True])
        t = t.drop_duplicates(subset=["日付", "競馬場", "R", "馬番", "馬名"], keep="first")

    keys = set()
    if not s.empty:
        for _, r in s.iterrows():
            keys.add((norm_text(r.get("日付", "")), norm_text(r.get("競馬場", "")), int(r.get("R_num", 99))))
    if not t.empty:
        for _, r in t.iterrows():
            keys.add((norm_text(r.get("日付", "")), norm_text(r.get("競馬場", "")), int(r.get("R_num", 99))))

    sort_keys = sorted(keys, key=lambda x: (venue_priority(x[1]), x[2], x[0]))
    cards = []
    for date, place, rnum in sort_keys:
        s_race = s[(s["日付"].map(norm_text) == date) & (s["競馬場"].map(norm_text) == place) & (s["R_num"] == rnum)].copy() if not s.empty else pd.DataFrame()
        t_race = t[(t["日付"].map(norm_text) == date) & (t["競馬場"].map(norm_text) == place) & (t["R_num"] == rnum)].copy() if not t.empty else pd.DataFrame()
        race_name = ""
        lines = []
        mode = "teppan_only"

        if not s_race.empty:
            mode = "straight"
            main = choose_straight_main(s_race)
            race_name = norm_text(main.get("レース名", ""))
            main_rank = find_teppan_rank_for_num(t_race, main.get("馬番", ""))
            lines.append({
                "mark": "◎",
                "num": norm_text(main.get("馬番", "")),
                "name": norm_text(main.get("馬名", "")),
                "flag": teppan_flag_text(main_rank),
                "flag_color": teppan_flag_color(main_rank),
            })

            for mark_symbol, num_col, name_col in [("◯", "対抗", "対抗馬名"), ("▲", "単穴", "単穴馬名"), ("△", "連下", "連下馬名")]:
                num_val = norm_text(main.get(num_col, ""))
                if num_val:
                    name_val = norm_text(main.get(name_col, ""))
                    rank = find_teppan_rank_for_num(t_race, num_val)
                    lines.append({
                        "mark": mark_symbol,
                        "num": num_val,
                        "name": name_val,
                        "flag": teppan_flag_text(rank),
                        "flag_color": teppan_flag_color(rank),
                    })

            others = []
            for c in ["他", "他1", "他2", "他3", "他4"]:
                v = norm_text(main.get(c, ""))
                if v:
                    others.append(v)
            if others:
                joined = "、".join([x for x in others if x])
                lines.append({"mark": "他", "num": "", "name": joined, "flag": "", "flag_color": "#111111"})

        else:
            if not t_race.empty:
                race_name = norm_text(t_race.iloc[0].get("レース名", ""))
            for _, row in t_race.iterrows():
                rank = norm_text(row.get("鉄板ランク", ""))
                lines.append({
                    "mark": "",
                    "num": norm_text(row.get("馬番", "")),
                    "name": norm_text(row.get("馬名", "")),
                    "flag": teppan_flag_text(rank),
                    "flag_color": teppan_flag_color(rank),
                })

        cards.append({
            "date": date,
            "競馬場": place,
            "R": f"{rnum}R",
            "R_num": rnum,
            "レース名": race_name,
            "mode": mode,
            "lines": lines,
        })

    return cards


def draw_fake_barcode(draw, x, y, w, h, color="#111111"):
    pattern = [1, 1, 2, 1, 3, 1, 1, 2, 1, 4, 2, 1, 3, 1, 1, 2, 2, 1, 4, 1, 2, 1, 3, 1, 1]
    total = sum(pattern)
    unit = max(1, int(w / total))
    cur_x = x
    for i, p in enumerate(pattern):
        bar_w = p * unit
        if i % 2 == 0:
            draw.rectangle((cur_x, y, cur_x + bar_w - 1, y + h), fill=color)
        cur_x += bar_w


def fit_text_to_width(draw, text, font, max_width):
    t = str(text)
    if not t:
        return t
    while len(t) > 1:
        bb = draw.textbbox((0, 0), t, font=font)
        if bb[2] - bb[0] <= max_width:
            return t
        t = t[:-1]
    return t


def draw_ticket_poster(cards, image_date=""):
    # Theme colors
    bg = "#031226"
    gold = "#E8C24A"
    gold2 = "#C8972C"
    white = "#F5F2EA"
    paper = "#F3ECD9"
    ink = "#111111"
    red = "#E83F49"
    line = "#B8A57B"
    navy = "#0A2345"

    width = 940
    margin_x = 34
    top = 22
    header_h = 168
    col_gap = 16
    row_gap = 18
    cols = 2
    card_w = (width - margin_x * 2 - col_gap) // 2

    f_title = load_font(72, bold=True)
    f_sub_en = load_font(30, bold=True)
    f_date = load_font(34, bold=False)
    f_legend = load_font(22, bold=True)
    f_header = load_font(32, bold=True)
    f_header_small = load_font(17, bold=False)
    f_mark = load_font(28, bold=True)
    f_num = load_font(30, bold=True)
    f_name = load_font(28, bold=True)
    f_other = load_font(28, bold=True)
    f_flag = load_font(30, bold=True)
    f_footer = load_font(16, bold=True)

    def calc_card_h(card):
        lines = card.get("lines", [])
        line_count = max(1, len(lines))
        body_h = 22 + line_count * 42 + 12
        footer_h = 44
        return 84 + body_h + footer_h

    row_heights = []
    for i in range(0, len(cards), cols):
        group = cards[i:i + cols]
        row_heights.append(max(calc_card_h(c) for c in group))

    height = top + header_h + sum(row_heights) + row_gap * max(0, len(row_heights) - 1) + 28
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    draw.rectangle((8, 8, width - 8, height - 8), outline=gold2, width=3)
    draw.rectangle((18, 18, width - 18, height - 18), outline=gold2, width=1)

    draw.text((68, top), "本日の推奨馬", font=f_title, fill=gold)
    subtitle = "TODAY’S PICKS"
    sub_y = top + 92
    draw.line((72, sub_y + 16, 230, sub_y + 16), fill=gold, width=2)
    draw.line((410, sub_y + 16, 570, sub_y + 16), fill=gold, width=2)
    draw.text((245, sub_y), subtitle, font=f_sub_en, fill=gold)

    date_text = normalize_image_date(image_date)
    if not date_text and cards:
        date_text = cards[0].get("date", "")
    if date_text:
        bb = draw.textbbox((0, 0), date_text, font=f_date)
        draw.text((width - margin_x - (bb[2] - bb[0]), top + 18), date_text, font=f_date, fill=gold)

    legend_x = width - 320
    legend_y = top + 64
    draw.text((legend_x, legend_y), "激", font=f_legend, fill=red)
    draw.text((legend_x + 28, legend_y), "=超鉄板", font=f_legend, fill=white)
    draw.text((legend_x + 126, legend_y), "熱", font=f_legend, fill=gold)
    draw.text((legend_x + 154, legend_y), "=鉄板", font=f_legend, fill=white)
    draw.text((legend_x, legend_y + 30), "印", font=f_legend, fill=white)
    draw.text((legend_x + 28, legend_y + 30), "=直線ロジック", font=f_legend, fill=white)

    y = top + header_h
    card_idx = 0
    for row_h in row_heights:
        for col_i in range(cols):
            if card_idx >= len(cards):
                break
            card = cards[card_idx]
            card_idx += 1

            x0 = margin_x + col_i * (card_w + col_gap)
            y0 = y
            x1 = x0 + card_w
            y1 = y0 + row_h

            draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=paper, outline=gold2, width=2)
            draw.rounded_rectangle((x0 + 8, y0 + 8, x1 - 8, y0 + 74), radius=14, fill=navy, outline=gold2, width=2)

            head_txt = f"{norm_text(card.get('競馬場', ''))} {norm_text(card.get('R', ''))}"
            hb = draw.textbbox((0, 0), head_txt, font=f_header)
            draw.text((x0 + (card_w - (hb[2] - hb[0])) / 2, y0 + 18), head_txt, font=f_header, fill=white)

            race_name = norm_text(card.get("レース名", ""))
            if race_name:
                race_name = fit_text_to_width(draw, race_name, f_header_small, card_w - 40)
                rb = draw.textbbox((0, 0), race_name, font=f_header_small)
                draw.text((x0 + (card_w - (rb[2] - rb[0])) / 2, y0 + 50), race_name, font=f_header_small, fill=white)

            lines = card.get("lines", [])
            line_y = y0 + 94
            mark_w = 38
            num_w = 42
            name_x = x0 + 18 + mark_w + num_w + 18
            flag_x = x1 - 40

            for i, line_row in enumerate(lines):
                yy = line_y + i * 42
                draw.line((x0 + 18, yy + 34, x1 - 18, yy + 34), fill=line, width=1)
                mark = norm_text(line_row.get("mark", ""))
                num = norm_text(line_row.get("num", ""))
                name = norm_text(line_row.get("name", ""))
                flag = norm_text(line_row.get("flag", ""))
                flag_color = line_row.get("flag_color", ink)

                if mark:
                    draw.text((x0 + 18, yy), mark, font=f_mark, fill=ink)
                if num:
                    draw.text((x0 + 18 + mark_w, yy), num, font=f_num, fill=ink)

                name_font = f_name if mark != "他" else f_other
                name_max = (flag_x - 8) - name_x
                text_val = fit_text_to_width(draw, name, name_font, max(80, name_max))
                draw.text((name_x, yy), text_val, font=name_font, fill=ink)

                if flag:
                    fb = draw.textbbox((0, 0), flag, font=f_flag)
                    draw.text((flag_x - (fb[2] - fb[0]), yy), flag, font=f_flag, fill=flag_color)

            footer_y = y1 - 38
            draw.text((x0 + 18, footer_y), "TODAY’S PICKS", font=f_footer, fill=ink)
            draw.line((x0 + 136, footer_y + 10, x0 + 136, footer_y + 28), fill=line, width=2)
            draw_fake_barcode(draw, x0 + 164, footer_y + 2, 122, 24, color=ink)
            code = f"{norm_text(card.get('競馬場', ''))[:1]}{norm_text(card.get('R', '')).replace('R', '').zfill(2)}-{normalize_image_date(date_text).replace('.', '') if date_text else ''}-{str(card_idx).zfill(3)}"
            draw.text((x0 + 168, footer_y + 22), code, font=f_footer, fill=ink)

        y += row_h + row_gap

    return img
st.title("複合推奨馬SNSアプリ（馬券風レイアウト版）")
st.caption("直線ロジックCSVと鉄板⭐️血統CSVを読み込み、複合結果CSVと馬券風SNS画像を作成します。")

col1, col2 = st.columns(2)

with col1:
    st.subheader("直線ロジックCSV")
    straight_mode = st.radio("入力方法（直線ロジック）", ["貼り付け", "ファイル読み込み"], key="s_mode", horizontal=True)
    straight_text = ""
    straight_file = None
    if straight_mode == "貼り付け":
        straight_text = st.text_area("直線ロジックCSVを貼り付け", height=240, key="s_text")
    else:
        straight_file = st.file_uploader("直線ロジックCSVファイル", type=["csv"], key="s_file")

with col2:
    st.subheader("鉄板⭐️血統CSV")
    teppan_mode = st.radio("入力方法（鉄板⭐️）", ["貼り付け", "ファイル読み込み"], key="t_mode", horizontal=True)
    teppan_text = ""
    teppan_file = None
    if teppan_mode == "貼り付け":
        teppan_text = st.text_area("鉄板⭐️CSVを貼り付け", height=240, key="t_text")
    else:
        teppan_file = st.file_uploader("鉄板⭐️CSVファイル", type=["csv"], key="t_file")

colA, colB = st.columns([2, 1])
with colA:
    image_date = st.text_input("画像に表示する日付", value=datetime.now().strftime("%Y.%m.%d"))
with colB:
    st.caption("出力画像は縦長の馬券風レイアウトです。")

run = st.button("複合結果を作成", type="primary", use_container_width=True)

if run:
    try:
        if straight_mode == "貼り付け":
            if not straight_text.strip():
                st.warning("直線ロジックCSVを入力してください。")
                st.stop()
            straight_df = read_csv_smart(io.StringIO(straight_text))
        else:
            if straight_file is None:
                st.warning("直線ロジックCSVファイルを選択してください。")
                st.stop()
            straight_df = read_csv_smart(straight_file)

        if teppan_mode == "貼り付け":
            if not teppan_text.strip():
                st.warning("鉄板⭐️CSVを入力してください。")
                st.stop()
            teppan_df = read_csv_smart(io.StringIO(teppan_text))
        else:
            if teppan_file is None:
                st.warning("鉄板⭐️CSVファイルを選択してください。")
                st.stop()
            teppan_df = read_csv_smart(teppan_file)

        per_race_df, all_df = build_composite(straight_df, teppan_df)
        final_df = dedupe_composite_rows(all_df)
        cards = build_race_cards(straight_df, teppan_df)

        if not cards:
            st.warning("複合該当馬がありませんでした。")
            st.stop()

        st.success(f"複合該当 {len(final_df)}件 / 表示レース {len(cards)}件 を作成しました。")

        show_cols = [c for c in ["日付", "競馬場", "R", "馬番", "馬名", "総合ランク", "複合ラベル", "複合点", "信頼度_num", "鉄板ランク", "相手表示"] if c in final_df.columns]
        st.dataframe(final_df[show_cols], use_container_width=True, hide_index=True)

        img = draw_ticket_poster(cards, image_date=image_date)
        st.subheader("SNS投稿用画像")
        st.image(img, use_container_width=True)

        csv_out = final_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("複合結果CSVをダウンロード", csv_out, file_name="composite_pick_result.csv", mime="text/csv", use_container_width=True)

        png_path = Path("/tmp/composite_pick_ticket_image.png")
        img.save(png_path, format="PNG")
        with open(png_path, "rb") as f:
            st.download_button("SNS画像をダウンロード", f.read(), file_name="composite_pick_ticket_image.png", mime="image/png", use_container_width=True)

    except Exception as e:
        st.error("処理中にエラーが出ました。")
        st.exception(e)
