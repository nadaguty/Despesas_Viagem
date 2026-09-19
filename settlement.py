"""
settlement.py
-------------
Regras de negócio para cálculo de saldos e simplificação de dívidas
(o "acerto de contas" da viagem).

Contém duas responsabilidades principais:

1. calcular_balancos(...)
   Consolida, para cada participante:
     - total pago (quanto ele desembolsou nas despesas)
     - total consumido (sua cota-parte real, considerando os rateios)
     - saldo bruto = pago - consumido
     - ajuste de liquidações já realizadas
     - saldo final = saldo bruto + ajuste de liquidações

2. simplificar_dividas(...)
   Implementa o algoritmo clássico de "Minimum Cash Flow" (também
   conhecido como Greedy Two-Pointer Debt Simplification):
     - Ordena devedores (saldo negativo) e credores (saldo positivo).
     - A cada passo, casa o MAIOR devedor com o MAIOR credor e transfere
       o menor valor entre as duas pontas: min(dívida, crédito).
     - Isso zera pelo menos uma das pontas a cada iteração, minimizando
       o número de transações necessárias para fechar o acerto de contas
       (bem menos transações do que fazer "todos pagam todos").
"""

from collections import defaultdict

import pandas as pd

TOLERANCIA = 0.01  # evita ruído de ponto flutuante (ex.: R$ 0,004 residual)


def calcular_balancos(participantes, despesas, liquidacoes):
    """
    Calcula o balanço financeiro de cada participante.

    Args:
        participantes: lista de objetos Participante (ativos)
        despesas: lista de objetos Despesa (com .rateios já carregados)
        liquidacoes: lista de objetos Liquidacao já registradas

    Returns:
        pandas.DataFrame com colunas:
            participante_id, nome, total_pago, total_consumido,
            saldo_bruto, ajuste_liquidacoes, saldo_final, status
    """
    total_pago = defaultdict(float)
    total_consumido = defaultdict(float)

    for despesa in despesas:
        total_pago[despesa.pagador_id] += despesa.valor_total
        for rateio in despesa.rateios:
            total_consumido[rateio.participante_id] += rateio.valor_consumido

    # Ajuste de liquidações: quando A já pagou B fora do app (ex.: via Pix),
    # isso "quita" parte da dívida de A e reduz o crédito pendente de B.
    ajuste = defaultdict(float)
    for liq in liquidacoes:
        ajuste[liq.pagador_id] += liq.valor      # quem pagou melhora seu saldo
        ajuste[liq.recebedor_id] -= liq.valor    # quem recebeu já foi compensado

    linhas = []
    for p in participantes:
        pago = round(total_pago.get(p.id, 0.0), 2)
        consumido = round(total_consumido.get(p.id, 0.0), 2)
        saldo_bruto = round(pago - consumido, 2)
        ajuste_liq = round(ajuste.get(p.id, 0.0), 2)
        saldo_final = round(saldo_bruto + ajuste_liq, 2)

        if saldo_final > TOLERANCIA:
            status = "A Receber"
        elif saldo_final < -TOLERANCIA:
            status = "A Pagar"
        else:
            status = "Quitado"

        linhas.append({
            "participante_id": p.id,
            "nome": p.nome,
            "total_pago": pago,
            "total_consumido": consumido,
            "saldo_bruto": saldo_bruto,
            "ajuste_liquidacoes": ajuste_liq,
            "saldo_final": saldo_final,
            "status": status,
        })

    return pd.DataFrame(linhas)


