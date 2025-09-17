import io
import re
from typing import Dict, List, Optional, Tuple, Set
import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process
from unidecode import unidecode

# =============== Configurações base ===============
TARGET_DEFAULT = "SOLICITAÇÃO_REQUERIMENTO"
TARGET_ALIASES = [
    "SOLICITAÇÃO_REQUERIMENTO",
    "SOLICITACAO_REQUERIMENTO",
    "SOLICITAÇÃO / REQUERIMENTO",
    "SOLICITACAO / REQUERIMENTO",
    "SOLICITAÇÃO-REQUERIMENTO",
    "SOLICITAÇÃO REQUERIMENTO",
    "NRO_SOLICITACAO_REQUERIMENTO",
    "NRO SOLICITACAO REQUERIMENTO",
    "SOLICITAÇÃO",
    "SOLICITACAO",
    "SOL_REQ",
    "SOLICITACAO+REQUERIMENTO",
]
USO_ALIASES = [
    "USO", "TIPO_USO", "TIPO DE USO", "TIPO USO",
    "FINALIDADE", "TIPO_DE_USO", "TIPO UTILIZAÇÃO", "TIPO UTILIZACAO",
    "TIPO DE USO DO RECURSO", "USO/FINALIDADE"
]

FUZZ_THRESHOLD = 88  # afinado para tolerar variações sem pegar falsos positivos

# =============== Funções utilitárias ===============
def norm_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = unidecode(s)                # remove acentos
    s = s.replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)      # normaliza espaços
    s = s.replace("-", " ").replace("_", " ").strip()
    return s.upper()

def best_match(name: str, candidates: List[str], threshold: int = FUZZ_THRESHOLD) -> Tuple[Optional[str], int]:
    """Retorna (melhor_candidato, score) acima do limiar; senão (None, 0)."""
    if not candidates:
        return (None, 0)
    name_n = norm_text(name)
    cand_n = [norm_text(c) for c in candidates]
    res = process.extractOne(name_n, cand_n, scorer=fuzz.token_set_ratio)
    if res is None:
        return (None, 0)
    idx = res[2]
    score = res[1]
    return (candidates[idx], score) if score >= threshold else (None, score)

def find_header_row(preview_df: pd.DataFrame, target_names: List[str]) -> Optional[int]:
    """
    Varre as primeiras ~200 linhas lidas sem cabeçalho e tenta achar
    a linha que contém a coluna alvo (por nome/alias/fuzzy).
    """
    # Cria lista normalizada de aliases
    target_norms = {norm_text(t) for t in target_names}
    for i, row in preview_df.iterrows():
        cells = [norm_text(c) for c in row.tolist()]
        # match exato com qualquer alias
        if any(c in target_norms for c in cells):
            return i
        # fuzzy: se algum cell combina bem com qualquer alias
        for cell in cells:
            m, score = best_match(cell, target_names, FUZZ_THRESHOLD)
            if m:
                return i
    return None

def read_table_from_sheet(file_bytes: bytes, sheet_name, target_names: List[str]) -> Tuple[Optional[pd.DataFrame], Optional[int]]:
    """
    Lê a planilha sem cabeçalho, detecta a linha de cabeçalho onde está a coluna alvo e devolve o DF com cabeçalho correto.
    """
    try:
        preview = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=None, nrows=200, dtype=str, engine="openpyxl")
    except Exception:
        # fallback engine
        preview = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=None, nrows=200, dtype=str)

    header_row = find_header_row(preview, target_names)
    if header_row is None:
        return None, None

    # Lê a planilha inteira a partir do header_row
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=header_row, dtype=str, engine="openpyxl")
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=header_row, dtype=str)

    # Remove linhas totalmente vazias
    df = df.dropna(how="all")
    # Normaliza nomes de colunas
    df.columns = [norm_text(c) for c in df.columns]
    return df, header_row

