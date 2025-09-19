# ================== APP SEGURO: nunca fica tela preta ==================
import io
import re
import sys
import traceback
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any

import pandas as pd
import streamlit as st

# ================== CONFIGURAÇÃO DA PÁGINA ==================
st.set_page_config(page_title="Validador de RELATÓRIOS (Excel)", layout="wide", initial_sidebar_state="expanded")

# ================== HELPER DE RECURSOS (DEV + EXE) ==================
def resource_path(rel_path: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return (base / rel_path).resolve()

# ================== LOGO (header) ==================
# Mantemos a logo de topo como fallback; o controle de tema/arquivo acontece na barra lateral.
logo_file_top = resource_path("assets/logo-white.png")
try:
    with open(logo_file_top, "rb") as f:
        st.image(f.read(), width=220)
except Exception as e:
    st.warning(f"Logo não carregado ({logo_file_top}): {e}")

# ================== TÍTULO ==================
st.title("🔎 Validador de RELATÓRIOS (Excel)")
st.caption("Detecta tabelas mesmo com legendas/imagens antes, permite escolher a coluna de chave, normaliza e compara divergências entre arquivos (Excel/CSV).")
with st.expander("❓ O que é esta etapa?", expanded=False):
    st.markdown(
        """
        **Objetivo:** carregar um arquivo Excel/CSV e inspecionar rapidamente a estrutura das bases,
        detectar **misturas de tipo**, configurar **chave/ID** e gerar comparações A vs B.

        **Exemplo prático:** identificar colunas com números como texto, datas inválidas e divergências entre duas extrações.
        """
    )

# ================== ESTILO DE CARDS (azul claro) ==================
st.markdown(
    """
    <style>
    .card {background:#e9f3ff;border:1px solid #cfe5ff;border-radius:12px;padding:10px 12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
    .card .label{font-size:12px;color:#0b5ed7;text-transform:uppercase;letter-spacing:.04em}
    .card .value{font-size:22px;font-weight:700;color:#0a3d91;margin-top:2px}
    .card .sub{font-size:12px;color:#3b5b9a}
    </style>
    """,
    unsafe_allow_html=True,
)
# Ajuste de quebra de linha dos rótulos dos cards (evita overflow)
st.markdown(
    """
    <style>
    .card .label{white-space:normal;word-break:break-word;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
    </style>
    """,
    unsafe_allow_html=True,
)

# Contador robusto de vazios (NaN, None, "", NBSP e tokens comuns)
def count_missing(series: pd.Series) -> int:
    s = series
    is_na = s.isna()
    s_str = s.astype(str).str.replace("\u00A0", " ", regex=False).str.strip()
    tokens = {"", "NA", "N/A", "NULL", "NONE", "NAN"}
    token_mask = s_str.str.upper().isin(tokens)
    return int((is_na | token_mask).sum())

def _card(label: str, value: str, sub: str = ""):
    st.markdown(
        f"<div class='card'><div class='label'>{label}</div><div class='value'>{value}</div>{f'<div class=\"sub\">{sub}</div>' if sub else ''}</div>",
        unsafe_allow_html=True,
    )

def _cards_row(items: list):
    cols = st.columns(min(4, max(1, len(items))))
    for i, (label, value, sub) in enumerate(items):
        with cols[i % len(cols)]:
            _card(label, value, sub)


# ================== UTILIDADES TEXTO/CHAVE ==================
def _strip_accents(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def norm_text(s: object) -> str:
    if s is None:
        return ""
    s = _strip_accents(str(s)).upper()
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ================== UTILIDADES DE DATA ==================
@st.cache_data(show_spinner=False)
def coerce_datetime_series(s: pd.Series) -> pd.Series:
    if s is None or s.empty:
        return pd.to_datetime(pd.Series([], dtype="object"), errors="coerce")
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True, utc=False, infer_datetime_format=True)
    if dt.isna().mean() > 0.2:
        s2 = s.astype(str).str.replace(r"[^0-9/:-]", "", regex=True)
        dt = pd.to_datetime(s2, errors="coerce", dayfirst=True, utc=False, infer_datetime_format=True)
    return dt

# ================== DETECÇÃO DE CABEÇALHO (ignora legendas/imagens) ==================

def is_probable_header_cell(x: Any) -> bool:
    """Heurística simples: parece rótulo de coluna?"""
    if pd.isna(x):
        return False
    s = str(x).strip()
    if not s:
        return False
    tmp = s.replace(".", "").replace(",", "").replace("/", "").replace("-", "").replace(":", "")
    if tmp.isdigit():
        return False
    return any(ch.isalpha() for ch in s)

@st.cache_data(show_spinner=False)
def detect_header_row_simple(df_raw: pd.DataFrame, max_scan: int = 30) -> Optional[int]:
    n = min(len(df_raw), max_scan)
    for i in range(n):
        row = df_raw.iloc[i]
        score = int(sum(is_probable_header_cell(v) for v in row))
        if score < 3:
            continue
        vals = [str(v).strip() for v in row if is_probable_header_cell(v)]
        if vals:
            unique_ratio = len(set(vals)) / len(vals)
            if unique_ratio < 0.6:
                continue
        if i + 1 < len(df_raw):
            next_nonnull = int(df_raw.iloc[i + 1].notna().sum())
            curr_nonnull = int(row.notna().sum())
            if next_nonnull < max(2, int(0.5 * curr_nonnull)):
                continue
        return i
    return None

@st.cache_data(show_spinner=False)
def read_table_smart(file, sheet: Optional[str] = None) -> pd.DataFrame:
    """Lê CSV/Excel detectando cabeçalho quando houver legendas/imagens antes da grade."""
    if file is None:
        return pd.DataFrame()
    name = getattr(file, "name", "").lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(file, sep=None, engine="python")
        # Excel
        file.seek(0)
        df_raw = pd.read_excel(file, sheet_name=sheet if sheet is not None else 0, header=None)
        idx = detect_header_row_simple(df_raw)
        if idx is None:
            file.seek(0)
            return pd.read_excel(file, sheet_name=sheet if sheet is not None else 0)
        cols = df_raw.iloc[idx].astype(str).tolist()
        df = df_raw.iloc[idx + 1 :].copy()
        df.columns = cols
        df = df.dropna(axis=1, how="all").dropna(how="all")
        return df
    except Exception:
        try:
            file.seek(0)
            return pd.read_csv(file, sep=None, engine="python")
        except Exception:
            return pd.DataFrame()

# ================== DETECÇÃO DE MISTURAS DE TIPO (fora do padrão) ==================

def detect_type_mixtures(df: pd.DataFrame, force_text: Optional[Set[str]] = None, force_numeric: Optional[Set[str]] = None) -> pd.DataFrame:
    """Varre cada coluna e identifica mistura de tipos fora do padrão esperado.
    Regras de tipo esperado:
      - Se o nome da coluna indicar **identificador** (ID/REQ/REQUER/CHAVE/SOLICIT/PROTOC) **OU** estiver em `force_text`, trata como TEXTO_ID e **não reporta mistura**.
      - Se o nome da coluna indicar **coordenada** (LATITUDE/LONGITUDE/COORD/SIRGAS) **OU** estiver em `force_numeric`, trata como **NUMERICO** (coordenadas) por padrão.
      - 'DATA' no nome, dtype datetime, ou >=70% parseável como data -> DATA
      - dtype numérico ou >=70% parseável como número -> NUMERICO
      - caso contrário -> TEXTO (não reporta mistura por padrão)
    """
    out_rows = []
    if df is None or df.empty:
        return pd.DataFrame(columns=["COLUNA","TIPO_ESPERADO","NAO_VAZIOS","VALIDOS","INVALIDOS","%INVALIDOS","PROBLEMAS","AMOSTRAS"])

    norm_force_text = set()
    if force_text:
        norm_force_text = {norm_text(c) for c in force_text if c is not None}
    norm_force_num = set()
    if force_numeric:
        norm_force_num = {norm_text(c) for c in force_numeric if c is not None}

    for c in df.columns:
        s = df[c]
        s_str = s.astype(str)
        empty_mask = s.isna() | s_str.str.strip().eq("")
        nonempty = s_str[~empty_mask]
        if nonempty.empty:
            continue

        nname = norm_text(c)
        ID_HINTS = ["_ID_NORM", "ID", "CHAVE", "REQ", "REQUER", "SOLICIT", "PROTOC"]
        if (nname in norm_force_text) or any(h in nname for h in ID_HINTS):
            continue

        COORD_HINTS = ["LATITUDE", "LONGITUDE", "COORD", "SIRGAS"]
        expected_forced_numeric = (nname in norm_force_num) or any(h in nname for h in COORD_HINTS)

        has_letters = nonempty.str.contains(r"[A-Za-z]", regex=True, na=False)

        s_num = nonempty.str.replace(r"[^0-9,\.\-]", "", regex=True)
        s_num = s_num.str.replace(r"\.", "", regex=True).str.replace(",", ".", regex=False)
        num_ok = pd.to_numeric(s_num, errors="coerce").notna()
        num_rate = float(num_ok.mean()) if len(num_ok) else 0.0

        dt_ok = pd.to_datetime(nonempty, errors="coerce", dayfirst=True).notna()
        date_rate = float(dt_ok.mean()) if len(dt_ok) else 0.0

        dtype_str = str(s.dtype)
        if expected_forced_numeric:
            expected = "NUMERICO"
        elif ("DATA" in nname) or dtype_str.startswith("datetime64") or date_rate >= 0.7:
            expected = "DATA"
        elif ("int" in dtype_str or "float" in dtype_str) or num_rate >= 0.7:
            expected = "NUMERICO"
        else:
            expected = "TEXTO"

        problems = []
        valid_cnt = invalid_cnt = nao_vazios = 0
        samples = []

        if expected == "DATA":
            nao_vazios = int(len(nonempty))
            valid_cnt = int(dt_ok.sum())
            invalid_cnt = int(nao_vazios - valid_cnt)
            if has_letters.any():
                problems.append("datas com letras/texto misto")
            if invalid_cnt > 0:
                problems.append("datas inválidas/formatos mistos")
            bad_mask = (~dt_ok) | has_letters
            samples = nonempty[bad_mask].drop_duplicates().head(8).tolist()
        elif expected == "NUMERICO":
            nao_vazios = int(len(nonempty))
            valid_cnt = int(num_ok.sum())
            invalid_cnt = int(nao_vazios - valid_cnt)
            has_comma = nonempty.str.contains(",", na=False)
            has_dot = nonempty.str.contains(r"\.", na=False)
            if has_comma.any() and has_dot.any():
                problems.append("mistura de separadores (',' e '.')")
            if has_letters.any():
                problems.append("valores numéricos com letras/símbolos")
            if invalid_cnt > 0:
                problems.append("números inválidos/formatos mistos")
            bad_mask = (~num_ok) | has_letters
            samples = nonempty[bad_mask].drop_duplicates().head(8).tolist()
        else:
            continue

        if problems:
            perc_inv = round((invalid_cnt / max(1, nao_vazios)) * 100, 2)
            out_rows.append({
                "COLUNA": c,
                "TIPO_ESPERADO": expected,
                "NAO_VAZIOS": nao_vazios,
                "VALIDOS": valid_cnt,
                "INVALIDOS": invalid_cnt,
                "%INVALIDOS": perc_inv,
                "PROBLEMAS": "; ".join(sorted(set(problems))),
                "AMOSTRAS": " | ".join(map(str, samples)),
            })

    out = pd.DataFrame(out_rows)
    if not out.empty:
        out = out.sort_values(by=["%INVALIDOS","INVALIDOS"], ascending=[False, False])
    return out

# ================== APARÊNCIA + UPLOADERS (SIDEBAR) ==================
with st.sidebar:
    st.header("Aparência")
    tema_claro = st.toggle(
        "Tema claro (logo colorido)", value=False,
        help="Altera o logo exibido: colorido no claro e branco no escuro."
    )
    logo_name = "cropped-SP-Aguas-Colorido.png" if tema_claro else "logo-white.png"
    try:
        logo_path = resource_path(f"assets/{logo_name}")
        if logo_path.exists():
            st.image(str(logo_path), width=220)
        # nome do arquivo abaixo do logo
        st.caption(f"assets/{logo_name}")
    except Exception:
        pass

    st.header("Arquivos")
    up_a = st.file_uploader("Base A (xlsx/csv)", type=["xlsx", "xls", "csv"], key="fileA")
    up_b = st.file_uploader("Base B (xlsx/csv)", type=["xlsx", "xls", "csv"], key="fileB")

    # Seleção de planilha quando for Excel
    sheet_a = sheet_b = None
    if up_a and up_a.name.lower().endswith((".xlsx", ".xls")):
        try:
            xlsa = pd.ExcelFile(up_a)
            sheet_a = st.selectbox("Planilha da Base A", xlsa.sheet_names, index=0)
        except Exception:
            sheet_a = None
        finally:
            up_a.seek(0)
    if up_b and up_b.name.lower().endswith((".xlsx", ".xls")):
        try:
            xlsb = pd.ExcelFile(up_b)
            sheet_b = st.selectbox("Planilha da Base B", xlsb.sheet_names, index=0)
        except Exception:
            sheet_b = None
        finally:
            up_b.seek(0)

    st.markdown("---")
    st.subheader("Opções")
    debug_mode = st.toggle("Modo debug (logs verbosos)", value=False)

# ================== LEITURA DOS ARQUIVOS ==================
@st.cache_data(show_spinner=False)
def read_any_table(file) -> pd.DataFrame:
    if file is None:
        return pd.DataFrame()
    name = getattr(file, "name", "").lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(file, sep=None, engine="python")
        else:
            return pd.read_excel(file, engine="openpyxl")
    except Exception as e:
        try:
            file.seek(0)
            return pd.read_csv(file, sep=None, engine="python")
        except Exception:
            raise e

# ================== MOTOR DE DIAGNÓSTICO ==================
def compare_dates(dt_a: Optional[pd.Timestamp], dt_b: Optional[pd.Timestamp], tol_days: int) -> Tuple[bool, Optional[int]]:
    if pd.isna(dt_a) and pd.isna(dt_b):
        return True, None
    if pd.isna(dt_a) or pd.isna(dt_b):
        return False, None
    delta = int(abs((dt_a - dt_b).days))
    return (delta <= tol_days), delta

# ================== FORMATAÇÃO DE DATAS (EXPORTAÇÃO) ==================
def format_dates_for_export(df: pd.DataFrame, preferred_cols: Optional[List[str]] = None) -> pd.DataFrame:
    out = df.copy()
    cols = set(preferred_cols or [])
    for c in out.columns:
        if c in cols or ("DATA" in norm_text(c) or str(out[c].dtype).startswith("datetime64")):
            try:
                out[c] = pd.to_datetime(out[c], errors="coerce", dayfirst=True).dt.strftime("%d/%m/%Y")
            except Exception:
                pass
    return out

# ================== DETECÇÃO DE COLUNAS (USO/FINALIDADE) ==================
USO_HINTS = [
    "USO", "TIPO USO", "TIPO DE USO", "TP_USO", "TPUSO"
]
FINALIDADE_HINTS = [
    "FINALIDADE", "SUBTIPO", "CATEGORIA USO", "DESTINACAO", "DESTINAÇÃO", "FINALIDADE/USO"
]

def guess_col(cols: List[str], hints: List[str]) -> Optional[str]:
    nm = {c: norm_text(c) for c in cols}
    hs = [norm_text(h) for h in hints]
    for c, n in nm.items():
        if any(h in n for h in hs):
            return c
    return None

# ================== CARDS (RESUMO POR BASE) ==================

def render_base_cards(df: pd.DataFrame, base_nome: str, pub_col: Optional[str], uso_col: Optional[str], fin_col: Optional[str]):
    st.markdown(f"**Resultados — {base_nome}**")
    with st.expander("❓ O que é esta seção?", expanded=False):
        st.markdown("Mostra contagens e vazios por coluna, ajudando a priorizar tratamento de dados.")
    total_rows = int(len(df))
    total_cols = int(df.shape[1])

    if "_DATA_PUBLICACAO" in df.columns:
        sem_pub = int(pd.to_datetime(df["_DATA_PUBLICACAO"], errors="coerce").isna().sum())
    elif pub_col and pub_col in df.columns:
        sem_pub = int(pd.to_datetime(df[pub_col], errors="coerce", dayfirst=True).isna().sum())
    else:
        sem_pub = None

    sem_uso = count_missing(df[uso_col]) if (uso_col and uso_col in df.columns) else None
    sem_fin = count_missing(df[fin_col]) if (fin_col and fin_col in df.columns) else None

    vazios_por_col = df.apply(count_missing)
    cols_com_vazio = int((vazios_por_col > 0).sum())

    _cards_row([
        ("Requerimentos", f"{total_rows:,}".replace(",", "."), ""),
        ("Sem Data de Publicação", ("—" if sem_pub is None else f"{sem_pub:,}".replace(",", ".")), ""),
        ("Sem Tipo de Uso", ("—" if sem_uso is None else f"{sem_uso:,}".replace(",", ".")), ""),
    ])
    _cards_row([
        ("Sem Finalidade", ("—" if sem_fin is None else f"{sem_fin:,}".replace(",", ".")), ""),
        ("Total de Colunas", f"{total_cols:,}".replace(",", "."), ""),
        ("Colunas com vazios", f"{cols_com_vazio:,}".replace(",", "."), ""),
    ])

    st.markdown("**Sem preenchimento por coluna — todos**")
    grid_cols = st.columns(4)
    nonzero = vazios_por_col[vazios_por_col > 0]
    if nonzero.empty:
        st.info("Todas as colunas estão preenchidas (sem vazios).")
    else:
        for i, (nome, qtd) in enumerate(nonzero.items()):
            with grid_cols[i % 4]:
                _card(str(nome), f"{int(qtd):,}".replace(",", "."))


# Cards por tabela específica

def render_table_cards(df: pd.DataFrame, titulo: str, pub_col: Optional[str], uso_col: Optional[str], fin_col: Optional[str]):
    total_rows = int(len(df))
    total_cols = int(df.shape[1])
    if df.empty:
        _cards_row([(titulo, "0", "sem linhas")])
        return

    if "_DATA_PUBLICACAO" in df.columns:
        sem_pub = int(pd.to_datetime(df["_DATA_PUBLICACAO"], errors="coerce").isna().sum())
    elif pub_col and pub_col in df.columns:
        sem_pub = int(pd.to_datetime(df[pub_col], errors="coerce", dayfirst=True).isna().sum())
    else:
        sem_pub = None

    sem_uso = count_missing(df[uso_col]) if (uso_col and uso_col in df.columns) else None
    sem_fin = count_missing(df[fin_col]) if (fin_col and fin_col in df.columns) else None
    vazios_por_col = df.apply(count_missing)
    cols_com_vazio = int((vazios_por_col > 0).sum())

    st.markdown(f"**Cards — {titulo}**")
    with st.expander("❓ Para que serve?", expanded=False):
        st.markdown("Resumo rápido da tabela exibida abaixo (linhas, vazios e colunas).")
    _cards_row([
        ("Linhas", f"{total_rows:,}".replace(",", "."), ""),
        ("Sem Publicação", ("—" if sem_pub is None else f"{sem_pub:,}".replace(",", ".")), ""),
        ("Sem Tipo de Uso", ("—" if sem_uso is None else f"{sem_uso:,}".replace(",", ".")), ""),
    ])
    _cards_row([
        ("Sem Finalidade", ("—" if sem_fin is None else f"{sem_fin:,}".replace(",", ".")), ""),
        ("Total de Colunas", f"{total_cols:,}".replace(",", "."), ""),
        ("Colunas com vazios", f"{cols_com_vazio:,}".replace(",", "."), ""),
    ])

# ================== CHECKLIST: funções auxiliares ==================
def build_checklist(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    def _collapse_dup_col(df: pd.DataFrame, colname: str) -> Optional[pd.Series]:
        if colname not in df.columns:
            return None
        mask = (df.columns == colname)
        if mask.sum() == 1:
            return df[colname]
        sub = df.loc[:, mask]
        collapsed = sub.bfill(axis=1).iloc[:, 0]
        collapsed.name = colname
        return collapsed

    cols_union = sorted(set(df_a.columns) | set(df_b.columns), key=lambda x: str(x).lower())
    has_id = ("_ID_NORM" in df_a.columns) and ("_ID_NORM" in df_b.columns)

    rows = []
    for c in cols_union:
        in_a = c in df_a.columns
        in_b = c in df_b.columns
        dtype_a = str(df_a[c].dtype) if in_a else ""
        dtype_b = str(df_b[c].dtype) if in_b else ""
        rows_a = len(df_a)
        rows_b = len(df_b)
        filled_a = int(df_a[c].notna().sum()) if in_a else 0
        filled_b = int(df_b[c].notna().sum()) if in_b else 0
        pct_a = (filled_a / rows_a * 100.0) if rows_a else 0.0
        pct_b = (filled_b / rows_b * 100.0) if rows_b else 0.0

        comparable = match_cnt = mismatch_cnt = None
        ids_dup_a = ids_dup_b = None

        if has_id and in_a and in_b:
            idA = _collapse_dup_col(df_a, "_ID_NORM")
            idB = _collapse_dup_col(df_b, "_ID_NORM")
            valA = _collapse_dup_col(df_a, c)
            valB = _collapse_dup_col(df_b, c)

            if idA is not None and idB is not None and valA is not None and valB is not None:
                tmp_a = pd.DataFrame({"_ID_NORM": idA, "VAL": valA}).dropna(subset=["_ID_NORM"])  
                tmp_b = pd.DataFrame({"_ID_NORM": idB, "VAL": valB}).dropna(subset=["_ID_NORM"])  

                ids_dup_a = int(tmp_a["_ID_NORM"].duplicated(keep=False).sum())
                ids_dup_b = int(tmp_b["_ID_NORM"].duplicated(keep=False).sum())

                def _first_non_null_norm(series: pd.Series) -> str:
                    for v in series:
                        if pd.notna(v) and str(v).strip() != "":
                            return norm_text(v)
                    return ""

                sA = tmp_a.groupby("_ID_NORM")["VAL"].apply(_first_non_null_norm)
                sB = tmp_b.groupby("_ID_NORM")["VAL"].apply(_first_non_null_norm)

                aligned = pd.concat([sA, sB], axis=1, keys=["A", "B"], join="inner")
                aligned = aligned[(aligned["A"] != "") & (aligned["B"] != "")]
                comparable = int(len(aligned))
                if comparable > 0:
                    comp = (aligned["A"] == aligned["B"])
                    match_cnt = int(comp.sum())
                    mismatch_cnt = int(comparable - match_cnt)

        rows.append({
            "COLUNA": c,
            "EXISTE_EM_A": in_a,
            "EXISTE_EM_B": in_b,
            "DTYPE_A": dtype_a,
            "DTYPE_B": dtype_b,
            "LINHAS_A": rows_a,
            "PREENCHIDOS_A": filled_a,
            "%_A": round(pct_a, 2),
            "LINHAS_B": rows_b,
            "PREENCHIDOS_B": filled_b,
            "%_B": round(pct_b, 2),
            "ID_DUPLICADOS_A": ids_dup_a,
            "ID_DUPLICADOS_B": ids_dup_b,
            "COMPARAVEIS": comparable,
            "IGUAIS": match_cnt,
            "DIFERENTES": mismatch_cnt,
        })

    checklist = pd.DataFrame(rows)
    checklist["BOTH"] = checklist["EXISTE_EM_A"].astype(int) & checklist["EXISTE_EM_B"].astype(int)
    checklist = checklist.sort_values(by=["BOTH", "%_A", "%_B"], ascending=[False, True, True]).drop(columns=["BOTH"])  
    return checklist


def generate_checklist_pdf(df: pd.DataFrame) -> Optional[bytes]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12, rightMargin=12, topMargin=12, bottomMargin=12)
        data = [list(df.columns)] + df.astype(str).values.tolist()
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        doc.build([tbl])
        pdf = buf.getvalue()
        buf.close()
        return pdf
    except Exception:
        return None

# ================== CORPO DO APP ==================
try:
    if not up_a or not up_b:
        st.info("Envie **Base A** e **Base B** pela **barra lateral**.")
        st.stop()

    with st.spinner("Lendo arquivos..."):
        df_a = read_table_smart(up_a, sheet=sheet_a)
        up_a.seek(0)
        df_b = read_table_smart(up_b, sheet=sheet_b)
        up_b.seek(0)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Prévia Base A")
        with st.expander("❓ O que é a Base A?", expanded=False):
            st.markdown("Primeira aba/arquivo base para comparação e diagnóstico inicial.")
        st.write(df_a.shape)
        st.dataframe(df_a.head(20), use_container_width=True)
    with col2:
        st.subheader("Prévia Base B")
        with st.expander("❓ O que é a Base B?", expanded=False):
            st.markdown("Segunda aba/arquivo usado para confronto com a Base A.")
        st.write(df_b.shape)
        st.dataframe(df_b.head(20), use_container_width=True)

    st.divider()
    st.subheader("Normalização de chaves")

    def _guess_id_col(cols: List[str]) -> Optional[int]:
        targets = {"ID", "CHAVE", "REQ", "NROREQ", "SOLCTREQ", "SOLCTREC", "REQUERIMENTO"}
        norm_cols = [norm_text(c) for c in cols]
        for i, c in enumerate(norm_cols):
            if any(t == c or t in c for t in targets):
                return i
        return 0 if cols else None

    idx_a_guess = _guess_id_col(list(df_a.columns)) or 0
    idx_b_guess = _guess_id_col(list(df_b.columns)) or 0

    sel_id_a = st.selectbox("Coluna de ID/Chave na Base A", options=list(df_a.columns), index=idx_a_guess if df_a.columns.size else None)
    sel_id_b = st.selectbox("Coluna de ID/Chave na Base B", options=list(df_b.columns), index=idx_b_guess if df_b.columns.size else None)

    if sel_id_a and sel_id_b:
        df_a["_ID_NORM"] = df_a[sel_id_a].astype(str).map(norm_text)
        df_b["_ID_NORM"] = df_b[sel_id_b].astype(str).map(norm_text)

    pub_cols = [c for c in df_a.columns if "PUBLICA" in norm_text(c)]
    ent_cols = [c for c in df_a.columns if "ENTRADA" in norm_text(c)]

    pub_a_col = pub_cols[0] if pub_cols else None
    pub_b_col = pub_cols[0] if pub_cols and pub_cols[0] in df_b.columns else None
    ent_a_col = ent_cols[0] if ent_cols else None
    ent_b_col = ent_cols[0] if ent_cols and ent_cols[0] in df_b.columns else None

    if pub_a_col: df_a["_DATA_PUBLICACAO"] = coerce_datetime_series(df_a[pub_a_col])
    if pub_b_col: df_b["_DATA_PUBLICACAO"] = coerce_datetime_series(df_b[pub_b_col])
    if ent_a_col: df_a["_DATA_ENTRADA"] = coerce_datetime_series(df_a[ent_a_col])
    if ent_b_col: df_b["_DATA_ENTRADA"] = coerce_datetime_series(df_b[ent_b_col])

    uso_a_col = guess_col(list(df_a.columns), USO_HINTS)
    uso_b_col = guess_col(list(df_b.columns), USO_HINTS)
    fin_a_col = guess_col(list(df_a.columns), FINALIDADE_HINTS)
    fin_b_col = guess_col(list(df_b.columns), FINALIDADE_HINTS)

    cardsA, cardsB = st.columns(2)
    with cardsA:
        render_base_cards(df_a, "Base A", pub_a_col, uso_a_col, fin_a_col)
    with cardsB:
        render_base_cards(df_b, "Base B", pub_b_col, uso_b_col, fin_b_col)

    # ===== Misturas de tipo (fora do padrão) por base =====
    title_a = "Misturas de tipo — Base A"
    if up_a:
        title_a += f" · Tipos de Dados Misturados ({up_a.name})"
    st.subheader(title_a)
    with st.expander("❓ O que é esta seção?", expanded=False):
        st.markdown("Relatório que identifica colunas com **formatos mistos** (número/texto; data/texto) na Base A.")
    force_text_a = {x for x in [sel_id_a, "_ID_NORM", "REQUERIMENTO", "SOLICITACAO_REQUERIMENTO", "SOLICITAÇÃO_REQUERIMENTO"] if x and x in df_a.columns}
    force_num_a = {x for x in ["LATITUDE_SIRGAS2000", "LONGITUDE_SIRGAS2000", "LATITUDE", "LONGITUDE"] if x in df_a.columns}
    mix_a = detect_type_mixtures(df_a, force_text=force_text_a, force_numeric=force_num_a)
    if mix_a is None or mix_a.empty:
        st.success("Nenhuma mistura identificada na Base A.")
    else:
        st.dataframe(mix_a, use_container_width=True, height=320)
        st.download_button(
            "Baixar misturas — Base A (CSV)",
            data=mix_a.to_csv(index=False).encode("utf-8-sig"),
            file_name="misturas_base_A.csv",
            mime="text/csv",
        )

    title_b = "Misturas de tipo — Base B"
    if up_b:
        title_b += f" · Tipos de Dados Misturados ({up_b.name})"
    st.subheader(title_b)
    with st.expander("❓ O que é esta seção?", expanded=False):
        st.markdown("Relatório que identifica colunas com **formatos mistos** (número/texto; data/texto) na Base B.")
    force_text_b = {x for x in [sel_id_b, "_ID_NORM", "REQUERIMENTO", "SOLICITACAO_REQUERIMENTO", "SOLICITAÇÃO_REQUERIMENTO"] if x and x in df_b.columns}
    force_num_b = {x for x in ["LATITUDE_SIRGAS2000", "LONGITUDE_SIRGAS2000", "LATITUDE", "LONGITUDE"] if x in df_b.columns}
    mix_b = detect_type_mixtures(df_b, force_text=force_text_b, force_numeric=force_num_b)
    if mix_b is None or mix_b.empty:
        st.success("Nenhuma mistura identificada na Base B.")
    else:
        st.dataframe(mix_b, use_container_width=True, height=320)
        st.download_button(
            "Baixar misturas — Base B (CSV)",
            data=mix_b.to_csv(index=False).encode("utf-8-sig"),
            file_name="misturas_base_B.csv",
            mime="text/csv",
        )

    st.subheader("Processamento principal")

    if "_ID_NORM" in df_a.columns and "_ID_NORM" in df_b.columns:
        ids_a = set(df_a["_ID_NORM"]) if not df_a.empty else set()
        ids_b = set(df_b["_ID_NORM"]) if not df_b.empty else set()
        only_a = sorted(ids_a - ids_b)
        only_b = sorted(ids_b - ids_a)
        st.write(f"IDs somente na A: {len(only_a)} | somente na B: {len(only_b)}")

        col3, col4 = st.columns(2)
        with col3:
            st.markdown("**Somente na A**")
            df_only_a = df_a[df_a["_ID_NORM"].isin(only_a)].copy()
            render_table_cards(df_only_a, "Somente na A", pub_a_col, uso_a_col, fin_a_col)
            export_only_a = format_dates_for_export(df_only_a)
            st.dataframe(export_only_a.head(200), use_container_width=True, height=300)
            st.download_button(
                "Baixar somente A (CSV)",
                data=export_only_a.to_csv(index=False).encode("utf-8-sig"),
                file_name="ids_somente_A.csv",
                mime="text/csv",
            )

        with col4:
            st.markdown("**Somente na B**")
            df_only_b = df_b[df_b["_ID_NORM"].isin(only_b)].copy()
            render_table_cards(df_only_b, "Somente na B", pub_b_col, uso_b_col, fin_b_col)
            export_only_b = format_dates_for_export(df_only_b)
            st.dataframe(export_only_b.head(200), use_container_width=True, height=300)
            st.download_button(
                "Baixar somente B (CSV)",
                data=export_only_b.to_csv(index=False).encode("utf-8-sig"),
                file_name="ids_somente_B.csv",
                mime="text/csv",
            )

        st.subheader("Checklist entre as bases (coluna a coluna)")
        with st.expander("❓ Como usar o checklist?", expanded=False):
            st.markdown("Compara preenchimento e valores por **_ID_NORM** para localizar divergências e colunas críticas.")
        checklist_df = build_checklist(df_a, df_b)
        checklist_display = format_dates_for_export(checklist_df)
        st.dataframe(checklist_display, use_container_width=True, height=380)
        st.download_button(
            "Baixar checklist (CSV)",
            data=checklist_display.to_csv(index=False).encode("utf-8-sig"),
            file_name="checklist_bases.csv",
            mime="text/csv",
        )
        pdf_bytes = generate_checklist_pdf(checklist_display)
        if pdf_bytes:
            st.download_button(
                "Baixar checklist (PDF)",
                data=pdf_bytes,
                file_name="checklist_bases.pdf",
                mime="application/pdf",
            )
        else:
            st.info("Para exportar PDF diretamente, instale o pacote `reportlab`. Já disponibilizei o CSV.")

        st.markdown("---")
        st.markdown("**Merge (A ⟕ B) para auditoria**")
        merged = df_a.merge(df_b.add_prefix("B__"), left_on="_ID_NORM", right_on="B__" + "_ID_NORM", how="left", indicator=True)
        export_merged = format_dates_for_export(merged)

        st.markdown("**Comparação A vs B (colunas em comum, lado a lado)**")
        common_cols = [c for c in df_a.columns if c in df_b.columns and c != "_ID_NORM"]
        if not common_cols:
            st.info("Não há colunas em comum entre A e B para comparar.")
        else:
            sbs = pd.DataFrame({"_ID_NORM": merged.get("_ID_NORM", pd.Series(index=merged.index))})
            for c in common_cols:
                colA = c
                colB = "B__" + c
                if (colA in merged.columns) and (colB in merged.columns):
                    sbs[f"{c} (A)"] = merged[colA]
                    sbs[f"{c} (B)"] = merged[colB]
            sbs_export = format_dates_for_export(sbs)
            st.dataframe(sbs_export.head(100), use_container_width=True)
            st.download_button(
                "Baixar comparação A vs B (CSV)",
                data=sbs_export.to_csv(index=False).encode("utf-8-sig"),
                file_name="comparacao_A_vs_B.csv",
                mime="text/csv",
            )
        st.dataframe(export_merged.head(100), use_container_width=True)
        st.download_button(
            "Baixar merge (CSV)",
            data=export_merged.to_csv(index=False).encode("utf-8-sig"),
            file_name="merge_A_left_B.csv",
            mime="text/csv",
        )

    else:
        st.info("Defina as colunas de chave em A e B para continuar o processamento.")

    if debug_mode:
        with st.expander("Debug"):
            st.write({"cols_a": list(df_a.columns)[:200], "cols_b": list(df_b.columns)[:200]})

except Exception:
    st.error("Ocorreu um erro durante a execução do app:")
    st.exception(traceback.format_exc())
    st.stop()