def simplificar_dividas(df_balancos, tolerancia=TOLERANCIA):
    """
    Algoritmo de simplificação de dívidas (Minimum Cash Flow - Greedy).

    Recebe o DataFrame retornado por calcular_balancos e devolve a lista
    gulosa (greedy) de transações necessárias para zerar todos os saldos,
    utilizando a técnica de dois ponteiros sobre listas ordenadas.

    Passo a passo do algoritmo:
        1. Separe os participantes em duas listas: credores (saldo > 0,
           "a receber") e devedores (saldo < 0, "a pagar").
        2. Ordene cada lista da maior para a menor magnitude de saldo.
        3. Use um ponteiro `i` para o maior devedor restante e um ponteiro
           `j` para o maior credor restante.
        4. Transfira o valor min(dívida_do_devedor, crédito_do_credor) do
           devedor para o credor — essa é a transação da vez.
        5. Subtraia o valor transferido dos dois lados. Sempre que o saldo
           de uma ponta chegar a zero, avance o ponteiro correspondente
           para o próximo da fila.
        6. Repita até que todos os devedores (ou credores) tenham sido
           processados — nesse ponto todos os saldos estarão zerados.

    Args:
        df_balancos: DataFrame com colunas 'nome' e 'saldo_final'
        tolerancia: valores absolutos abaixo disso são tratados como zero

    Returns:
        list[dict]: [{'de': str, 'para': str, 'valor': float}, ...]
    """
    # 1) Separa credores (saldo > 0) e devedores (saldo < 0)
    credores = [
        [row["nome"], row["saldo_final"]]
        for _, row in df_balancos.iterrows()
        if row["saldo_final"] > tolerancia
    ]
    devedores = [
        [row["nome"], -row["saldo_final"]]  # guarda como valor positivo devido
        for _, row in df_balancos.iterrows()
        if row["saldo_final"] < -tolerancia
    ]

    # 2) Ordena da maior para a menor magnitude (a ponta "mais cheia" primeiro)
    credores.sort(key=lambda x: x[1], reverse=True)
    devedores.sort(key=lambda x: x[1], reverse=True)

    transacoes = []
    i, j = 0, 0  # ponteiro do devedor / ponteiro do credor

    # 3) Percorre com dois ponteiros: a cada iteração, casa o maior devedor
    #    com o maior credor restante e transfere o menor valor entre eles.
    #    Quem "zerar" primeiro avança seu ponteiro para o próximo da fila.
    while i < len(devedores) and j < len(credores):
        nome_devedor, valor_devido = devedores[i]
        nome_credor, valor_credito = credores[j]

        valor_transferido = round(min(valor_devido, valor_credito), 2)

        if valor_transferido > tolerancia:
            transacoes.append({
                "de": nome_devedor,
                "para": nome_credor,
                "valor": valor_transferido,
            })

        devedores[i][1] = round(devedores[i][1] - valor_transferido, 2)
        credores[j][1] = round(credores[j][1] - valor_transferido, 2)

        if devedores[i][1] <= tolerancia:
            i += 1
        if credores[j][1] <= tolerancia:
            j += 1

    return transacoes


def calcular_dividas_diretas(participantes, despesas, liquidacoes, tolerancia=TOLERANCIA):
    """
    Calcula as dívidas diretas par-a-par entre os participantes, sem a simplificação
    multilateral de compensação de dívidas.

    Para cada par de pessoas (A, B):
    - Acumula quanto B consumiu de despesas que A pagou.
    - Abate pagamentos de liquidação já realizados.
    - Faz a compensação bilateral líquida direta entre A e B.

    Returns:
        list[dict]: [{'de': str, 'para': str, 'valor': float}, ...]
    """
    matriz = defaultdict(lambda: defaultdict(float))
    nome_map = {p.id: p.nome for p in participantes}

    # 1. Mapeia despesas: consumidor deve ao pagador
    for d in despesas:
        pagador_id = d.pagador_id
        for r in d.rateios:
            consumidor_id = r.participante_id
            if consumidor_id != pagador_id:
                matriz[consumidor_id][pagador_id] += r.valor_consumido

    # 2. Mapeia liquidações já efetuadas: liq.pagador pagou liq.recebedor
    for l in liquidacoes:
        matriz[l.pagador_id][l.recebedor_id] -= l.valor

    # 3. Consolidação bilateral entre todos os pares
    transacoes = []
    p_ids = list(nome_map.keys())

    for i in range(len(p_ids)):
        for j in range(i + 1, len(p_ids)):
            id1 = p_ids[i]
            id2 = p_ids[j]

            divida_1_para_2 = matriz[id1][id2]
            divida_2_para_1 = matriz[id2][id1]

            saldo_net = round(divida_1_para_2 - divida_2_para_1, 2)

            if saldo_net > tolerancia:
                transacoes.append({
                    "de": nome_map[id1],
                    "para": nome_map[id2],
                    "valor": saldo_net,
                })
            elif saldo_net < -tolerancia:
                transacoes.append({
                    "de": nome_map[id2],
                    "para": nome_map[id1],
                    "valor": round(-saldo_net, 2),
                })

    # Ordena por valor decrescente
    transacoes.sort(key=lambda x: x["valor"], reverse=True)
    return transacoes