def pick_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Escolhe a melhor coluna no DF a partir dos aliases com fuzzy."""
    cols = list(df.columns)
    # 1) tentar match exato após normalização
    cand_norms = [norm_text(c) for c in candidates]
    for c in cols:
        if norm_text(c) in cand_norms:
            return c
    # 2) fuzzy
    for c in cols:
        m, score = best_match(c, candidates, FUZZ_THRESHOLD)
        if m:
            return c
    return None

def normalize_id(val: Optional[str], keep_leading_zeros=True) -> Optional[str]:
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "":
        return None
    # Modo conservador: só aparar espaços; manter zeros à esquerda por padrão
    # Remover quebras de linha/espaços duplos já foi
    # Opcional: remover separadores comuns (.,/,-, espaço) para comparar formatos diferentes
    s_compare = re.sub(r"[.\-\/\s]", "", s)
    return s if keep_leading_zeros else s_compare

def analyze_df(df: pd.DataFrame, target_col: str, uso_col: Optional[str]) -> Dict:
    ids_raw = df[target_col]
    ids_norm = ids_raw.apply(lambda x: normalize_id(x, keep_leading_zeros=True))

    total_rows = len(df)
    nonnull = ids_norm.notna().sum()
    blanks = (ids_norm.isna()).sum()

    # Duplicados (considerando normalização conservadora)
    dup_counts = ids_norm.value_counts()
    duplicates = dup_counts[dup_counts > 1]

    usos_set: Set[str] = set()
    if uso_col and uso_col in df.columns:
        usos = df[uso_col].dropna().astype(str).map(lambda s: norm_text(s).strip())
        usos_set = set([u for u in usos if u != ""])

    return {
        "total_rows": total_rows,
        "nonnull": nonnull,
        "blank": blanks,
        "duplicates_series": duplicates,
        "id_set": set(ids_norm.dropna().astype(str)),
        "usos_set": usos_set
    }

def guess_uso_column(df: pd.DataFrame, uso_aliases: List[str]) -> Optional[str]:
    return pick_column(df, uso_aliases)

# =============== UI ===============
st.set_page_config(page_title="Validador de Solicitações (Excel)", layout="wide")
st.title("🔎 Validador de Solicitações — Excel")
st.caption("Detecta tabelas em planilhas 'sujas', encontra a coluna **SOLICITAÇÃO_REQUERIMENTO**, conta linhas, e compara divergências entre arquivos. (Funciona com múltiplos .xls/.xlsx)")

with st.expander("⚙️ Configurações", expanded=False):
    target_input = st.text_input("Nome esperado da coluna-alvo", value=TARGET_DEFAULT)
    aliases_extra = st.text_area("Aliases adicionais (um por linha, opcional)", value="")
    uso_toggle = st.checkbox("Detectar e comparar também a coluna de USO/FINALIDADE", value=True)
    uso_aliases_extra = st.text_area("Aliases extras para USO (um por linha, opcional)", value="")

    target_names = [target_input.strip()] + TARGET_ALIASES
    if aliases_extra.strip():
        target_names = [target_input.strip()] + [a.strip() for a in aliases_extra.splitlines() if a.strip()] + TARGET_ALIASES

    uso_names = USO_ALIASES.copy()
    if uso_aliases_extra.strip():
        uso_names = [a.strip() for a in uso_aliases_extra.splitlines() if a.strip()] + uso_names

files = st.file_uploader(
    "Anexe um ou mais arquivos Excel",
    type=["xlsx", "xls"],
    accept_multiple_files=True
)

if not files:
    st.info("Anexe seus arquivos para começar. Dica: você pode arrastar vários `.xlsx`/`.xls` de uma vez.")
    st.stop()

# =============== Processamento ===============
summ_rows = []
all_id_sets: Dict[str, Set[str]] = {}
all_uso_sets: Dict[str, Set[str]] = {}
dup_overview: Dict[str, pd.Series] = {}

for up in files:
    file_bytes = up.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        sheets = xls.sheet_names
    except Exception:
        st.error(f"❌ Não consegui abrir: {up.name}")
        continue

    for sh in sheets:
        df, header_row = read_table_from_sheet(file_bytes, sh, target_names)
        if df is None:
            summ_rows.append({
                "Arquivo": up.name,
                "Planilha": sh,
                "Status": "Tabela não encontrada (coluna alvo ausente)",
                "HeaderRow": None,
                "LinhasTotais": None,
                "Com_ColunaAlvo": None,
                "Vazias_ColunaAlvo": None
            })
            continue

        # Escolher coluna alvo (pode ter sido renomeada ao normalizar)
        target_col = pick_column(df, target_names)
        if not target_col:
            summ_rows.append({
                "Arquivo": up.name,
                "Planilha": sh,
                "Status": "Coluna alvo não identificada após leitura",
                "HeaderRow": header_row,
                "LinhasTotais": len(df),
                "Com_ColunaAlvo": 0,
                "Vazias_ColunaAlvo": len(df)
            })
            continue

        # USO (opcional)
        uso_col = None
        if uso_toggle:
            uso_col = guess_uso_column(df, uso_names)

        res = analyze_df(df, target_col, uso_col)

        summ_rows.append({
            "Arquivo": up.name,
            "Planilha": sh,
            "Status": "OK",
            "HeaderRow": header_row,
            "Coluna_Alvo": target_col,
            "Coluna_Uso": uso_col or "",
            "LinhasTotais": res["total_rows"],
            "Com_ColunaAlvo": res["nonnull"],
            "Vazias_ColunaAlvo": res["blank"],
            "Duplicados_Count": int(res["duplicates_series"].sum()) if not res["duplicates_series"].empty else 0
        })

        key = f"{up.name}::{sh}"
        all_id_sets[key] = res["id_set"]
        all_uso_sets[key] = res["usos_set"]
        dup_overview[key] = res["duplicates_series"]

# =============== Relatórios ===============
st.subheader("📊 Resumo por arquivo/planilha")
summary_df = pd.DataFrame(summ_rows)
st.dataframe(summary_df, use_container_width=True)

# Diagnóstico consolidado
if all_id_sets:
    st.subheader("🧮 Consolidação das Solicitações")

    union_ids = set().union(*all_id_sets.values()) if all_id_sets else set()
    inter_ids = set.intersection(*all_id_sets.values()) if len(all_id_sets) > 1 else next(iter(all_id_sets.values()))

    st.markdown(f"- **Total (união)** de solicitações distintas: **{len(union_ids)}**")
    st.markdown(f"- **Interseção** (presentes em todos os arquivos): **{len(inter_ids)}**")

    # Faltantes por arquivo
    st.markdown("**IDs faltantes (por arquivo/planilha) em relação à união:**")
    for key, s in all_id_sets.items():
        missing = union_ids - s
        st.write(f"• {key}: faltam {len(missing)}")
        if len(missing) <= 50:
            st.code(", ".join(sorted(list(missing))[:50]) if missing else "—")

    # Extras por arquivo (presentes só nele)
    st.markdown("**IDs exclusivos (aparecem somente nesse arquivo/planilha):**")
    for key, s in all_id_sets.items():
        others = set().union(*[v for k, v in all_id_sets.items() if k != key]) if len(all_id_sets) > 1 else set()
        only_here = s - others
        st.write(f"• {key}: exclusivos {len(only_here)}")
        if len(only_here) <= 50:
            st.code(", ".join(sorted(list(only_here))[:50]) if only_here else "—")

    # Duplicados por origem
    st.markdown("**Possíveis causas de divergência detectadas:**")
    bullets = []
    if (summary_df["Duplicados_Count"].fillna(0) > 0).any():
        bullets.append("• **Duplicados** da coluna-alvo em um ou mais arquivos.")
    if (summary_df["Vazias_ColunaAlvo"].fillna(0) > 0).any():
        bullets.append("• **Linhas vazias** na coluna-alvo (registros incompletos).")
    if len(all_id_sets) > 1 and (len(union_ids) != summary_df["Com_ColunaAlvo"].sum()):
        bullets.append("• **Formatação divergente** (zeros à esquerda, separadores, espaços).")
    if not bullets:
        bullets.append("• Não foram detectados problemas óbvios além de diferenças reais entre os conjuntos.")
    st.write("\n".join(bullets))

    # Mostrar duplicados
    any_dups = any((not s.empty) for s in dup_overview.values())
    if any_dups:
        st.markdown("**Detalhe de IDs duplicados por arquivo/planilha:**")
        for key, s in dup_overview.items():
            if not s.empty:
                st.write(f"• {key}: {int(s.sum())} duplicado(s)")
                st.dataframe(s.rename("Ocorrências").to_frame(), use_container_width=True)

# USOS
if uso_toggle and any(len(s) > 0 for s in all_uso_sets.values()):
    st.subheader("🗂️ Comparação de USOS/FINALIDADES")
    union_usos = set().union(*all_uso_sets.values())
    st.markdown(f"- **Total de categorias de USO** (união): **{len(union_usos)}**")

    for key, s in all_uso_sets.items():
        missing = union_usos - s
        st.write(f"• {key}: categorias faltantes {len(missing)}")
        if len(missing) <= 30:
            st.code(", ".join(sorted(list(missing))) if missing else "—")

# Export
st.subheader("⬇️ Exportar relatório")
def make_report_csv(summary: pd.DataFrame,
                    id_sets: Dict[str, Set[str]],
                    uso_sets: Dict[str, Set[str]]) -> bytes:
    out = io.StringIO()
    out.write("# Resumo por arquivo/planilha\n")
    summary.to_csv(out, index=False)
    out.write("\n\n# IDs por origem (listados até 10.000)\n")
    for key, s in id_sets.items():
        lst = sorted(list(s))[:10000]
        out.write(f"\n[{key}] ({len(s)} IDs)\n")
        out.write(",".join(lst) + "\n")
    if uso_sets:
        out.write("\n\n# USOS por origem\n")
        for key, s in uso_sets.items():
            lst = sorted(list(s))[:10000]
            out.write(f"\n[{key}] ({len(s)} USOS)\n")
            out.write(",".join(lst) + "\n")
    return out.getvalue().encode("utf-8")

csv_bytes = make_report_csv(summary_df, all_id_sets, all_uso_sets)
st.download_button(
    "Baixar relatório CSV",
    data=csv_bytes,
    file_name="relatorio_solicitacoes.csv",
    mime="text/csv"
)

st.success("Pronto! Se quiser, me mande um print do resumo ou um recorte do CSV que eu te digo exatamente onde ajustar na origem.")
