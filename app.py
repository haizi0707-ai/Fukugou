import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="消寄アプリ", layout="wide")
APP_VERSION = "keshiyose_only_v1_2026-05-15"
APP_DIR = Path(__file__).resolve().parent

HEADERLESS_TARGET_COLUMNS = [
    "日付", "場所", "場R", "レース名", "芝ダ", "距離", "馬番", "馬名",
    "種牡馬", "父タイプ名", "母父名", "母父タイプ名",
    "性別", "年齢", "斤量", "頭数",
    "前走馬場状態", "前芝ダ", "前距離", "前走斤量",
    "休み明け〜戦目", "所属", "調教師", "騎手", "前走騎手",
    "前走着順", "前走着差", "前走頭数",
    "前走通過順1", "前走通過順2", "前走通過順3", "前走通過順4",
    "前走上り3F順", "前走脚質", "前走場所", "前走場所区分",
]

DISPLAY_COLS = [
    "日付", "競馬場", "R", "レース名", "芝ダ", "距離", "馬番", "馬名",
    "消寄判定", "消寄ランク", "消寄該当数", "消寄理由",
    "過去該当頭数", "過去複勝圏内数", "過去複勝率", "リフト", "該当率",
    "芝ダ替わり", "距離変化帯", "前走着差帯", "前走着順帯", "前走上り順帯",
    "前走4角位置", "前走脚質帯", "頭数変化", "今回頭数帯", "休み明け区分",
]


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
    s = s.replace("Ｒ", "R")
    s = s.replace("芝・ダ", "芝ダ")
    s = s.replace("芝ダ・距離", "芝ダ距離")
    s = s.replace("～", "〜")
    return re.sub(r"\s+", "", s)


def to_int(x):
    try:
        if x is None or pd.isna(x):
            return None
        m = re.search(r"-?\d+", str(x))
        return int(m.group(0)) if m else None
    except Exception:
        return None


def to_float(x):
    try:
        if x is None or pd.isna(x):
            return None
        s = str(x).strip()
        if "勝" in s or "同" in s:
            return 0.0
        s = s.replace("秒", "").replace("+", "")
        s = s.replace("▲", "").replace("△", "").replace("◇", "")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else None
    except Exception:
        return None


def parse_date(v):
    s = norm_text(v)
    if not s:
        return ""
    if re.fullmatch(r"\d{4}", s):
        return f"2026.{s[:2]}.{s[2:4]}"
    if re.fullmatch(r"\d{6}", s):
        return f"20{s[:2]}.{s[2:4]}.{s[4:6]}"
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}.{s[4:6]}.{s[6:8]}"
    s = s.replace("/", ".").replace("-", ".")
    parts = s.split(".")
    if len(parts) == 3:
        return f"{parts[0]}.{parts[1].zfill(2)}.{parts[2].zfill(2)}"
    return s


def looks_like_headerless_target(df):
    cols = [str(c).strip() for c in df.columns]
    if len(cols) < 8:
        return False
    date_like = bool(re.fullmatch(r"\d{3,8}", cols[0]))
    place_like = cols[1] in [
        "札", "函", "福", "新", "東", "中", "名", "京", "阪", "小",
        "札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉",
    ]
    r_like = bool(re.search(r"\d+", cols[2]))
    return date_like and place_like and r_like


