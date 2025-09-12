from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, DateTime, Float, func
from sqlalchemy.orm import relationship
from database import Base

class Cliente(Base):
    __tablename__ = "cartera"

    id = Column(Integer, primary_key=True, index=True)
    razon_social = Column(String(255))
    nit_cliente = Column(String(50))
    nro_docto_cruce = Column(String(100))
    dias_vencidos = Column(Integer)
    fecha_docto = Column(Date)
    fecha_vcto = Column(Date)
    valor_docto = Column(Float)       # Valor inicial de la factura
    total_cop = Column(Float)  
    telefono = Column(String(50))
    celular = Column(String(50))
    asesor = Column(String(100))
    fecha_gestion = Column(Date)
    tipo = Column(String(100))

    observaciones = relationship("Observacion", back_populates="cliente", cascade="all, delete")
    abonos = relationship("Abono", back_populates="cliente", cascade="all, delete")

    @property
    def recaudo(self):
        """Suma total de abonos"""
        return sum(ab.valor for ab in self.abonos)

    @property
    def saldo(self):
        """Saldo pendiente (valor_docto - recaudo)"""
        return (self.valor_docto or 0) - self.recaudo


class Observacion(Base):
    __tablename__ = "observaciones"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("cartera.id"))
    texto = Column(Text)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    cliente = relationship("Cliente", back_populates="observaciones")


class Abono(Base):
    __tablename__ = "abonos"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("cartera.id"))
    valor = Column(Float, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    cliente = relationship("Cliente", back_populates="abonos")


# from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, DateTime, func
# from sqlalchemy.orm import relationship
# from database import Base

# class Cliente(Base):
#     __tablename__ = "cartera"

#     id = Column(Integer, primary_key=True, index=True)
#     razon_social = Column(String(255))
#     nit_cliente = Column(String(50))
#     nro_docto_cruce = Column(String(100))
#     dias_vencidos = Column(Integer)
#     fecha_docto = Column(Date)
#     fecha_vcto = Column(Date)
#     total_cop = Column(String(50))
#     recaudo = Column(String(50))
#     telefono = Column(String(50))
#     celular = Column(String(50))
#     asesor = Column(String(100))
#     fecha_gestion = Column(Date)
#     tipo = Column(String(100))

#     observaciones = relationship("Observacion", back_populates="cliente", cascade="all, delete")


# class Observacion(Base):
#     __tablename__ = "observaciones"

#     id = Column(Integer, primary_key=True, index=True)
#     cliente_id = Column(Integer, ForeignKey("cartera.id"))
#     texto = Column(Text)

#     # 👉 Nuevo campo de fecha y hora de creación
#     fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

#     cliente = relationship("Cliente", back_populates="observaciones")
