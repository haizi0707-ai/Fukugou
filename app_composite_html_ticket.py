import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="複合推奨馬SNSアプリ HTML版", layout="wide")


def read_csv_smart(obj):
    encodings = ["utf-8-sig", "utf-8", "cp932", "shift_jis"]
    last_err = None
    for enc in encodings:
        try:
            if isinstance(obj, str):
                return pd.read_csv(io.StringIO(obj), encoding=enc)
            obj.seek(0)
            return pd.read_csv(obj, encoding=enc)
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
    s = str(c).strip().replace("\u3000", "")
    s = s.replace("Ｒ", "R").replace("芝・ダ", "芝ダ").replace("～", "〜")
    s = re.sub(r"\s+", "", s)
    return s


def to_int(v, default=999):
    m = re.search(r"\d+", str(v))
    if not m:
        return default
    try:
        return int(m.group(0))
    except Exception:
        return default


def parse_date(v):
    s = norm_text(v)
    if not s:
        return ""
    if re.fullmatch(r"\d{6}", s):
        return f"20{s[:2]}.{s[2:4]}.{s[4:6]}"
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}.{s[4:6]}.{s[6:8]}"
    s = s.replace("/", ".").replace("-", ".")
    parts = s.split(".")
    if len(parts) == 3:
        return f"{parts[0]}.{parts[1].zfill(2)}.{parts[2].zfill(2)}"
    return s


def esc(s):
    s = str(s)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def normalize_straight(df):
    df = df.copy()
    df.columns = [norm_col(c) for c in df.columns]

    rename = {
        "場所": "競馬場",
        "レース番号": "R",
        "馬番号": "馬番",
        "本命馬番": "馬番",
        "推奨馬番": "馬番",
        "推奨馬": "馬名",
        "本命馬": "馬名",
        "レース": "レース名",
        "日": "日付",
        "信頼率": "信頼度",
        "信頼度%": "信頼度",
        "○": "対抗",
        "◯": "対抗",
        "▲": "単穴",
        "△": "連下",
        "対抗馬番": "対抗",
        "単穴馬番": "単穴",
        "連下馬番": "連下",
        "○馬名": "対抗馬名",
        "◯馬名": "対抗馬名",
        "▲馬名": "単穴馬名",
        "△馬名": "連下馬名",
        "対抗馬": "対抗馬名",
        "単穴馬": "単穴馬名",
        "連下馬": "連下馬名",
        "対抗名": "対抗馬名",
        "単穴名": "単穴馬名",
        "連下名": "連下馬名",
    }
    for old, new in rename.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    for c in [
        "日付", "競馬場", "R", "レース名", "馬番", "馬名", "印",
        "対抗", "単穴", "連下", "他", "他1", "他2", "他3", "他4",
        "対抗馬名", "単穴馬名", "連下馬名"
    ]:
        if c in df.columns:
            df[c] = df[c].map(norm_text)

    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date)
    else:
        df["日付"] = ""

    if "印" not in df.columns:
        df["印"] = "◎"

    for c in ["他", "他1", "他2", "他3", "他4"]:
        if c not in df.columns:
            df[c] = ""

    return df


def normalize_teppan(df):
    df = df.copy()
    df.columns = [norm_col(c) for c in df.columns]
    rename = {"場所": "競馬場", "レース番号": "R", "馬番号": "馬番", "ランク": "鉄板ランク"}
    for old, new in rename.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    for c in ["日付", "競馬場", "R", "レース名", "馬番", "馬名", "鉄板ランク", "判定", "印"]:
        if c in df.columns:
            df[c] = df[c].map(norm_text)

    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date)
    else:
        df["日付"] = ""

    if "鉄板ランク" not in df.columns:
        df["鉄板ランク"] = "鉄板⭐️"
    if "判定" not in df.columns:
        df["判定"] = "採用"
    if "印" not in df.columns:
        df["印"] = ""

    return df


def mark_priority(v):
    v = norm_text(v)
    order = {"◎": 1, "本命": 1, "○": 2, "◯": 2, "対抗": 2, "▲": 3, "単穴": 3, "△": 4, "連下": 4, "☆": 5, "注": 6, "他": 7}
    return order.get(v, 99)


def teppan_priority(rank):
    r = norm_text(rank)
    if r == "超鉄板⭐️":
        return 3
    if r == "強鉄板⭐️":
        return 2
    if r == "鉄板⭐️":
        return 1
    return 0


def flag_from_rank(rank):
    r = norm_text(rank)
    if r == "超鉄板⭐️":
        return "激"
    if r in ["強鉄板⭐️", "鉄板⭐️"]:
        return "熱"
    return ""


def flag_class(rank):
    r = norm_text(rank)
    if r == "超鉄板⭐️":
        return "flag-geki"
    if r in ["強鉄板⭐️", "鉄板⭐️"]:
        return "flag-netsu"
    return ""


