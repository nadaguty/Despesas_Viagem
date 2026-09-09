"""
database.py
------------
Camada de persistência da aplicação de Gestão de Despesas de Viagem.

Utiliza SQLAlchemy como ORM, o que permite trocar facilmente o banco de
dados de desenvolvimento (SQLite local) para um banco de produção
(PostgreSQL / Supabase) apenas alterando a variável de ambiente
DATABASE_URL — nenhuma linha de código de negócio precisa mudar.

Modelos:
    Participante     -> pessoas que participam da viagem
    Despesa          -> gasto realizado por um participante (pagador)
    RateioDespesa    -> como uma despesa é dividida entre os participantes
    Liquidacao       -> pagamentos de acerto de contas já realizados
"""

import os
from datetime import datetime, date

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, DateTime,
    ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

import streamlit as st

# ---------------------------------------------------------------------------
# Configuração de conexão
# ---------------------------------------------------------------------------
def _get_database_url() -> str:
    """Busca DATABASE_URL no st.secrets do Streamlit ou nas variáveis de ambiente."""
    try:
        if "DATABASE_URL" in st.secrets and st.secrets["DATABASE_URL"]:
            return str(st.secrets["DATABASE_URL"]).strip()
    except Exception:
        pass
    return os.getenv("DATABASE_URL", "sqlite:///viagem.db").strip()

DATABASE_URL = _get_database_url()

# Corrigir protocolo caso o provedor (Heroku/Supabase) forneça 'postgres://' ou 'postgresql://'
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# Parâmetros de conexão por dialeto
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # PostgreSQL na nuvem (Supabase, Neon, Render)
    connect_args = {"connect_timeout": 10}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,  # Reconecta conexões que caíram por inatividade
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class Participante(Base):
    __tablename__ = "participantes"

    id = Column(Integer, primary_key=True)
    nome = Column(String(80), nullable=False, unique=True)
    ativo = Column(Integer, default=1)  # 1 = ativo, 0 = removido (soft delete)

    despesas_pagas = relationship("Despesa", back_populates="pagador")
    rateios = relationship("RateioDespesa", back_populates="participante")


class Despesa(Base):
    __tablename__ = "despesas"

    id = Column(Integer, primary_key=True)
    data_gasto = Column(Date, nullable=False, default=date.today)
    descricao = Column(String(200), nullable=False)
    categoria = Column(String(50), nullable=False, default="Outros")
    valor_total = Column(Float, nullable=False)
    pagador_id = Column(Integer, ForeignKey("participantes.id"), nullable=False)
    tipo_divisao = Column(String(20), default="igualitaria")  # 'igualitaria' | 'customizada'
    criado_em = Column(DateTime, default=datetime.utcnow)

    pagador = relationship("Participante", back_populates="despesas_pagas")
    rateios = relationship(
        "RateioDespesa", back_populates="despesa",
        cascade="all, delete-orphan"
    )


class RateioDespesa(Base):
    """Define quanto cada participante consumiu de uma despesa específica."""
    __tablename__ = "rateios_despesa"

    id = Column(Integer, primary_key=True)
    despesa_id = Column(Integer, ForeignKey("despesas.id"), nullable=False)
    participante_id = Column(Integer, ForeignKey("participantes.id"), nullable=False)
    peso = Column(Float, default=1.0)                 # peso relativo na divisão
    valor_consumido = Column(Float, nullable=False)   # valor final já calculado (R$)

    despesa = relationship("Despesa", back_populates="rateios")
    participante = relationship("Participante", back_populates="rateios")


class Liquidacao(Base):
    """Registra pagamentos de acerto de contas (quitação de dívidas)."""
    __tablename__ = "liquidacoes"

    id = Column(Integer, primary_key=True)
    data_pagamento = Column(Date, nullable=False, default=date.today)
    pagador_id = Column(Integer, ForeignKey("participantes.id"), nullable=False)
    recebedor_id = Column(Integer, ForeignKey("participantes.id"), nullable=False)
    valor = Column(Float, nullable=False)
    observacao = Column(String(200), default="")
    criado_em = Column(DateTime, default=datetime.utcnow)

    pagador = relationship("Participante", foreign_keys=[pagador_id])
    recebedor = relationship("Participante", foreign_keys=[recebedor_id])


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------
def init_db(nomes_padrao=None):
    """Cria as tabelas (se não existirem) e garante 4 participantes padrão."""
    Base.metadata.create_all(engine)

    if nomes_padrao is None:
        nomes_padrao = ["Participante 1", "Participante 2", "Participante 3", "Participante 4"]

    session = SessionLocal()
    try:
        total = session.query(Participante).count()
        if total == 0:
            for nome in nomes_padrao:
                session.add(Participante(nome=nome))
            session.commit()
    finally:
        session.close()


