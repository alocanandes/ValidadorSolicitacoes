# -*- coding: utf-8 -*-
"""
Validador de Relatórios (Excel) — versão com opções de tema e ajuda contextual.
"""

from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import streamlit as st
from rapidfuzz import process
from unidecode import unidecode

# ================== CONFIGURAÇÃO DA PÁGINA ==================
st.set_page_config(
    page_title="Validador de RELATÓRIOS (Excel)",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================== HELPER DE RECURSOS (DEV + EXE) ==================
def resource_path(rel_path: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent
    return (base / rel_path).resolve()

# ================== OPÇÕES DE TEMA E DEBUG ==================
st.sidebar.header("Opções")
modo_debug = st.sidebar.toggle("Modo debug (logs detalhados)", value=False)

modo_tema = st.sidebar.radio(
    "Tema visual:",
    options=["Escuro", "Claro"],
    index=0,
    help="Altere entre tema escuro e claro. A logo muda automaticamente."
)

# Logo dinâmico conforme tema
if modo_tema == "Claro":
    logo_file = resource_path("assets/cropped-SP-Aguas-Colorido.png")
else:
    logo_file = resource_path("assets/logo-white.png")

if logo_file.exists():
    try:
        st.sidebar.image(str(logo_file), use_container_width=True)
    except Exception:
        pass

st.sidebar.caption(f"Logo usada: {Path(logo_file).name}")

# ================== AJUDA CONTEXTUAL (?) ==================
def help_section():
    with st.expander("❓ Ajuda e explicações", expanded=False):
        st.markdown(
            """
            ### ℹ️ Guia rápido das seções
            
            - **🔎 Validador de RELATÓRIOS (Excel)**: módulo principal que lê os arquivos Excel enviados e executa diagnósticos por coluna (tipos, nulos, inválidos, etc.).
              
              📍 *Exemplo:* se uma coluna `REQUERIMENTO` tiver números e textos misturados, será sinalizado.

            - **Prévia Base A**: exibe as primeiras linhas da primeira aba do Excel. Serve para verificar se os dados foram carregados corretamente.

            - **Prévia Base B**: mostra outra aba (ou planilha secundária), útil para comparar dados ou validar integrações entre diferentes bases.
            
            - **Diagnóstico por Coluna**: apresenta os tipos detectados, % de nulos, % inválidos e notas de alerta.

            - **Análises de Datas**: compara datas de entrada/requerimento e publicação, destacando prazos e SLA.

            - **Tabela Paginada**: mostra os dados completos de forma fracionada para facilitar auditorias.

            - **Opções de Tema**: escolha entre **Claro** e **Escuro**, alterando também a logo.

            - **Modo Debug**: quando ativado, exibe logs detalhados e mensagens técnicas úteis para desenvolvedores.
            """
        )

help_section()

# (restante do código segue igual — diagnóstico, análises, exportações...)

st.success("✅ Versão com tema dinâmico, logo alternável e ajuda contextual incluída.")
