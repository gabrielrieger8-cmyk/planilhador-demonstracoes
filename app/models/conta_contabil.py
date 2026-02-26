"""Modelo ORM para a tabela contas_contabeis."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.models.database import Base


class ContaContabil(Base):
    __tablename__ = "contas_contabeis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    documento_id = Column(
        String(36), ForeignKey("documentos.id"), nullable=False, index=True
    )
    codigo_conta = Column(String(20))
    descricao = Column(String(255))
    nivel = Column(Integer)
    natureza = Column(String(1))  # D ou C
    saldo_anterior = Column(Numeric(15, 2))
    debitos = Column(Numeric(15, 2))
    creditos = Column(Numeric(15, 2))
    saldo_atual = Column(Numeric(15, 2))

    documento = relationship("Documento", back_populates="contas")