def get_session():
    """Retorna uma nova sessão SQLAlchemy. Lembre de fechar após o uso."""
    return SessionLocal()


# ---------------------------------------------------------------------------
# CRUD - Participantes
# ---------------------------------------------------------------------------
def listar_participantes(somente_ativos=True):
    session = get_session()
    try:
        query = session.query(Participante)
        if somente_ativos:
            query = query.filter(Participante.ativo == 1)
        return query.order_by(Participante.id).all()
    finally:
        session.close()


def renomear_participante(participante_id, novo_nome):
    session = get_session()
    try:
        p = session.get(Participante, participante_id)
        if p:
            p.nome = novo_nome
            session.commit()
    finally:
        session.close()


def adicionar_participante(nome):
    """Permite expandir a viagem além de 4 participantes."""
    session = get_session()
    try:
        p = Participante(nome=nome)
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def remover_participante(participante_id):
    """Soft delete: mantém o histórico de despesas, apenas oculta da lista ativa."""
    session = get_session()
    try:
        p = session.get(Participante, participante_id)
        if p:
            p.ativo = 0
            session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CRUD - Despesas
# ---------------------------------------------------------------------------
def adicionar_despesa(data_gasto, descricao, categoria, valor_total,
                       pagador_id, tipo_divisao, rateios):
    """
    Cria uma despesa e seus rateios.

    rateios: lista de dicts [{'participante_id': int, 'peso': float}]
        - Para divisão igualitária, envie todos os participantes com peso=1.
        - Para divisão customizada, envie apenas quem participou daquele
          consumo, com o peso desejado (pesos iguais => divisão igual entre
          os selecionados; pesos diferentes => divisão proporcional ao peso).
    """
    session = get_session()
    try:
        despesa = Despesa(
            data_gasto=data_gasto,
            descricao=descricao,
            categoria=categoria,
            valor_total=valor_total,
            pagador_id=pagador_id,
            tipo_divisao=tipo_divisao,
        )
        session.add(despesa)
        session.flush()  # garante despesa.id disponível antes do commit

        soma_pesos = sum(r["peso"] for r in rateios)
        for r in rateios:
            valor_consumido = valor_total * (r["peso"] / soma_pesos)
            session.add(RateioDespesa(
                despesa_id=despesa.id,
                participante_id=r["participante_id"],
                peso=r["peso"],
                valor_consumido=round(valor_consumido, 2),
            ))
        session.commit()
        return despesa.id
    finally:
        session.close()


def excluir_despesa(despesa_id):
    session = get_session()
    try:
        despesa = session.get(Despesa, despesa_id)
        if despesa:
            session.delete(despesa)
            session.commit()
    finally:
        session.close()


def listar_despesas():
    """Retorna lista de despesas com pagador e rateios já carregados."""
    session = get_session()
    try:
        despesas = (
            session.query(Despesa)
            .order_by(Despesa.data_gasto.desc(), Despesa.id.desc())
            .all()
        )
        # Força o carregamento dos relacionamentos antes de fechar a sessão
        for d in despesas:
            _ = d.pagador.nome
            for r in d.rateios:
                _ = r.participante.nome
        return despesas
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CRUD - Liquidações
# ---------------------------------------------------------------------------
def registrar_liquidacao(pagador_id, recebedor_id, valor, data_pagamento=None, observacao=""):
    session = get_session()
    try:
        liquidacao = Liquidacao(
            pagador_id=pagador_id,
            recebedor_id=recebedor_id,
            valor=valor,
            data_pagamento=data_pagamento or date.today(),
            observacao=observacao,
        )
        session.add(liquidacao)
        session.commit()
        return liquidacao.id
    finally:
        session.close()


def listar_liquidacoes():
    session = get_session()
    try:
        liquidacoes = (
            session.query(Liquidacao)
            .order_by(Liquidacao.data_pagamento.desc(), Liquidacao.id.desc())
            .all()
        )
        for l in liquidacoes:
            _ = l.pagador.nome
            _ = l.recebedor.nome
        return liquidacoes
    finally:
        session.close()


def excluir_liquidacao(liquidacao_id):
    session = get_session()
    try:
        liq = session.get(Liquidacao, liquidacao_id)
        if liq:
            session.delete(liq)
            session.commit()
    finally:
        session.close()
