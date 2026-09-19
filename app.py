"""
app.py
------
Aplicação Streamlit para gestão e liquidação de despesas compartilhadas
de viagem entre participantes (4 por padrão, expansível).

Abas:
    1. Participantes    -> cadastro / renomeação / adicionar mais gente
    2. Nova Despesa      -> lançar gastos com divisão igual ou customizada
    3. Painel Financeiro -> saldos individuais + algoritmo de acerto
    4. Liquidações       -> registrar pagamentos já feitos entre as pessoas
    5. Histórico/Exportar -> extrato completo + exportação CSV/Excel

Execute com:
    streamlit run app.py
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

import database as db
import settlement as calc
import importlib
importlib.reload(calc)

CATEGORIAS = ["Hospedagem", "Alimentação", "Transporte", "Lazer", "Outros"]

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Divisão de Despesas da Viagem",
    page_icon="🧳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# CSS leve para deixar os cards mais bonitos e a UI mobile-friendly
st.markdown("""
<style>
    .stApp { max-width: 1100px; margin: 0 auto; }
    div[data-testid="stMetric"] {
        background-color: rgba(148, 163, 184, 0.08);
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 12px;
        padding: 14px 16px 8px 16px;
    }
    .transacao-card {
        background-color: rgba(34, 197, 94, 0.08);
        border: 1px solid rgba(34, 197, 94, 0.35);
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 10px;
        font-size: 1.02rem;
    }
    .transacao-card b { color: inherit; }
    @media (max-width: 640px) {
        div[data-testid="column"] { min-width: 100% !important; }
    }
