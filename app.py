import io
import re
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


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
    # 260510 -> 2026.05.10 と仮定
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


def load_font(size, bold=False):
    candidates = []
    if bold:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansJP-Bold.otf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf",
        ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


# =========================================
# Normalize Straight Logic CSV
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
        "他1": "他1",
        "他2": "他2",
        "他3": "他3",
        "対抗馬番": "対抗",
        "単穴馬番": "単穴",
        "連下馬番": "連下",
    }
    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    # normalize key columns
    for c in ["日付", "競馬場", "R", "馬番", "馬名"]:
        if c in df.columns:
            df[c] = df[c].map(norm_text)

    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date_like)

    # build straight label
    if "印" not in df.columns:
        df["印"] = "本命"

    # confidence
    if "信頼度" in df.columns:
        df["信頼度_num"] = df["信頼度"].map(to_float_safe)
    else:
        df["信頼度_num"] = 90.0

    def build_opponent_text(row):
        if "相手表示" in row.index and norm_text(row.get("相手表示", "")):
            return str(row.get("相手表示", ""))
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
# Normalize Teppan CSV
# =========================================
def normalize_teppan_df(df):
    df = df.copy()
    df.columns = [norm_col(c) for c in df.columns]

    rename_map = {
        "場所": "競馬場",
        "レース番号": "R",
        "馬番号": "馬番",
    }
    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    for c in ["日付", "競馬場", "R", "馬番", "馬名"]:
        if c in df.columns:
            df[c] = df[c].map(norm_text)
    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date_like)

    if "鉄板ランク" not in df.columns:
        # fallback if older column name or absent
        if "ランク" in df.columns:
            df = df.rename(columns={"ランク": "鉄板ランク"})
        else:
            df["鉄板ランク"] = "鉄板⭐️"

    if "判定" not in df.columns:
        df["判定"] = "採用"

    return df


# =========================================
# Combine Logic
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

    # straight side
    if row.get("straight_present", False):
        conf = row.get("信頼度_num", 90.0)
        if conf is None:
            conf = 90.0
        score += conf

        mark = norm_text(row.get("印", ""))
        if mark in ["本命", "◎"]:
            score += 20
        elif mark in ["○", "対抗"]:
            score += 10
        elif mark in ["▲", "単穴"]:
            score += 7
        elif mark in ["△", "連下"]:
            score += 4

    # teppan side
    teppan_rank = norm_text(row.get("鉄板ランク", ""))
    if teppan_rank == "超鉄板⭐️":
        score += 35
    elif teppan_rank == "強鉄板⭐️":
        score += 22
    elif teppan_rank == "鉄板⭐️":
        score += 10

    judge = norm_text(row.get("判定", ""))
    if judge == "採用":
        score += 8
    elif judge == "保留":
        score += 3

    # overlap bonus
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
    if "日付" not in out.columns:
        out["日付"] = ""
    if "競馬場" not in out.columns:
        out["競馬場"] = ""
    if "R" not in out.columns:
        out["R"] = ""
    if "馬番" not in out.columns:
        out["馬番"] = ""
    out["merge_key"] = (
        out["日付"].map(norm_text) + "|" +
        out["競馬場"].map(norm_text) + "|" +
        out["R"].map(norm_text) + "|" +
        out["馬番"].map(norm_text)
    )
    return out


def build_composite(straight_df, teppan_df):
    s = normalize_straight_df(straight_df)
    t = normalize_teppan_df(teppan_df)

    s = make_key(s)
    t = make_key(t)

    # Mark presence
    s["straight_present"] = True
    t["teppan_present"] = True

    merged = pd.merge(
        s,
        t,
        on="merge_key",
        how="outer",
        suffixes=("_straight", "_teppan")
    )

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
        row["鉄板ランク"] = row["鉄板ランク"] if norm_text(row["鉄板ランク"]) else ""
        row["複合ラベル"] = composite_label(row["straight_present"], row["鉄板ランク"])
        row["複合点"] = composite_score(row)
        row["総合ランク"] = composite_rank_label(row["複合点"])
        rows.append(row)

    out = pd.DataFrame(rows)

    # Deduplicate / choose best horse per race
    if out.empty:
        return out, out

    out["R_num"] = out["R"].map(to_int_safe).fillna(99)
    out["馬番_num"] = out["馬番"].map(to_int_safe).fillna(99)

    per_race = (
        out.sort_values(["日付", "競馬場", "R_num", "複合点", "馬番_num"], ascending=[True, True, True, False, True])
           .groupby(["日付", "競馬場", "R"], as_index=False)
           .first()
    )

    per_race = per_race.sort_values(["日付", "競馬場", "R_num", "複合点"], ascending=[True, True, True, False]).reset_index(drop=True)
    out = out.sort_values(["日付", "競馬場", "R_num", "複合点"], ascending=[True, True, True, False]).reset_index(drop=True)

    return per_race, out


# =========================================
# Image generation
# =========================================
def fit_text(draw, text, font, max_width):
    text = str(text)
    while len(text) > 1:
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            break
        text = text[:-1]
    return text


