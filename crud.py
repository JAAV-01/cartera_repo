from sqlalchemy.orm import Session
from models import Cliente, Observacion


# -------------------
# CRUD Cliente
# -------------------

def get_cliente(db: Session, cliente_id: int):
    return db.query(Cliente).filter(Cliente.id == cliente_id).first()


def get_cliente_by_nit(db: Session, nit_cliente: str):
    return db.query(Cliente).filter(Cliente.nit_cliente == nit_cliente).first()


def get_clientes(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Cliente).offset(skip).limit(limit).all()


def create_cliente(db: Session, cliente: Cliente):
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


def update_recaudo(db: Session, cliente_id: int, monto: float):
    cliente = get_cliente(db, cliente_id)
    if cliente:
        cliente.recaudo += monto
        cliente.total_cop = cliente.valor_docto - cliente.recaudo
        db.commit()
        db.refresh(cliente)
    return cliente


# -------------------
# CRUD Observacion
# -------------------

def get_observaciones(db: Session, cliente_id: int):
    return db.query(Observacion).filter(Observacion.cliente_id == cliente_id).all()


def create_observacion(db: Session, cliente_id: int, texto: str):
    observacion = Observacion(cliente_id=cliente_id, texto=texto)
    db.add(observacion)
    db.commit()
    db.refresh(observacion)
    return observacion




# from sqlalchemy.orm import Session
# from models import Cliente, Observacion
# from sqlalchemy.orm import Session
# import models
# from typing import Dict, Any
# from typing import Dict, Any


# def create_abono(db: Session, cliente_id: int, valor: float) -> models.Abono:
#     """Crea y guarda un nuevo abono para un cliente."""
#     db_abono = models.Abono(cliente_id=cliente_id, valor=valor)
#     db.add(db_abono)
#     db.commit()
#     db.refresh(db_abono)
#     return db_abono
# # ======================
# # HELPER PARA FILTRAR COLUMNAS
# # ======================

# def filter_data_for_model(data: dict, model):
#     model_columns = {c.name for c in model.__table__.columns}
#     return {k: v for k, v in data.items() if k in model_columns}

# # ======================
# # CLIENTES
# # ======================

# def get_clientes(db: Session):
#     return db.query(Cliente).all()


# def get_cliente(db: Session, cliente_id: int):
#     return db.query(Cliente).filter(Cliente.id == cliente_id).first()


# def create_cliente(db: Session, data: dict):
#     data = filter_data_for_model(data, Cliente)

#     # Forzar nit_cliente a string
#     if "nit_cliente" in data and data["nit_cliente"] is not None:
#         data["nit_cliente"] = str(data["nit_cliente"])

#     valor_docto = float(data.get("valor_docto", 0) or 0)
#     recaudo = float(data.get("recaudo", 0) or 0)
#     total_cop = valor_docto - recaudo

#     data["valor_docto"] = valor_docto
#     data["recaudo"] = recaudo
#     data["total_cop"] = total_cop

#     cliente = Cliente(**data)
#     db.add(cliente)
#     db.commit()
#     db.refresh(cliente)
#     return cliente





# def delete_cliente(db: Session, cliente_id: int):
#     cliente = get_cliente(db, cliente_id)
#     if cliente:
#         db.delete(cliente)
#         db.commit()


# # En crud.py

# def update_cliente_full(db: Session, db_cliente: models.Cliente, update_data: Dict[str, Any]):
#     """
#     Actualiza los campos de un cliente, manejando la lógica de cada uno.
#     """
#     # Maneja la actualización del teléfono
#     telefono_nuevo = update_data.get("telefono")
#     print(f"DEBUG: El valor recibido para teléfono es: {telefono_nuevo}") # <-- Nueva línea de depuración
    
#     if telefono_nuevo is not None:
#         db_cliente.telefono = telefono_nuevo
#         print(f"DEBUG: Teléfono actualizado a: {db_cliente.telefono}")

#     # Maneja el recaudo creando un nuevo abono
#     valor_abono_str = update_data.get("valor_abono")
#     if valor_abono_str and float(valor_abono_str) > 0:
#         valor_abono = float(valor_abono_str)
#         create_abono(db, db_cliente.id, valor_abono)
#         print(f"DEBUG: Abono de {valor_abono} creado para el cliente {db_cliente.id}")

#     # Guarda los cambios
#     try:
#         db.commit()
#         db.refresh(db_cliente)
#     except Exception as e:
#         db.rollback()
#         print(f"ERROR: No se pudieron guardar los cambios. Error: {e}")

# def upsert_cliente(db: Session, cliente_data: Dict[str, Any]) -> Cliente:
#     """
#     Busca un cliente por su NIT y lo actualiza si existe,
#     o crea uno nuevo si no lo encuentra.
#     """

#     # 1. Limpieza y preparación de los datos
#     # Asegura que el NIT sea un string y elimina espacios
#     nit_str = str(cliente_data.get("nit_cliente")).strip() if "nit_cliente" in cliente_data and cliente_data.get("nit_cliente") is not None else None

#     if not nit_str:
#         print("DEBUG: NIT no válido. No se puede procesar el cliente.")
#         return None
    
#     # 2. Búsqueda del cliente existente
#     db_cliente = db.query(Cliente).filter(Cliente.nit_cliente == nit_str).first()

#     # 3. Lógica de creación o actualización
#     if db_cliente:
#         # El cliente existe, actualizamos sus datos
#         print(f"DEBUG: Actualizando cliente existente con NIT: {nit_str}")
#         for key, value in cliente_data.items():
#             if hasattr(db_cliente, key) and key != "id":
#                 setattr(db_cliente, key, value)
#     else:
#         # El cliente no existe, crea una nueva instancia
#         print(f"DEBUG: Creando nuevo cliente con NIT: {nit_str}")
#         # Filtra los datos para que solo contengan los campos del modelo
#         db_cliente = Cliente(**{k: v for k, v in cliente_data.items() if hasattr(Cliente, k)})
#         db.add(db_cliente)

#     # 4. Guardar los cambios
#     try:
#         db.commit()
#         # Refresca el objeto para obtener el ID y otros valores autogenerados
#         db.refresh(db_cliente)
#         print(f"DEBUG: Cliente guardado con éxito. ID: {db_cliente.id}")
#         return db_cliente
#     except Exception as e:
#         # Si algo falla, revierte los cambios para evitar datos inconsistentes
#         db.rollback()
#         print(f"ERROR: No se pudo guardar el cliente. Error: {e}")
#         return None
# # ======================
# # OBSERVACIONES
# # ======================

# def add_observacion(db: Session, cliente_id: int, texto: str):
#     obs = Observacion(cliente_id=cliente_id, texto=texto)
#     db.add(obs)
#     db.commit()
#     db.refresh(obs)
#     return obs


# def get_historial_cliente(db: Session, cliente_id: int):
#     return db.query(Observacion).filter(Observacion.cliente_id == cliente_id).all()

# # ======================
# # NAVEGACIÓN ENTRE CLIENTES
# # ======================

# def get_next_cliente_id(db: Session, current_id: int):
#     next_cliente = db.query(Cliente).filter(Cliente.id > current_id).order_by(Cliente.id.asc()).first()
#     return next_cliente.id if next_cliente else None


# def get_prev_cliente_id(db: Session, current_id: int):
#     prev_cliente = db.query(Cliente).filter(Cliente.id < current_id).order_by(Cliente.id.desc()).first()
#     return prev_cliente.id if prev_cliente else None