def read_csv_smart(obj):
    encodings = ["cp932", "shift_jis", "utf-8-sig", "utf-8"]
    last_err = None
    for enc in encodings:
        try:
            if hasattr(obj, "seek"):
                obj.seek(0)
                df = pd.read_csv(obj, encoding=enc)
                if looks_like_headerless_target(df):
                    obj.seek(0)
                    raw = pd.read_csv(obj, encoding=enc, header=None)
                    raw = raw.iloc[:, :len(HEADERLESS_TARGET_COLUMNS)]
                    raw.columns = HEADERLESS_TARGET_COLUMNS[:len(raw.columns)]
                    return raw, enc, "ヘッダーなしCSV"
                return df, enc, "ヘッダーありCSV"
            else:
                df = pd.read_csv(obj, encoding=enc)
                if looks_like_headerless_target(df):
                    raw = pd.read_csv(obj, encoding=enc, header=None)
                    raw = raw.iloc[:, :len(HEADERLESS_TARGET_COLUMNS)]
                    raw.columns = HEADERLESS_TARGET_COLUMNS[:len(raw.columns)]
                    return raw, enc, "ヘッダーなしCSV"
                return df, enc, "ヘッダーありCSV"
        except Exception as e:
            last_err = e
    raise last_err


def normalize_target(df):
    df = df.copy()
    df.columns = [norm_col(c) for c in df.columns]

    rename_map = {
        "場所": "競馬場", "場": "競馬場", "場R": "R", "レース": "R", "レース番号": "R",
        "馬番号": "馬番", "芝ダ距離": "距離", "レース名(クラス)": "レース名",
        "前馬場状態": "前走馬場状態", "前走馬場": "前走馬場状態",
        "前距離": "前走距離", "前芝ダ": "前走芝ダ", "前芝・ダ": "前走芝ダ",
        "前走着": "前走着順", "前着順": "前走着順", "前差": "前走着差",
        "前走上がり3F順": "前走上り3F順", "前走上り順位": "前走上り3F順",
        "前走上がり順位": "前走上り3F順", "前走4角": "前走通過順4", "前4角": "前走通過順4",
        "前走3角": "前走通過順3", "前3角": "前走通過順3", "前頭数": "前走頭数",
    }
    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    place_map = {
        "札": "札幌", "函": "函館", "福": "福島", "新": "新潟", "東": "東京",
        "中": "中山", "名": "中京", "京": "京都", "阪": "阪神", "小": "小倉",
    }

    if "競馬場" in df.columns:
        df["競馬場"] = df["競馬場"].apply(lambda x: place_map.get(norm_text(x), norm_text(x)))
    else:
        df["競馬場"] = ""

    if "R" in df.columns:
        df["R"] = df["R"].apply(to_int)
    else:
        df["R"] = None

    # 今回の芝ダ・距離
    if "距離" in df.columns:
        raw = df["距離"].astype(str)
        if "芝ダ" not in df.columns:
            df["芝ダ"] = raw.str.extract(r"([芝ダ])", expand=False).fillna("")
        else:
            miss = df["芝ダ"].map(norm_text).eq("")
            ext = raw.str.extract(r"([芝ダ])", expand=False).fillna("")
            df.loc[miss, "芝ダ"] = ext[miss]
        df["距離"] = raw.str.extract(r"(\d+)", expand=False).apply(to_int)
    else:
        df["距離"] = None
        if "芝ダ" not in df.columns:
            df["芝ダ"] = ""

    # 前走の芝ダ・距離
    if "前走距離" in df.columns:
        raw = df["前走距離"].astype(str)
        if "前走芝ダ" not in df.columns:
            df["前走芝ダ"] = raw.str.extract(r"([芝ダ])", expand=False).fillna("")
        else:
            miss = df["前走芝ダ"].map(norm_text).eq("")
            ext = raw.str.extract(r"([芝ダ])", expand=False).fillna("")
            df.loc[miss, "前走芝ダ"] = ext[miss]
        df["前走距離"] = raw.str.extract(r"(\d+)", expand=False).apply(to_int)
    else:
        df["前走距離"] = None
        if "前走芝ダ" not in df.columns:
            df["前走芝ダ"] = ""

    if "日付" in df.columns:
        df["日付"] = df["日付"].map(parse_date)
    else:
        df["日付"] = ""

    for c in [
        "競馬場", "レース名", "芝ダ", "馬名", "前走芝ダ", "前走脚質",
        "前走場所", "休み明け〜戦目"
    ]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].map(norm_text)

    for c in [
        "距離", "R", "馬番", "頭数", "前走距離", "前走頭数", "前走着順", "前走着差",
        "前走通過順3", "前走通過順4", "前走上り3F順"
    ]:
        if c not in df.columns:
            df[c] = ""

    return df