</style>
""", unsafe_allow_html=True)

db.init_db()

st.title("🧳 Divisão de Despesas da Viagem")
st.caption("Cadastre gastos, acompanhe quem deve para quem e feche as contas sem dor de cabeça.")

aba_participantes, aba_despesa, aba_painel, aba_liquidacao, aba_historico = st.tabs(
    ["👥 Participantes", "➕ Nova Despesa", "📊 Painel Financeiro", "✅ Liquidações", "📁 Histórico / Exportar"]
)

# ===========================================================================
# ABA 1 — PARTICIPANTES
# ===========================================================================
with aba_participantes:
    st.subheader("Participantes da viagem")
    participantes = db.listar_participantes()

    cols = st.columns(2)
    for idx, p in enumerate(participantes):
        with cols[idx % 2]:
            with st.form(key=f"form_rename_{p.id}", clear_on_submit=False):
                novo_nome = st.text_input(f"Nome do participante #{idx + 1}", value=p.nome)
                salvar = st.form_submit_button("Salvar nome")
                if salvar and novo_nome.strip() and novo_nome.strip() != p.nome:
                    db.renomear_participante(p.id, novo_nome.strip())
                    st.success(f"Atualizado para '{novo_nome.strip()}'")
                    st.rerun()

    st.divider()
    with st.expander("➕ Adicionar mais um participante (expandir além de 4)"):
        with st.form("form_add_participante", clear_on_submit=True):
            nome_novo = st.text_input("Nome do novo participante")
            add = st.form_submit_button("Adicionar")
            if add:
                if not nome_novo.strip():
                    st.warning("Digite um nome válido.")
                else:
                    db.adicionar_participante(nome_novo.strip())
                    st.success(f"'{nome_novo.strip()}' adicionado à viagem!")
                    st.rerun()

    if len(participantes) > 2:
        with st.expander("🗑️ Remover participante"):
            nomes_map = {p.nome: p.id for p in participantes}
            escolhido = st.selectbox("Selecione quem remover", list(nomes_map.keys()), key="remover_select")
            st.caption("O histórico de despesas dessa pessoa é preservado; ela só deixa de aparecer nas listas.")
            if st.button("Remover participante", type="secondary"):
                db.remover_participante(nomes_map[escolhido])
                st.success("Participante removido.")
                st.rerun()

# ===========================================================================
# ABA 2 — NOVA DESPESA
# ===========================================================================
with aba_despesa:
    st.subheader("Registrar nova despesa")

    if st.session_state.pop("limpar_campos_despesa", False):
        st.session_state["despesa_desc"] = ""
        st.session_state["despesa_valor"] = 0.0

    if "sucesso_despesa" in st.session_state:
        msg_sucesso = st.session_state.pop("sucesso_despesa")
        st.success(msg_sucesso)
        st.toast(msg_sucesso, icon="🎉")

    participantes = db.listar_participantes()

    if len(participantes) < 2:
        st.warning("Cadastre pelo menos 2 participantes antes de lançar despesas.")
    else:
        nomes_map = {p.nome: p.id for p in participantes}

        col1, col2 = st.columns(2)
        with col1:
            data_gasto = st.date_input("Data do gasto", value=date.today())
            descricao = st.text_input(
                "Descrição da despesa",
                placeholder="Ex.: Jantar no restaurante X",
                key="despesa_desc",
            )
        with col2:
            categoria = st.selectbox("Categoria", CATEGORIAS)
            valor_total = st.number_input(
                "Valor total (R$)",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key="despesa_valor",
            )

        pagador_nome = st.selectbox("Quem pagou?", list(nomes_map.keys()))

        tipo_divisao = st.radio(
            "Como dividir esse gasto?",
            ["Igualitária (entre todos)", "Customizada (selecionar quem participou)"],
            horizontal=True,
        )

        rateios_input = []

        if tipo_divisao.startswith("Igualitária"):
            st.caption(f"Será dividido igualmente entre os {len(participantes)} participantes.")
            rateios_input = [{"participante_id": p.id, "peso": 1.0} for p in participantes]
        else:
            selecionados = st.multiselect(
                "Quem participou desse consumo específico?",
                list(nomes_map.keys()),
                default=list(nomes_map.keys()),
            )
            if selecionados:
                st.caption("Ajuste o peso de cada um se a divisão não for igual (padrão = 1 para todos).")
                peso_cols = st.columns(min(len(selecionados), 4))
                pesos = {}
                for i, nome in enumerate(selecionados):
                    with peso_cols[i % len(peso_cols)]:
                        pesos[nome] = st.number_input(
                            f"Peso — {nome}", min_value=0.0, value=1.0, step=0.5, key=f"peso_{nome}"
                        )
                rateios_input = [
                    {"participante_id": nomes_map[nome], "peso": pesos[nome]}
                    for nome in selecionados if pesos[nome] > 0
                ]

        st.markdown("")
        if st.button("💾 Salvar despesa", type="primary", use_container_width=True):
            if not descricao.strip():
                st.error("Informe uma descrição para a despesa.")
            elif valor_total <= 0:
                st.error("O valor total deve ser maior que zero.")
            elif not rateios_input:
                st.error("Selecione ao menos um participante na divisão.")
            else:
                tipo_salvo = "igualitaria" if tipo_divisao.startswith("Igualitária") else "customizada"
                db.adicionar_despesa(
                    data_gasto=data_gasto,
                    descricao=descricao.strip(),
                    categoria=categoria,
                    valor_total=valor_total,
                    pagador_id=nomes_map[pagador_nome],
                    tipo_divisao=tipo_salvo,
                    rateios=rateios_input,
                )
                st.session_state["sucesso_despesa"] = (
                    f"✅ Despesa '{descricao.strip()}' no valor de R$ {valor_total:,.2f} salva com sucesso!"
                )
                st.session_state["limpar_campos_despesa"] = True
                st.rerun()

# ===========================================================================
# ABA 3 — PAINEL FINANCEIRO & ACERTO DE CONTAS
# ===========================================================================
with aba_painel:
    st.subheader("Painel financeiro")

    participantes = db.listar_participantes()
    despesas = db.listar_despesas()
    liquidacoes = db.listar_liquidacoes()

    if not participantes:
        st.info("Cadastre participantes para ver o painel financeiro.")
    else:
        df_balancos = calc.calcular_balancos(participantes, despesas, liquidacoes)

        if despesas:
            total_viagem = sum(d.valor_total for d in despesas)
            st.metric("💰 Total gasto na viagem", f"R$ {total_viagem:,.2f}")

        st.markdown("#### Saldo individual")
        cols = st.columns(len(df_balancos)) if len(df_balancos) <= 4 else st.columns(4)
        for idx, row in df_balancos.iterrows():
            col = cols[idx % len(cols)]
            with col:
                if row["status"] == "A Receber":
                    delta_color = "normal"
                elif row["status"] == "A Pagar":
                    delta_color = "inverse"
                else:
                    delta_color = "off"
                st.metric(
                    label=f"{row['nome']} — {row['status']}",
                    value=f"R$ {row['saldo_final']:,.2f}",
                    delta=f"Pagou R$ {row['total_pago']:,.2f} / Consumiu R$ {row['total_consumido']:,.2f}",
                    delta_color=delta_color,
                )

        st.markdown("#### Tabela detalhada")
        df_exibicao = df_balancos.rename(columns={
            "nome": "Participante",
            "total_pago": "Total Pago (R$)",
            "total_consumido": "Cota-parte Consumida (R$)",
            "saldo_bruto": "Saldo Bruto (R$)",
            "ajuste_liquidacoes": "Ajuste Liquidações (R$)",
            "saldo_final": "Saldo Líquido (R$)",
            "status": "Status",
        })[[
            "Participante", "Total Pago (R$)", "Cota-parte Consumida (R$)",
            "Saldo Bruto (R$)", "Ajuste Liquidações (R$)", "Saldo Líquido (R$)", "Status"
        ]]
        st.dataframe(
            df_exibicao.style.format({
                "Total Pago (R$)": "R$ {:,.2f}",
                "Cota-parte Consumida (R$)": "R$ {:,.2f}",
                "Saldo Bruto (R$)": "R$ {:,.2f}",
                "Ajuste Liquidações (R$)": "R$ {:,.2f}",
                "Saldo Líquido (R$)": "R$ {:,.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("#### 🔄 Acerto de contas — quem deve pagar quem")

        modo_acerto = st.radio(
            "Selecione a lógica de acerto de contas:",
            options=[
                "⚡ Otimizado / Simplificado (Menor número de transferências)",
                "📜 Direto por Despesa (Quem pagou cada gasto recebe direto)",
            ],
            index=0,
            key="modo_acerto_select",
            help="Alterne entre o modo que reduz a quantidade de Pixs e o modo direto despesa por despesa."
        )

        with st.expander("💡 Entenda a diferença entre os 2 modos de acerto de contas"):
            st.markdown("""
            **⚡ 1. Modo Otimizado / Simplificado (Recomendado):**
            * **Como funciona:** Consolida todas as contas da viagem e ajusta os saldos finais de cada pessoa.
            * **Vantagem:** Elimina a **triangulação de dinheiro** (quando a pessoa A paga a B para a B repassar a C).
            * **Exemplo:** Se o Pandolf deve R$ 300 para o Vitor, mas o Vitor deve R$ 300 para o Gustavo, o Pandolf faz o Pix de R$ 300 direto para o Gustavo. O número de transações é o **mínimo possível**, e no final **todos recebem/pagam os mesmos valores exatos**!

            ---

            **📜 2. Modo Direto por Despesa:**
            * **Como funciona:** Calcula a dívida direta considerando **exclusivamente quem colocou a mão no bolso para pagar cada gasto individual**.
            * **Ideal para:** Quando os participantes preferem acertar diretamente com quem fez os pagamentos das despesas específicas em que participaram, sem compensação cruzada entre outros gastos.
            """)

        if modo_acerto.startswith("⚡") or not hasattr(calc, "calcular_dividas_diretas"):
            transacoes = calc.simplificar_dividas(df_balancos)
        else:
            transacoes = calc.calcular_dividas_diretas(participantes, despesas, liquidacoes)

        if not transacoes:
            st.success("✅ Todas as contas já estão quitadas! Ninguém deve nada a ninguém.")
        else:
            for t in transacoes:
                st.markdown(
                    f"""<div class="transacao-card">
                        💸 <b>{t['de']}</b> deve pagar <b>R$ {t['valor']:,.2f}</b>
                        para <b>{t['para']}</b> via Pix
                    </div>""",
                    unsafe_allow_html=True,
                )

            with st.expander("Registrar uma dessas transações como já paga"):
                opcoes = [f"{t['de']} → {t['para']} (R$ {t['valor']:,.2f})" for t in transacoes]
                escolha = st.selectbox("Selecione a transação", opcoes)
                idx_escolha = opcoes.index(escolha)
                t_escolhida = transacoes[idx_escolha]
                data_pgto = st.date_input("Data do pagamento", value=date.today(), key="data_pgto_rapido")
                if st.button("✅ Marcar como liquidado", type="primary"):
                    nomes_map = {p.nome: p.id for p in participantes}
                    db.registrar_liquidacao(
                        pagador_id=nomes_map[t_escolhida["de"]],
                        recebedor_id=nomes_map[t_escolhida["para"]],
                        valor=t_escolhida["valor"],
                        data_pagamento=data_pgto,
                        observacao="Registrado via Painel Financeiro",
                    )
                    st.success("Liquidação registrada! O balanço foi recalculado.")
                    st.rerun()

# ===========================================================================
# ABA 4 — LIQUIDAÇÕES
# ===========================================================================
with aba_liquidacao:
    st.subheader("Controle de liquidações (pagamentos efetuados)")
    participantes = db.listar_participantes()

    if len(participantes) < 2:
        st.info("Cadastre pelo menos 2 participantes para registrar liquidações.")
    else:
        nomes_map = {p.nome: p.id for p in participantes}

        col1, col2 = st.columns(2)
        with col1:
            pagador_nome = st.selectbox("Quem pagou (Pagador)", list(nomes_map.keys()), key="liq_pagador")
        with col2:
            opcoes_recebedor = [n for n in nomes_map if n != pagador_nome]
            recebedor_nome = st.selectbox("Quem recebeu (Recebedor)", opcoes_recebedor, key="liq_recebedor")

        with st.form("form_liquidacao", clear_on_submit=True):
            valor_liq = st.number_input("Valor pago (R$)", min_value=0.0, step=0.01, format="%.2f")
            data_liq = st.date_input("Data do pagamento", value=date.today(), key="liq_data")
            obs = st.text_input("Observação (opcional)", placeholder="Ex.: Pix transferido dia X")

            registrar = st.form_submit_button("✅ Registrar liquidação", type="primary")
            if registrar:
                if valor_liq <= 0:
                    st.error("Informe um valor maior que zero.")
                else:
                    db.registrar_liquidacao(
                        pagador_id=nomes_map[pagador_nome],
                        recebedor_id=nomes_map[recebedor_nome],
                        valor=valor_liq,
                        data_pagamento=data_liq,
                        observacao=obs,
                    )
                    st.success("Liquidação registrada e balanço recalculado!")
                    st.rerun()

        st.divider()
        st.markdown("#### Liquidações já registradas")
        liquidacoes = db.listar_liquidacoes()
        if not liquidacoes:
            st.caption("Nenhuma liquidação registrada ainda.")
        else:
            for liq in liquidacoes:
                col_txt, col_btn = st.columns([5, 1])
                with col_txt:
                    st.markdown(
                        f"🗓️ **{liq.data_pagamento}** — {liq.pagador.nome} pagou "
                        f"**R$ {liq.valor:,.2f}** para {liq.recebedor.nome}"
                        + (f" · _{liq.observacao}_" if liq.observacao else "")
                    )
                with col_btn:
                    if st.button("Excluir", key=f"del_liq_{liq.id}"):
                        db.excluir_liquidacao(liq.id)
                        st.rerun()

# ===========================================================================
# ABA 5 — HISTÓRICO / EXPORTAÇÃO
# ===========================================================================
with aba_historico:
    st.subheader("Histórico de despesas")
    despesas = db.listar_despesas()

    if not despesas:
        st.info("Nenhuma despesa registrada ainda.")
    else:
        linhas_extrato = []
        for d in despesas:
            for r in d.rateios:
                linhas_extrato.append({
                    "Data": d.data_gasto,
                    "Descrição": d.descricao,
                    "Categoria": d.categoria,
                    "Valor Total (R$)": d.valor_total,
                    "Pago por": d.pagador.nome,
                    "Tipo de Divisão": d.tipo_divisao,
                    "Participante do Rateio": r.participante.nome,
                    "Peso": r.peso,
                    "Valor Consumido (R$)": r.valor_consumido,
                })
        df_extrato = pd.DataFrame(linhas_extrato)

        st.dataframe(df_extrato, use_container_width=True, hide_index=True)

        for d in despesas:
            col_txt, col_btn = st.columns([5, 1])
            with col_txt:
                st.caption(f"{d.data_gasto} · {d.descricao} · R$ {d.valor_total:,.2f} ({d.categoria})")
            with col_btn:
                if st.button("Excluir despesa", key=f"del_desp_{d.id}"):
                    db.excluir_despesa(d.id)
                    st.rerun()

        st.divider()
        st.markdown("#### 📤 Exportar relatório")

        participantes = db.listar_participantes()
        liquidacoes = db.listar_liquidacoes()
        df_balancos = calc.calcular_balancos(participantes, despesas, liquidacoes)
        transacoes = calc.simplificar_dividas(df_balancos)
        df_transacoes = pd.DataFrame(transacoes) if transacoes else pd.DataFrame(
            columns=["de", "para", "valor"]
        )

        col_csv, col_xlsx = st.columns(2)

        with col_csv:
            csv_bytes = df_extrato.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ Baixar extrato em CSV",
                data=csv_bytes,
                file_name="extrato_despesas_viagem.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with col_xlsx:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_extrato.to_excel(writer, sheet_name="Extrato de Despesas", index=False)
                df_balancos.to_excel(writer, sheet_name="Balanço Individual", index=False)
                df_transacoes.to_excel(writer, sheet_name="Acerto de Contas", index=False)
            st.download_button(
                "⬇️ Baixar relatório completo em Excel",
                data=buffer.getvalue(),
                file_name="relatorio_viagem.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