def strongest_rank(ranks):
    ranks = [r for r in ranks if norm_text(r)]
    if not ranks:
        return ""
    return sorted(ranks, key=teppan_priority, reverse=True)[0]


def choose_main(s_race):
    g = s_race.copy()
    g["R_num"] = g["R"].map(to_int)
    g["馬番_num"] = g["馬番"].map(to_int)
    g["mark_pri"] = g["印"].map(mark_priority)
    g = g.sort_values(["mark_pri", "馬番_num"], ascending=[True, True])
    return g.iloc[0]


def find_teppan_rank(t_race, num):
    if t_race.empty:
        return ""
    num = norm_text(num)
    x = t_race[t_race["馬番"].map(norm_text) == num]
    if x.empty:
        return ""
    return strongest_rank(x["鉄板ランク"].tolist())


def make_venue_order(s, t):
    order = []
    for df in [s, t]:
        if df is None or df.empty or "競馬場" not in df.columns:
            continue
        for v in df["競馬場"].tolist():
            v = norm_text(v)
            if v and v not in order:
                order.append(v)
    return {v: i for i, v in enumerate(order)}


def build_cards(straight_df, teppan_df):
    s = normalize_straight(straight_df)
    t = normalize_teppan(teppan_df)

    if not s.empty:
        s["R_num"] = s["R"].map(to_int)
    if not t.empty:
        t["R_num"] = t["R"].map(to_int)
        t["馬番_num"] = t["馬番"].map(to_int)
        t["rank_pri"] = t["鉄板ランク"].map(teppan_priority)
        t["mark_pri"] = t["印"].map(mark_priority)
        t = (
            t.sort_values(["R_num", "mark_pri", "rank_pri", "馬番_num"], ascending=[True, True, False, True])
            .drop_duplicates(subset=["日付", "競馬場", "R", "馬番", "馬名"], keep="first")
        )

    venue_order = make_venue_order(s, t)

    keys = set()
    for df in [s, t]:
        if df.empty:
            continue
        for _, r in df.iterrows():
            keys.add((norm_text(r.get("日付", "")), norm_text(r.get("競馬場", "")), int(r.get("R_num", 999))))

    keys = sorted(keys, key=lambda x: (venue_order.get(x[1], 999), x[2], x[0]))

    cards = []
    for date, venue, rnum in keys:
        s_race = s[(s["日付"].map(norm_text) == date) & (s["競馬場"].map(norm_text) == venue) & (s["R_num"] == rnum)].copy() if not s.empty else pd.DataFrame()
        t_race = t[(t["日付"].map(norm_text) == date) & (t["競馬場"].map(norm_text) == venue) & (t["R_num"] == rnum)].copy() if not t.empty else pd.DataFrame()

        lines = []
        race_name = ""

        if not s_race.empty:
            main = choose_main(s_race)
            race_name = norm_text(main.get("レース名", ""))
            main_rank = find_teppan_rank(t_race, main.get("馬番", ""))
            lines.append({"mark": "◎", "num": norm_text(main.get("馬番", "")), "name": norm_text(main.get("馬名", "")), "flag": flag_from_rank(main_rank), "flag_class": flag_class(main_rank)})

            for mark, num_col, name_col in [("○", "対抗", "対抗馬名"), ("▲", "単穴", "単穴馬名"), ("△", "連下", "連下馬名")]:
                num = norm_text(main.get(num_col, ""))
                if num:
                    rank = find_teppan_rank(t_race, num)
                    lines.append({"mark": mark, "num": num, "name": norm_text(main.get(name_col, "")), "flag": flag_from_rank(rank), "flag_class": flag_class(rank)})

            others = []
            for c in ["他", "他1", "他2", "他3", "他4"]:
                v = norm_text(main.get(c, ""))
                if v:
                    others.append(v)
            if others:
                lines.append({"mark": "他", "num": "", "name": ", ".join(others), "flag": "", "flag_class": ""})
        else:
            if not t_race.empty:
                race_name = norm_text(t_race.iloc[0].get("レース名", ""))
            t_race = t_race.sort_values(["mark_pri", "rank_pri", "馬番_num"], ascending=[True, False, True])
            for _, r in t_race.iterrows():
                rank = norm_text(r.get("鉄板ランク", ""))
                lines.append({"mark": "", "num": norm_text(r.get("馬番", "")), "name": norm_text(r.get("馬名", "")), "flag": flag_from_rank(rank), "flag_class": flag_class(rank)})

        cards.append({"date": date, "venue": venue, "race_no": f"{rnum}R", "race_name": race_name, "lines": lines})

    return cards