def get_corner_category(pos, field_size):
    pos = to_int(pos)
    field_size = to_int(field_size)
    if pos is None:
        return ""
    if pos == 1:
        return "1番手"
    if field_size is None or field_size <= 0:
        if pos <= 3:
            return "2〜3番手"
        elif pos <= 6:
            return "4〜6番手"
        elif pos <= 10:
            return "7〜10番手"
        return "11番手以下"
    ratio = pos / field_size
    if pos <= 3 or ratio <= 0.20:
        return "2〜3番手"
    elif pos <= 6 or ratio <= 0.40:
        return "4〜6番手"
    elif pos <= 10 or ratio <= 0.70:
        return "7〜10番手"
    return "11番手以下"


def holiday_run_category(x):
    n = to_int(x)
    if n is None:
        s = norm_text(x)
        return s
    return f"休み明け{n}戦目"


def build_feature_map(row):
    cur_surface = norm_text(row.get("芝ダ", ""))
    prev_surface = norm_text(row.get("前走芝ダ", ""))
    cur_dist = to_int(row.get("距離"))
    prev_dist = to_int(row.get("前走距離"))
    cur_field = to_int(row.get("頭数"))
    prev_field = to_int(row.get("前走頭数"))
    margin = to_float(row.get("前走着差"))
    rank = to_int(row.get("前走着順"))
    ag = to_int(row.get("前走上り3F順"))
    c4cat = get_corner_category(row.get("前走通過順4"), row.get("前走頭数"))
    style = norm_text(row.get("前走脚質", ""))
    rest = holiday_run_category(row.get("休み明け〜戦目", ""))

    if prev_surface and cur_surface:
        surface_change = f"{prev_surface}→{cur_surface}" if prev_surface != cur_surface else "同芝ダ"
    else:
        surface_change = ""

    if cur_dist is not None and prev_dist is not None:
        diff = cur_dist - prev_dist
        ad = abs(diff)
        if diff == 0:
            dist_band = "同距離"
        elif diff < 0 and ad <= 200:
            dist_band = "短縮100-200m"
        elif diff > 0 and ad <= 200:
            dist_band = "延長100-200m"
        elif diff < 0 and ad <= 400:
            dist_band = "短縮300-400m"
        elif diff > 0 and ad <= 400:
            dist_band = "延長300-400m"
        elif diff < 0:
            dist_band = "短縮500m以上"
        else:
            dist_band = "延長500m以上"
    else:
        dist_band = ""

    if margin is None:
        margin_band = ""
    elif margin >= 2.0:
        margin_band = "2.0秒以上負け"
    elif margin >= 1.0:
        margin_band = "1.0秒以上負け"
    elif margin >= 0.6:
        margin_band = "0.6-0.9秒負け"
    elif margin >= 0.4:
        margin_band = "0.4-0.5秒負け"
    elif margin >= 0.1:
        margin_band = "0.1-0.3秒負け"
    else:
        margin_band = "勝ち/同タイム"

    if rank is None:
        rank_band = ""
    elif rank == 1:
        rank_band = "1着"
    elif rank <= 3:
        rank_band = "2-3着"
    elif rank <= 5:
        rank_band = "4-5着"
    elif rank <= 9:
        rank_band = "6-9着"
    else:
        rank_band = "10着以下"

    if ag is None:
        ag_band = ""
    elif ag == 1:
        ag_band = "1位"
    elif ag <= 3:
        ag_band = "2-3位"
    elif ag <= 5:
        ag_band = "4-5位"
    elif ag <= 9:
        ag_band = "6-9位"
    else:
        ag_band = "10位以下"

    if cur_field is None:
        cur_field_band = ""
    elif cur_field >= 16:
        cur_field_band = "16頭以上"
    elif cur_field >= 14:
        cur_field_band = "14-15頭"
    elif cur_field >= 10:
        cur_field_band = "10-13頭"
    else:
        cur_field_band = "9頭以下"

    if prev_field is None or cur_field is None:
        field_change = ""
    else:
        diff = prev_field - cur_field
        if diff >= 4:
            field_change = "今回かなり頭数減"
        elif diff >= 1:
            field_change = "今回頭数減"
        elif diff == 0:
            field_change = "同頭数"
        elif diff >= -3:
            field_change = "今回頭数増"
        else:
            field_change = "今回かなり頭数増"

    if "逃" in style:
        style_band = "逃げ"
    elif "先" in style or "好位" in style:
        style_band = "先行/好位"
    elif "差" in style:
        style_band = "差し"
    elif "追" in style:
        style_band = "追込"
    else:
        style_band = ""

    return {
        "芝ダ替わり": surface_change,
        "距離変化帯": dist_band,
        "前走着差帯": margin_band,
        "前走着順帯": rank_band,
        "前走上り順帯": ag_band,
        "前走4角位置": c4cat,
        "前走脚質帯": style_band,
        "頭数変化": field_change,
        "今回頭数帯": cur_field_band,
        "休み明け区分": rest,
    }


