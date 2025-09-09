from sqlalchemy.orm import Session
from models import Cliente, Observacion
import models

def get_clientes(db: Session):
    return db.query(Cliente).all()

def get_cliente(db: Session, cliente_id: int):
    return db.query(Cliente).filter(Cliente.id == cliente_id).first()

def create_cliente(db: Session, data: dict):
    cliente = Cliente(**data)
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente

# def update_cliente(db: Session, cliente_id: int, data: dict):
#     cliente = get_cliente(db, cliente_id)
#     for key, value in data.items():
#         setattr(cliente, key, value)
#     db.commit()
#     db.refresh(cliente)
#     return cliente
def update_cliente(db: Session, cliente_id: int, data: dict):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return None
    for key, value in data.items():
        setattr(cliente, key, value)
    db.commit()
    db.refresh(cliente)
    return cliente

def delete_cliente(db: Session, cliente_id: int):
    cliente = get_cliente(db, cliente_id)
    db.delete(cliente)
    db.commit()

def add_observacion(db: Session, cliente_id: int, texto: str):
    obs = Observacion(cliente_id=cliente_id, texto=texto)
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs

def get_historial_cliente(db, cliente_id):
    return db.query(models.Observacion).filter(models.Observacion.cliente_id == cliente_id).all()

def get_next_cliente_id(db: Session, current_id: int):
    next_cliente = db.query(Cliente).filter(Cliente.id > current_id).order_by(Cliente.id.asc()).first()
    return next_cliente.id if next_cliente else None

def get_prev_cliente_id(db: Session, current_id: int):
    prev_cliente = db.query(Cliente).filter(Cliente.id < current_id).order_by(Cliente.id.desc()).first()
    return prev_cliente.id if prev_cliente else None