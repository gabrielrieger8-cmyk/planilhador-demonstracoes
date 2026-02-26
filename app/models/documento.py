"""Modelo ORM para a tabela documentos."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    String,
    Text,
    TypeDecorator,
    func,
)
from sqlalchemy.orm import relationship

from app.models.database import Base


class JSONType(TypeDecorator):
    """Tipo JSON portável: usa JSONB no PostgreSQL, TEXT+json no SQLite."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value, ensure_ascii=False)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value


class Documento(Base):
    __tablename__ = "documentos"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nome_arquivo = Column(String(255), nullable=False)
    tipo_documento = Column(String(100))
    empresa = Column(String(255))
    periodo_referencia = Column(String(20))
    data_upload = Column(DateTime, server_default=func.now())
    status = Column(String(20), default="processando")
    dados_json = Column(JSONType)
    validacao_ok = Column(Boolean)
    observacoes = Column(Text)
    custo_api_usd = Column(Float, default=0.0)

    contas = relationship(
        "ContaContabil",
        back_populates="documento",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "nome_arquivo": self.nome_arquivo,
            "tipo_documento": self.tipo_documento,
            "empresa": self.empresa,
            "periodo_referencia": self.periodo_referencia,
            "data_upload": self.data_upload.isoformat() if self.data_upload else None,
            "status": self.status,
            "validacao_ok": self.validacao_ok,
            "observacoes": self.observacoes,
            "custo_api_usd": self.custo_api_usd,
        }