def load_keshiyose_dictionary():
    files = sorted(APP_DIR.glob("*.csv"))
    candidates = [f for f in files if "消寄" in f.name and "コース別上位20" in f.name]
    if not candidates:
        candidates = [f for f in files if "消寄" in f.name]
    if not candidates:
        return pd.DataFrame(), None

    path = candidates[0]
    for enc in ["utf-8-sig", "cp932", "shift_jis", "utf-8"]:
        try:
            df = pd.read_csv(path, encoding=enc)
            df.columns = [norm_col(c) for c in df.columns]
            return df, path
        except Exception:
            continue
    return pd.DataFrame(), path


def build_keshiyose_results(target_df, selected_ranks):
    inp = normalize_target(target_df)
    inp = inp[inp["R"].isin([7, 8, 9, 10, 11, 12])].copy()
    dict_df, dict_path = load_keshiyose_dictionary()
    if inp.empty or dict_df.empty:
        return pd.DataFrame(), dict_path

    kd = dict_df.copy()
    needed = ["競馬場", "芝ダ", "距離", "消寄項目1", "消寄条件1", "消寄項目2", "消寄条件2", "消寄項目3", "消寄条件3", "消寄ランク", "消寄理由"]
    for c in needed:
        if c not in kd.columns:
            kd[c] = ""
        if c != "距離":
            kd[c] = kd[c].map(norm_text)
    kd["距離"] = kd["距離"].map(to_int)
    if selected_ranks:
        kd = kd[kd["消寄ランク"].isin(selected_ranks)].copy()

    rows = []
    for _, horse in inp.iterrows():
        rules = kd[(kd["競馬場"] == norm_text(horse["競馬場"])) & (kd["芝ダ"] == norm_text(horse["芝ダ"])) & (kd["距離"] == to_int(horse["距離"]))]
        if rules.empty:
            continue
        fmap = build_feature_map(horse)
        hit_reasons, hit_ranks = [], []
        for _, r in rules.iterrows():
            ok = True
            for i in [1, 2, 3]:
                item = norm_text(r.get(f"消寄項目{i}", ""))
                cond = norm_text(r.get(f"消寄条件{i}", ""))
                if not item or not cond:
                    continue
                if fmap.get(item, "") != cond:
                    ok = False
                    break
            if ok:
                hit_reasons.append(norm_text(r.get("消寄理由", "")) or f"{r.get('消寄項目1')}={r.get('消寄条件1')}")
                hit_ranks.append(norm_text(r.get("消寄ランク", "")))
        if hit_reasons:
            a_count = sum(1 for x in hit_ranks if x == "消寄A")
            label = "強消寄" if len(hit_reasons) >= 2 or a_count >= 1 else "消寄"
            rows.append({
                "日付": horse["日付"],
                "競馬場": horse["競馬場"],
                "R": int(horse["R"]),
                "レース名": horse["レース名"],
                "芝ダ": horse["芝ダ"],
                "距離": horse["距離"],
                "馬番": int(horse["馬番"]) if pd.notna(horse["馬番"]) else "",
                "馬名": horse["馬名"],
                "消寄判定": label,
                "消寄ランク": "・".join(sorted(set([x for x in hit_ranks if x]))),
                "消寄該当数": len(hit_reasons),
                "消寄理由": " / ".join(hit_reasons[:3]),
                **fmap,
            })
    return pd.DataFrame(rows), dict_path


