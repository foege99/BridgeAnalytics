"""
BridgeAnalytics – Web Dashboard
================================
Streamlit-baseret dashboard til visning af BridgeAnalytics Excel-rapporter.

Kør med:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path

# ── Sidekonfiguration ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="BridgeAnalytics Dashboard",
    page_icon="🃏",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Hjælpefunktioner ───────────────────────────────────────────────────────

def find_local_xlsx() -> list[Path]:
    """Find alle *ANALYSE*xlsx-filer i projektmappen (ekskl. ~$-låsefiler)."""
    root = Path(__file__).parent
    files = sorted(
        (f for f in root.glob("*ANALYSE*.xlsx") if not f.name.startswith("~$")),
        reverse=True,
    )
    return files


def load_excel(file) -> dict[str, pd.DataFrame]:
    """
    Indlæs alle ark fra en Excel-fil.
    Returnerer dict: {ark_navn: DataFrame}.
    """
    xl = pd.ExcelFile(file)
    sheets = {}
    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet)
            sheets[sheet] = df
        except Exception:
            pass
    return sheets


def pct_color(val: float) -> str:
    """CSS-farve baseret på procent-performance."""
    if pd.isna(val):
        return "color: gray"
    if val >= 55:
        return "color: #27ae60; font-weight: bold"
    if val <= 45:
        return "color: #e74c3c; font-weight: bold"
    return "color: #2c3e50"


def diff_color(val: float) -> str:
    """CSS-farve for afvigelse fra forventet."""
    if pd.isna(val):
        return "color: gray"
    if val > 5:
        return "color: #27ae60; font-weight: bold"
    if val < -5:
        return "color: #e74c3c; font-weight: bold"
    return "color: #2c3e50"


def fmt_pct(val) -> str:
    if pd.isna(val):
        return "–"
    return f"{val:.1f}%"


def fmt_diff(val) -> str:
    if pd.isna(val):
        return "–"
    return f"{val:+.1f}%"


# ── Sidebar – filvalg ──────────────────────────────────────────────────────

st.sidebar.title("🃏 BridgeAnalytics")
st.sidebar.markdown("---")

source = st.sidebar.radio(
    "Datakilde",
    ["Upload Excel-fil", "Brug lokal fil"],
    index=0,
)

sheets: dict[str, pd.DataFrame] = {}

if source == "Upload Excel-fil":
    uploaded = st.sidebar.file_uploader(
        "Vælg Excel-fil (.xlsx)",
        type=["xlsx"],
        help="Upload en Excel-fil genereret af BridgeAnalytics (main.py).",
    )
    if uploaded:
        with st.spinner("Indlæser data…"):
            sheets = load_excel(uploaded)
        st.sidebar.success(f"Indlæst: {uploaded.name}")
else:
    local_files = find_local_xlsx()
    if local_files:
        options = {f.name: f for f in local_files}
        choice = st.sidebar.selectbox("Vælg fil", list(options.keys()))
        if choice:
            with st.spinner("Indlæser data…"):
                sheets = load_excel(options[choice])
            st.sidebar.success(f"Indlæst: {choice}")
    else:
        st.sidebar.warning("Ingen lokale ANALYSE-filer fundet.")

st.sidebar.markdown("---")
st.sidebar.caption("BridgeAnalytics · Phase 2.1")

# ── Ingen data endnu ───────────────────────────────────────────────────────

if not sheets:
    st.title("🃏 BridgeAnalytics Dashboard")
    st.info(
        "**Kom i gang:** Upload eller vælg en BridgeAnalytics Excel-fil i sidepanelet til venstre."
    )
    with st.expander("Hvad er BridgeAnalytics?"):
        st.markdown(
            """
            BridgeAnalytics er et analyseværktøj til seriøse bridgepar.

            **Funktioner:**
            - 📊 Rollebaseret performance (Declarer, Forsvar, Udspiller)
            - 🃏 Board Review med forklaringer
            - 📈 Benchmarking mod anonymt felt
            - 🔒 Privacy-fokuseret – ingen andre parnavne vises

            **Workflow:**
            1. Kør `python main.py` for at hente og analysere data
            2. Upload den genererede Excel-fil her
            3. Udforsk dine resultater
            """
        )
    st.stop()

# ── Faner ──────────────────────────────────────────────────────────────────

tabs = st.tabs([
    "🏠 Overblik",
    "📊 Aftensanalyse",
    "🃏 Board Review",
    "📈 Feltanalyse",
    "⬇️ Declarer",
])


# ══════════════════════════════════════════════════════════════════════════
# TAB 1 – OVERBLIK
# ══════════════════════════════════════════════════════════════════════════

with tabs[0]:
    st.header("🏠 Overblik")

    # ── KPI'er fra Tournament_Summary ─────────────────────────────────────
    df_ts = sheets.get("Tournament_Summary", pd.DataFrame())
    df_br = sheets.get("Board_Review_Summary", pd.DataFrame())

    if not df_ts.empty:
        total_evenings = len(df_ts)
        total_boards = int(df_ts["boards"].sum()) if "boards" in df_ts.columns else 0

        avg_hf = df_ts["HF_total_pct"].mean() if "HF_total_pct" in df_ts.columns else np.nan
        avg_pf = df_ts["PF_total_pct"].mean() if "PF_total_pct" in df_ts.columns else np.nan

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Aftener analyseret", total_evenings)
        col2.metric("Boards i alt", total_boards)
        col3.metric(
            "Henrik – gns. %",
            fmt_pct(avg_hf),
            delta=fmt_diff(avg_hf - 50) if not pd.isna(avg_hf) else None,
        )
        col4.metric(
            "Per – gns. %",
            fmt_pct(avg_pf),
            delta=fmt_diff(avg_pf - 50) if not pd.isna(avg_pf) else None,
        )
        st.divider()

    # ── Board-type fordeling ───────────────────────────────────────────────
    if not df_br.empty and "Board_Type" in df_br.columns:
        st.subheader("Board-type fordeling")
        bt_counts = df_br["Board_Type"].value_counts()
        col_left, col_right = st.columns([2, 3])
        with col_left:
            st.dataframe(
                bt_counts.rename("Antal boards").reset_index().rename(columns={"index": "Board Type"}),
                use_container_width=True,
                hide_index=True,
            )
        with col_right:
            st.bar_chart(bt_counts)
        st.divider()

    # ── Turneringsoversigt ─────────────────────────────────────────────────
    if not df_ts.empty:
        st.subheader("Turneringsoversigt")

        display_ts = df_ts.copy()
        for col in ["HF_total_pct", "PF_total_pct", "HF_declarer_pct", "PF_declarer_pct",
                    "HF_defense_pct", "PF_defense_pct"]:
            if col in display_ts.columns:
                display_ts[col] = display_ts[col].apply(fmt_pct)

        st.dataframe(display_ts, use_container_width=True, hide_index=True)

    if df_ts.empty and df_br.empty:
        st.warning("Tournament_Summary og Board_Review_Summary mangler i denne fil.")


# ══════════════════════════════════════════════════════════════════════════
# TAB 2 – AFTENSANALYSE
# ══════════════════════════════════════════════════════════════════════════

with tabs[1]:
    st.header("📊 Aftensanalyse")

    df_ts = sheets.get("Tournament_Summary", pd.DataFrame())
    df_rs = sheets.get("Role_Summary", pd.DataFrame())
    df_em = sheets.get("Evening_Matrix", pd.DataFrame())
    df_qs = sheets.get("Quarterly_Summary", pd.DataFrame())

    # ── Tournament Summary ─────────────────────────────────────────────────
    if not df_ts.empty:
        st.subheader("Samlet performance pr. aften")

        # Linjegraf over total-%
        chart_cols = {}
        if "HF_total_pct" in df_ts.columns:
            chart_cols["Henrik total %"] = df_ts.set_index("tournament_date")["HF_total_pct"]
        if "PF_total_pct" in df_ts.columns:
            chart_cols["Per total %"] = df_ts.set_index("tournament_date")["PF_total_pct"]

        if chart_cols:
            chart_df = pd.DataFrame(chart_cols)
            # Tilføj 50%-linje
            chart_df["Middel (50%)"] = 50.0
            st.line_chart(chart_df, use_container_width=True)

        st.dataframe(df_ts, use_container_width=True, hide_index=True)
        st.divider()

    # ── Role Summary ───────────────────────────────────────────────────────
    if not df_rs.empty:
        st.subheader("Performance pr. rolle")

        col_h, col_p = st.columns(2)

        for col, player in [(col_h, "Henrik Friis"), (col_p, "Per Føge Jensen")]:
            with col:
                st.markdown(f"**{player}**")
                sub = df_rs[df_rs["Player"] == player].copy() if "Player" in df_rs.columns else df_rs
                if "Avg_pct" in sub.columns:
                    sub = sub.copy()
                    sub["Avg_pct"] = sub["Avg_pct"].apply(fmt_pct)
                st.dataframe(sub, use_container_width=True, hide_index=True)
        st.divider()

    # ── Evening Matrix ─────────────────────────────────────────────────────
    if not df_em.empty:
        st.subheader("Rollematrix pr. aften")
        st.dataframe(df_em, use_container_width=True, hide_index=True)
        st.divider()

    # ── Quarterly Summary ──────────────────────────────────────────────────
    if not df_qs.empty:
        st.subheader("Kvartalsoversigt med konfidensintervaller (95%)")
        st.caption(
            "CI95: Konfidensinterval baseret på 1,96 × standardfejl. "
            "Brede intervaller indikerer lille datasæt."
        )

        # Vis pr. rolle
        if "Role" in df_qs.columns:
            roles = df_qs["Role"].unique().tolist()
            selected_role = st.selectbox("Filtrer rolle", ["Alle"] + roles)
            if selected_role != "Alle":
                df_qs_display = df_qs[df_qs["Role"] == selected_role]
            else:
                df_qs_display = df_qs
        else:
            df_qs_display = df_qs

        st.dataframe(df_qs_display, use_container_width=True, hide_index=True)

    if df_ts.empty and df_rs.empty:
        st.warning("Ingen aftensdata fundet i denne fil.")


# ══════════════════════════════════════════════════════════════════════════
# TAB 3 – BOARD REVIEW
# ══════════════════════════════════════════════════════════════════════════

with tabs[2]:
    st.header("🃏 Board Review")

    df_bra = sheets.get("Board_Review_All", pd.DataFrame())
    df_brs = sheets.get("Board_Review_Summary", pd.DataFrame())

    # ── Filtre ────────────────────────────────────────────────────────────
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    board_type_options = ["Alle"]
    if not df_brs.empty and "Board_Type" in df_brs.columns:
        board_type_options += sorted(df_brs["Board_Type"].dropna().unique().tolist())

    with filter_col1:
        bt_filter = st.selectbox("Board Type", board_type_options, key="br_bt")

    with filter_col2:
        min_diff = st.slider(
            "Min. afvigelse fra forventet (%)",
            min_value=0,
            max_value=30,
            value=0,
            step=1,
            key="br_diff",
        )

    with filter_col3:
        show_competitive = st.checkbox("Kun competitive boards", value=False, key="br_comp")

    # ── Board Review Summary ───────────────────────────────────────────────
    if not df_brs.empty:
        st.subheader("Board-oversigt (ét board pr. række)")

        df_display = df_brs.copy()

        if bt_filter != "Alle" and "Board_Type" in df_display.columns:
            df_display = df_display[df_display["Board_Type"] == bt_filter]

        if "avg_pct_vs_expected_abs" in df_display.columns:
            df_display = df_display[df_display["avg_pct_vs_expected_abs"] >= min_diff]

        if show_competitive and "competitive_flag" in df_display.columns:
            df_display = df_display[df_display["competitive_flag"].astype(bool)]

        # Formater procent-kolonner
        for c in ["expected_pct", "avg_pct_NS"]:
            if c in df_display.columns:
                df_display[c] = df_display[c].apply(fmt_pct)
        for c in ["avg_pct_vs_expected", "avg_pct_vs_expected_abs"]:
            if c in df_display.columns:
                df_display[c] = df_display[c].apply(fmt_diff)

        # Prioriterede kolonner
        priority_cols = [
            "tournament_date", "board_no", "row", "num_hands",
            "contract_actual", "decl", "level", "strain",
            "expected_pct", "avg_pct_NS", "avg_pct_vs_expected",
            "Board_Type", "competitive_flag",
            "field_mode_contract", "field_mode_freq",
            "avg_NS_HCP", "avg_ØV_HCP",
        ]
        visible_cols = [c for c in priority_cols if c in df_display.columns]
        extra_cols = [c for c in df_display.columns if c not in visible_cols]

        st.dataframe(
            df_display[visible_cols + extra_cols],
            use_container_width=True,
            hide_index=True,
        )

        st.caption(f"Viser {len(df_display)} boards")
        st.divider()

    # ── Board Review All Hands ─────────────────────────────────────────────
    if not df_bra.empty:
        with st.expander("📋 Alle hænder (detaljeret)", expanded=False):
            df_all_display = df_bra.copy()

            if bt_filter != "Alle" and "Board_Type" in df_all_display.columns:
                df_all_display = df_all_display[df_all_display["Board_Type"] == bt_filter]

            if "pct_vs_expected_abs" in df_all_display.columns:
                df_all_display = df_all_display[
                    df_all_display["pct_vs_expected_abs"] >= min_diff
                ]

            if show_competitive and "competitive_flag" in df_all_display.columns:
                df_all_display = df_all_display[df_all_display["competitive_flag"].astype(bool)]

            # Prioriterede kolonner
            hand_priority_cols = [
                "tournament_date", "board_no", "row", "contract",
                "expected_pct", "pct_NS", "pct_vs_expected",
                "Board_Type", "competitive_flag",
                "field_mode_contract", "decl", "level", "strain",
                "NS_HCP", "ØV_HCP", "NS_LTC_adj", "ØV_LTC_adj",
            ]
            vis_cols = [c for c in hand_priority_cols if c in df_all_display.columns]
            ext_cols = [c for c in df_all_display.columns if c not in vis_cols]

            for c in ["expected_pct", "pct_NS"]:
                if c in df_all_display.columns:
                    df_all_display[c] = df_all_display[c].apply(fmt_pct)
            if "pct_vs_expected" in df_all_display.columns:
                df_all_display["pct_vs_expected"] = df_all_display["pct_vs_expected"].apply(
                    fmt_diff
                )

            st.dataframe(
                df_all_display[vis_cols + ext_cols],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Viser {len(df_all_display)} hænder")

    if df_bra.empty and df_brs.empty:
        st.warning("Ingen Board Review-data fundet i denne fil.")


# ══════════════════════════════════════════════════════════════════════════
# TAB 4 – FELTANALYSE
# ══════════════════════════════════════════════════════════════════════════

with tabs[3]:
    st.header("📈 Feltanalyse")
    st.caption(
        "Anonymt felt – alle par i turneringen. "
        "Minimum 50 boards for at indgå i analysen."
    )

    df_fd = sheets.get("Field_Defense", pd.DataFrame())
    df_fdecl = sheets.get("Field_Declarer", pd.DataFrame())

    col_def, col_decl = st.columns(2)

    with col_def:
        st.subheader("Forsvar")
        if not df_fd.empty:
            # Formater pct-kolonne
            pct_col = next((c for c in df_fd.columns if "pct" in c.lower()), None)
            df_fd_display = df_fd.copy()
            if pct_col:
                df_fd_display[pct_col] = df_fd_display[pct_col].apply(fmt_pct)
            st.dataframe(df_fd_display, use_container_width=True, hide_index=True)

            # Histogram
            raw_col = next((c for c in df_fd.columns if "pct" in c.lower()), None)
            if raw_col and raw_col in df_fd.columns:
                hist_data = df_fd[raw_col].dropna()
                if not hist_data.empty:
                    st.bar_chart(
                        hist_data.value_counts(bins=10, sort=False).sort_index(),
                        use_container_width=True,
                    )
        else:
            st.info("Ingen forsvarsdata i denne fil.")

    with col_decl:
        st.subheader("Declarer")
        if not df_fdecl.empty:
            pct_col = next((c for c in df_fdecl.columns if "pct" in c.lower()), None)
            df_fdecl_display = df_fdecl.copy()
            if pct_col:
                df_fdecl_display[pct_col] = df_fdecl_display[pct_col].apply(fmt_pct)
            st.dataframe(df_fdecl_display, use_container_width=True, hide_index=True)

            raw_col = next((c for c in df_fdecl.columns if "pct" in c.lower()), None)
            if raw_col and raw_col in df_fdecl.columns:
                hist_data = df_fdecl[raw_col].dropna()
                if not hist_data.empty:
                    st.bar_chart(
                        hist_data.value_counts(bins=10, sort=False).sort_index(),
                        use_container_width=True,
                    )
        else:
            st.info("Ingen declarerdata i denne fil.")

    if df_fd.empty and df_fdecl.empty:
        st.warning("Ingen feltdata fundet i denne fil.")


# ══════════════════════════════════════════════════════════════════════════
# TAB 5 – DECLARER
# ══════════════════════════════════════════════════════════════════════════

with tabs[4]:
    st.header("⬇️ Declarer-analyse")

    df_da = sheets.get("Declarer_Analysis", pd.DataFrame())
    df_dl = sheets.get("Declarer_List", pd.DataFrame())

    # ── Declarer Analysis ─────────────────────────────────────────────────
    if not df_da.empty:
        st.subheader("Declarer Analysis (board-niveau)")

        # Kolonne-filter
        if "Player" in df_da.columns:
            players = ["Alle"] + df_da["Player"].dropna().unique().tolist()
            player_filter = st.selectbox("Filtrer spiller", players, key="da_player")
            if player_filter != "Alle":
                df_da = df_da[df_da["Player"] == player_filter]

        st.dataframe(df_da, use_container_width=True, hide_index=True)
        st.caption(f"Viser {len(df_da)} boards")
        st.divider()

    # ── Declarer List ──────────────────────────────────────────────────────
    if not df_dl.empty:
        st.subheader("Declarer-liste (alle kontrakter)")

        if "Player" in df_dl.columns:
            players = ["Alle"] + df_dl["Player"].dropna().unique().tolist()
            player_filter_dl = st.selectbox("Filtrer spiller", players, key="dl_player")
            if player_filter_dl != "Alle":
                df_dl = df_dl[df_dl["Player"] == player_filter_dl]

        # Sorter efter dato
        if "tournament_date" in df_dl.columns:
            df_dl = df_dl.sort_values("tournament_date", ascending=False)

        st.dataframe(df_dl, use_container_width=True, hide_index=True)
        st.caption(f"Viser {len(df_dl)} kontrakter")

    if df_da.empty and df_dl.empty:
        st.info(
            "Ingen declarer-data i denne fil. "
            "Det kan skyldes at parret ikke har spillet sammen i A-rækken i den valgte periode."
        )