def build_result_df(straight_df, teppan_df):
    s = normalize_straight(straight_df)
    t = normalize_teppan(teppan_df)
    rows = []
    for df, typ in [(s, "直線"), (t, "鉄板")]:
        if df.empty:
            continue
        for _, r in df.iterrows():
            rows.append({"種別": typ, "日付": r.get("日付", ""), "競馬場": r.get("競馬場", ""), "R": r.get("R", ""), "レース名": r.get("レース名", ""), "馬番": r.get("馬番", ""), "馬名": r.get("馬名", ""), "鉄板ランク": r.get("鉄板ランク", ""), "判定": r.get("判定", ""), "印": r.get("印", "")})
    return pd.DataFrame(rows)


def render_line(line):
    mark = esc(line.get("mark", ""))
    num = esc(line.get("num", ""))
    name = esc(line.get("name", ""))
    flag = esc(line.get("flag", ""))
    fcls = esc(line.get("flag_class", ""))
    return f"""
      <div class="pick-line">
        <span class="mark">{mark}</span>
        <span class="num">{num}</span>
        <span class="horse-name">{name}</span>
        <span class="flag {fcls}">{flag}</span>
      </div>
    """


def render_card(card, idx):
    venue = esc(card["venue"])
    race_no = esc(card["race_no"])
    race_name = esc(card.get("race_name", ""))
    serial = f"{venue[:1]}{re.sub(r'[^0-9]', '', race_no).zfill(2)}-20260513-{str(idx).zfill(3)}"
    lines_html = "\n".join(render_line(line) for line in card["lines"])
    return f"""
    <div class="ticket-card">
      <div class="ticket-head">
        <div class="race-title">{venue} {race_no}</div>
        <div class="race-name">{race_name}</div>
      </div>
      <div class="ticket-body">
        {lines_html}
      </div>
      <div class="ticket-footer">
        <div class="footer-label">TODAY’S PICKS</div>
        <div class="footer-divider"></div>
        <div class="barcode"></div>
        <div class="serial">{serial}</div>
      </div>
    </div>
    """


def render_html(cards, image_date):
    date = parse_date(image_date) if image_date else (cards[0]["date"] if cards else "")
    cards_html = "\n".join(render_card(card, i + 1) for i, card in enumerate(cards))
    return f"""
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
:root {{
  --bg:#031226;
  --gold:#e5bc4b;
  --gold2:#b9871e;
  --paper:#f6f0dd;
  --ink:#111111;
  --navy:#0b2c59;
  --red:#d8212d;
  --yellow:#c88d00;
  --line:#d5c7a0;
}}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--bg);font-family:"Noto Sans CJK JP","Noto Sans JP","Hiragino Sans","Yu Gothic",sans-serif;}}
.poster{{
  width:1080px;
  margin:0 auto;
  padding:34px 34px 36px;
  background:linear-gradient(180deg,#031226 0%,#020f20 100%);
  color:#fff;
  border:4px solid var(--gold2);
  outline:1px solid var(--gold2);
  outline-offset:-14px;
}}
.header{{height:170px;position:relative;}}
.title{{position:absolute;left:36px;top:5px;font-size:78px;line-height:1;color:var(--gold);font-weight:900;letter-spacing:.04em;}}
.subtitle{{position:absolute;left:235px;top:103px;color:var(--gold);font-weight:900;font-size:32px;letter-spacing:.12em;}}
.subtitle::before,.subtitle::after{{content:"";display:inline-block;width:150px;height:2px;background:var(--gold);vertical-align:middle;margin:0 16px;}}
.date{{position:absolute;right:32px;top:8px;color:var(--gold);font-size:34px;letter-spacing:.08em;}}
.legend{{position:absolute;right:22px;top:68px;font-size:22px;font-weight:800;line-height:1.45;}}
.legend .red{{color:var(--red);}}
.legend .yellow{{color:var(--yellow);}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:18px 22px;}}
.ticket-card{{background:var(--paper);border:2px solid var(--gold2);border-radius:16px;overflow:hidden;min-height:235px;box-shadow:0 0 0 2px rgba(255,255,255,.15) inset;}}
.ticket-head{{margin:8px 8px 0;height:68px;background:var(--navy);border:2px solid var(--gold2);border-radius:12px 12px 4px 4px;color:white;text-align:center;padding-top:10px;}}
.race-title{{font-size:34px;font-weight:900;line-height:1;letter-spacing:.06em;}}
.race-name{{margin-top:6px;font-size:14px;color:#f4efe0;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.ticket-body{{padding:14px 20px 6px;}}
.pick-line{{display:grid;grid-template-columns:34px 52px 1fr 34px;align-items:center;height:39px;border-bottom:1px solid var(--line);font-weight:800;color:var(--ink);font-size:22px;letter-spacing:.02em;}}
.pick-line:last-child{{border-bottom:none;}}
.mark{{font-size:24px;text-align:left;}}
.num{{font-size:23px;text-align:left;}}
.horse-name{{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}}
.flag{{font-weight:900;text-align:right;font-size:24px;}}
.flag-geki{{color:var(--red);}}
.flag-netsu{{color:var(--yellow);}}
.ticket-footer{{height:44px;display:grid;grid-template-columns:130px 14px 1fr;align-items:center;padding:0 18px;color:var(--ink);position:relative;}}
.footer-label{{font-size:15px;font-weight:900;}}
.footer-divider{{height:24px;width:1px;background:var(--gold2);}}
.barcode{{width:150px;height:22px;margin-left:20px;background:repeating-linear-gradient(90deg,#111 0,#111 3px,transparent 3px,transparent 6px,#111 6px,#111 8px,transparent 8px,transparent 13px);}}
.serial{{position:absolute;left:210px;bottom:2px;font-size:13px;letter-spacing:.04em;}}
</style>
</head>
<body>
<div class="poster" id="poster">
  <div class="header">
    <div class="title">本日の推奨馬</div>
    <div class="subtitle">TODAY’S PICKS</div>
    <div class="date">{esc(date)}</div>
    <div class="legend">
      <div><span class="red">激</span>=超鉄板　<span class="yellow">熱</span>=鉄板</div>
      <div>印=直線ロジック</div>
    </div>
  </div>
  <div class="cards">
    {cards_html}
  </div>
</div>
</body>
</html>
"""