# UI
st.title("消寄アプリ")
st.caption(f"バージョン: {APP_VERSION}")
st.write("TARGET/JRA-VAN CSVを読み込み、7〜12Rの消寄該当馬だけを抽出します。")
with st.expander("app.pyと同じ場所に置く辞書CSV", expanded=True):
    st.code("消寄_コース別上位20.csv")
    st.write("※ ファイル名に『消寄』と『コース別上位20』が入っていれば自動検出します。")

uploaded = st.file_uploader("TARGET/JRA-VAN由来CSVを選択", type=["csv"])
selected_ranks = st.multiselect("使用する消寄ランク", ["消寄A", "消寄B", "消寄C"], default=["消寄A", "消寄B"])

if uploaded is not None:
    try:
        raw_df, encoding, read_mode = read_csv_smart(uploaded)
        result_df, dict_path = build_keshiyose_results(raw_df, selected_ranks)
        target_df = normalize_target(raw_df)
        target_7_12 = target_df[target_df["R"].isin([7, 8, 9, 10, 11, 12])].copy()

        st.success("消寄判定を行いました。")
        c1, c2, c3 = st.columns(3)
        c1.metric("読み込み方式", read_mode)
        c2.metric("文字コード", encoding)
        c3.metric("7〜12R頭数", len(target_7_12))
        c4, c5, c6 = st.columns(3)
        c4.metric("消寄該当頭数", len(result_df))
        c5.metric("対象R数", target_7_12["R"].nunique() if not target_7_12.empty else 0)
        c6.metric("対象競馬場数", target_7_12["競馬場"].nunique() if not target_7_12.empty else 0)

        if dict_path:
            st.info(f"使用辞書: {dict_path.name}")
        else:
            st.warning("消寄辞書CSVが見つかりません。app.pyと同じ場所に 消寄_コース別上位20.csv を置いてください。")

        st.subheader("消寄判定結果")
        if result_df.empty:
            st.warning("消寄に該当する馬はいませんでした。")
        else:
            show_cols = [c for c in DISPLAY_COLS if c in result_df.columns]
            st.dataframe(result_df[show_cols], use_container_width=True, hide_index=True, height=420)
            st.download_button("消寄判定CSVをダウンロード", result_df.to_csv(index=False, encoding="utf-8-sig"), file_name="keshiyose_result.csv", mime="text/csv", use_container_width=True)

        with st.expander("確認用：7〜12Rデータ", expanded=False):
            preview_cols = ["日付", "競馬場", "R", "レース名", "芝ダ", "距離", "馬番", "馬名", "前走芝ダ", "前走距離", "前走着順", "前走着差", "前走上り3F順", "前走脚質"]
            preview_cols = [c for c in preview_cols if c in target_7_12.columns]
            st.dataframe(target_7_12[preview_cols].head(80), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error("処理中にエラーが出ました。")
        st.exception(e)
else:
    st.info("CSVファイルを選択してください。")