def draw_sns_image(df, image_date=""):
    # style
    bg = "#071322"
    gold = "#F0C84B"
    white = "#F6F4EF"
    gray = "#B4BBC8"
    line = "#233348"

    n = len(df)
    width = 1240
    top_pad = 48
    title_h = 200
    row_h = 132
    bottom_pad = 42
    height = top_pad + title_h + row_h * n + bottom_pad

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    f_small = load_font(26, bold=False)
    f_title = load_font(74, bold=True)
    f_date = load_font(46, bold=False)
    f_place = load_font(32, bold=True)
    f_num = load_font(42, bold=True)
    f_name = load_font(54, bold=True)
    f_sub = load_font(28, bold=False)
    f_tag = load_font(24, bold=False)

    # Header
    draw.text((74, top_pad), "TODAY'S PICKS", font=f_small, fill=gold)
    draw.text((74, top_pad + 42), "本日の推奨馬", font=f_title, fill=white)
    date_text = image_date if image_date else ""
    bbox = draw.textbbox((0, 0), date_text, font=f_date)
    draw.text((width - 74 - (bbox[2] - bbox[0]), top_pad + 56), date_text, font=f_date, fill=gold)

    y0 = top_pad + title_h - 20
    draw.line((74, y0, width - 74, y0), fill=line, width=2)

    for i, (_, row) in enumerate(df.iterrows()):
        y_top = top_pad + title_h + i * row_h
        y_bottom = y_top + row_h

        if i > 0:
            draw.line((74, y_top, width - 74, y_top), fill=line, width=2)

        place = f"{norm_text(row.get('競馬場',''))}\n{norm_text(row.get('R',''))}"
        horse_no = norm_text(row.get("馬番", ""))
        horse_name = str(row.get("馬名", ""))
        horse_name = fit_text(draw, horse_name, f_name, max_width=700)

        composite = norm_text(row.get("複合ラベル", ""))
        rank_lbl = norm_text(row.get("総合ランク", ""))
        opp = str(row.get("相手表示", "")).strip()

        # left venue block
        draw.multiline_text((74, y_top + 14), place, font=f_place, fill=gold, spacing=0)

        # number circle
        cx = 272
        cy = y_top + 66
        r = 44
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=gold)
        nb = draw.textbbox((0, 0), horse_no, font=f_num)
        nw = nb[2] - nb[0]
        nh = nb[3] - nb[1]
        draw.text((cx - nw / 2, cy - nh / 2 - 4), horse_no, font=f_num, fill=bg)

        # horse name
        draw.text((390, y_top + 18), horse_name, font=f_name, fill=white)

        # subline
        tag_text = f"[{rank_lbl}] {composite}"
        sub = tag_text
        if opp:
            sub += "  " + opp
        sub = fit_text(draw, sub, f_sub, max_width=760)
        draw.text((390, y_top + 82), sub, font=f_sub, fill=gray)

    return img


# =========================================
# UI
# =========================================
st.title("複合推奨馬SNSアプリ")
st.caption("直線ロジックCSVと鉄板⭐️血統CSVを読み込み、複合ランキングとSNS投稿用画像を1枚で出力します。")

with st.expander("入力CSVの想定列", expanded=False):
    st.markdown("**直線ロジックCSV**")
    st.code("日付,競馬場,R,レース名,馬番,馬名,信頼度,印,対抗,単穴,連下,他1,他2,相手表示", language="csv")
    st.markdown("**鉄板⭐️血統CSV**")
    st.code("日付,競馬場,R,レース名,馬番,馬名,鉄板ランク,判定", language="csv")
    st.caption("列名に多少ゆれがあっても吸収します。直線ロジック側は、相手表示がなくても対抗/単穴/連下/他から自動生成します。")

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
    one_per_race = st.checkbox("1レース1頭で出力", value=True)

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

        if per_race_df.empty:
            st.warning("複合該当馬がありませんでした。")
            st.stop()

        final_df = per_race_df if one_per_race else all_df

        st.success(f"複合該当 {len(final_df)}件を作成しました。")

        show_cols = [c for c in ["日付", "競馬場", "R", "馬番", "馬名", "総合ランク", "複合ラベル", "複合点", "信頼度_num", "鉄板ランク", "相手表示"] if c in final_df.columns]
        st.dataframe(final_df[show_cols], use_container_width=True, hide_index=True)

        rank_summary = final_df["総合ランク"].value_counts().rename_axis("総合ランク").reset_index(name="頭数")
        st.subheader("総合ランク内訳")
        st.dataframe(rank_summary, use_container_width=True, hide_index=True)

        # Image
        img = draw_sns_image(final_df, image_date=image_date)

        st.subheader("SNS投稿用画像")
        st.image(img, use_container_width=True)

        # CSV download
        csv_out = final_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("複合結果CSVをダウンロード", csv_out, file_name="composite_pick_result.csv", mime="text/csv", use_container_width=True)

        # PNG download
        png_path = Path("/tmp/composite_pick_image.png")
        img.save(png_path, format="PNG")
        with open(png_path, "rb") as f:
            st.download_button("SNS画像をダウンロード", f.read(), file_name="composite_pick_image.png", mime="image/png", use_container_width=True)

    except Exception as e:
        st.error("処理中にエラーが出ました。")
        st.exception(e)