st.title("複合推奨馬SNSアプリ HTML/CSS版")
st.caption("直線ロジックCSVと鉄板⭐️血統CSVを読み込み、参考画像に近い2列の馬券風テンプレートで表示します。")

with st.expander("必要CSV列", expanded=False):
    st.markdown("**直線ロジックCSV 推奨列**")
    st.code("日付,競馬場,R,レース名,馬番,馬名,信頼度,印,対抗,対抗馬名,単穴,単穴馬名,連下,連下馬名,他1,他2,相手表示", language="csv")
    st.markdown("**鉄板CSV 推奨列**")
    st.code("日付,競馬場,R,レース名,馬番,馬名,鉄板ランク,判定,印", language="csv")

col1, col2 = st.columns(2)
with col1:
    st.subheader("直線ロジックCSV")
    smode = st.radio("入力方法（直線）", ["貼り付け", "ファイル読み込み"], horizontal=True, key="s")
    straight_text = st.text_area("直線ロジックCSVを貼り付け", height=240) if smode == "貼り付け" else ""
    straight_file = st.file_uploader("直線ロジックCSVファイル", type=["csv"], key="sf") if smode == "ファイル読み込み" else None

with col2:
    st.subheader("鉄板⭐️血統CSV")
    tmode = st.radio("入力方法（鉄板）", ["貼り付け", "ファイル読み込み"], horizontal=True, key="t")
    teppan_text = st.text_area("鉄板CSVを貼り付け", height=240) if tmode == "貼り付け" else ""
    teppan_file = st.file_uploader("鉄板CSVファイル", type=["csv"], key="tf") if tmode == "ファイル読み込み" else None

image_date = st.text_input("画像に表示する日付", value=datetime.now().strftime("%Y.%m.%d"))

if st.button("複合画像を作成", type="primary", use_container_width=True):
    try:
        if smode == "貼り付け":
            if not straight_text.strip():
                st.warning("直線ロジックCSVを入力してください。")
                st.stop()
            straight_df = read_csv_smart(straight_text)
        else:
            if straight_file is None:
                st.warning("直線ロジックCSVファイルを選択してください。")
                st.stop()
            straight_df = read_csv_smart(straight_file)

        if tmode == "貼り付け":
            if not teppan_text.strip():
                st.warning("鉄板CSVを入力してください。")
                st.stop()
            teppan_df = read_csv_smart(teppan_text)
        else:
            if teppan_file is None:
                st.warning("鉄板CSVファイルを選択してください。")
                st.stop()
            teppan_df = read_csv_smart(teppan_file)

        cards = build_cards(straight_df, teppan_df)
        result_df = build_result_df(straight_df, teppan_df)

        if not cards:
            st.warning("表示対象がありませんでした。")
            st.stop()

        html = render_html(cards, image_date)
        st.success(f"表示レース {len(cards)}件を作成しました。")

        st.subheader("表示データ")
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        st.subheader("SNS画像プレビュー")
        components.html(html, height=1200, scrolling=True)

        st.download_button("HTMLをダウンロード", data=html.encode("utf-8"), file_name="composite_ticket_style.html", mime="text/html", use_container_width=True)
        st.info("PNG保存は、プレビューをスクショする運用が最も安定します。")

    except Exception as e:
        st.error("処理中にエラーが出ました。")
        st.exception(e)
