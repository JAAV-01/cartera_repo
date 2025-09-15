
# database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Cambia usuario, contraseña, host, puerto y nombre_base_datos según tu instalación
SQLALCHEMY_DATABASE_URL = "postgresql+psycopg2://postgres:1234@localhost:5432/cartera_db"

# Crea el motor de conexión
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Crea el SessionLocal para abrir sesiones con la BD
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para los modelos
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
