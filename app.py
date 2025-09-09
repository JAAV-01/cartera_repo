# version de chatgptplus (corregido y ordenado)

from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
import pandas as pd
from io import BytesIO
import unicodedata
import re
from models import Cliente
from typing import Dict, Any, List, Set, Optional
from datetime import datetime
from decimal import Decimal, InvalidOperation
from collections import defaultdict
import io
import crud
import models
from database import SessionLocal, engine, Base

# ------------------- Base de datos -------------------
Base.metadata.create_all(bind=engine)

# ------------------- App & Templates -------------------
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


# Filtro Jinja para dinero seguro (acepta str/Decimal/float/int)
def fmt_money(value):
    if value is None or value == "":
        return "-"
    try:
        if isinstance(value, (int, float, Decimal)):
            v = Decimal(str(value))
        else:
            s = str(value).strip().replace("\xa0", "").replace(" ", "")
            has_dot = "." in s
            has_comma = "," in s
            if has_dot and has_comma:
                s = s.replace(".", "").replace(",", ".")
            elif has_comma and not has_dot:
                parts = s.split(",")
                if len(parts) == 2 and parts[1].isdigit():
                    s = s.replace(",", ".")
                else:
                    s = s.replace(",", "")
            elif has_dot and not has_comma:
                parts = s.split(".")
                if not (len(parts) == 2 and parts[1].isdigit()):
                    s = s.replace(".", "")
            v = Decimal(s)
        return f"{v:,.2f}"
    except Exception:
        return str(value)

templates.env.filters["fmt_money"] = fmt_money

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()
    cols = []
    for c in df2.columns:
        if c is None:
            cols.append("unnamed")
        else:
            c2 = str(c).strip().lower()
            c2 = c2.replace(" ", "_")
            cols.append(c2)
    df2.columns = cols
    return df2


def _to_decimal(val) -> Optional[Decimal]:
    try:
        if pd.isna(val):
            return None
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _to_string_formateado(val) -> Optional[str]:
    if pd.isna(val):
        return None
    return str(val).strip()


def normalize_ref(ref: str) -> Optional[str]:
    if not ref:
        return None
    return re.sub(r"[^0-9A-Za-z]", "", str(ref)).upper()

# ------------------- Helpers -------------------
def _normalize_text(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s

def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        _normalize_text(c).lower().replace("  ", " ").replace(" ", "_")
        for c in df.columns
    ]
    return df

def _to_date(x: Any) -> Optional[datetime.date]:
    if pd.isna(x) or x is None or str(x).strip() == "":
        return None
    try:
        if isinstance(x, (datetime, pd.Timestamp)):
            return x.date()
        s = str(x).strip()
        try:
            return pd.to_datetime(s, dayfirst=True).date()
        except Exception:
            return pd.to_datetime(s, dayfirst=False).date()
    except Exception:
        return None

def _to_int(x: Any) -> Optional[int]:
    if pd.isna(x) or x is None or str(x).strip() == "":
        return None
    try:
        return int(float(str(x).replace(",", "").replace(".", "")))
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return None

def _to_string_formateado(x: Any) -> Optional[str]:
    """
    Convierte valores numéricos o strings a string con separadores de miles.
    Ejemplo: 1000000 -> '1,000,000'
    """
    if x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and x.strip() == ""):
        return None
    try:
        # Primero convierto a Decimal
        valor = _to_string_formateado(x)
        if valor is None:
            return None
        # Devuelvo como string con formato
        return "{:,.0f}".format(valor)
    except Exception:
        return str(x)

# def _read_any(upload: UploadFile) -> pd.DataFrame:
#     """
#     Lee CSV (sep=';') o Excel por extensión. Normaliza columnas.
#     """
#     filename = (upload.filename or "").lower()
#     raw = upload.file.read()
#     if filename.endswith(".csv"):
#         df = pd.read_csv(BytesIO(raw), sep=";", engine="python")
#     elif filename.endswith(".xlsx") or filename.endswith(".xls"):
#         df = pd.read_excel(BytesIO(raw))
#     else:
#         try:
#             df = pd.read_excel(BytesIO(raw))
#         except Exception:
#             try:
#                 df = pd.read_csv(BytesIO(raw), sep=";")
#             except Exception:
#                 raise HTTPException(status_code=400, detail=f"No se pudo leer {upload.filename}")
#     if df is None or df.empty:
#         raise HTTPException(status_code=400, detail=f"El archivo {upload.filename} está vacío.")
#     return _norm_cols(df)

def _read_any(file: UploadFile, skiprows: int = 0) -> pd.DataFrame:
    try:
        return pd.read_excel(file.file, skiprows=skiprows)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error leyendo {file.filename}: {e}")


# ------------------- Parse cartera (archivo 1) -------------------
CARTERA_MAP = {
    "razon_social": ["razon_social", "razon_social_", "razon", "razon__social"],
    "nit_cliente": ["nit_cliente_despacho", "nit", "nit_cliente"],
    "nro_docto_cruce": ["nro._docto._cruce", "nro_docto_cruce", "documento_cruce", "nro_doc_cruce"],
    "dias_vencidos": ["dias_vencidos"],
    "fecha_docto": ["fecha_docto.", "fecha_docto"],
    "fecha_vcto": ["fecha_vcto.", "fecha_vcto"],
    "total_cop": ["total_cop", "total_cop_", "total", "total_cop__"],
    "telefono": ["telefono", "telefono_"],
    "celular": ["celular"],
    # Asesor viene de "razon social vend. cliente"
    "asesor": [
        "razon_social_vend._cliente",
        "razon_social_vend_cliente",
        "asesor"
    ]
}

def _pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None

# def extract_cartera_records(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
#     cols = {}
#     for k, cands in CARTERA_MAP.items():
#         col = _pick_col(df, cands)
#         cols[k] = col

#     required = ["razon_social", "nit_cliente", "nro_docto_cruce", "total_cop"]
#     missing = [k for k in required if not cols.get(k)]
#     if missing:
#         raise HTTPException(status_code=400, detail=f"Al archivo de cartera le faltan columnas requeridas: {missing}. Encontradas: {df.columns.tolist()}")

#     out: Dict[str, Dict[str, Any]] = {}
#     for _, row in df.iterrows():
#         ref = str(row[cols["nro_docto_cruce"]]).strip() if cols["nro_docto_cruce"] else ""
#         if not ref:
#             continue
#         rec = {
#             "razon_social": _normalize_text(row[cols["razon_social"]]) if cols["razon_social"] else None,
#             "nit_cliente": str(row[cols["nit_cliente"]]).strip() if cols["nit_cliente"] else None,
#             "nro_docto_cruce": ref,
#             "dias_vencidos": _to_int(row[cols["dias_vencidos"]]) if cols["dias_vencidos"] else None,
#             "fecha_docto": _to_date(row[cols["fecha_docto"]]) if cols["fecha_docto"] else None,
#             "fecha_vcto": _to_date(row[cols["fecha_vcto"]]) if cols["fecha_vcto"] else None,
#             "total_cop": _to_string_formateado(row[cols["total_cop"]]) if cols["total_cop"] else None,
#             "telefono": _normalize_text(row[cols["telefono"]]) if cols["telefono"] else None,
#             "celular": _normalize_text(row[cols["celular"]]) if cols["celular"] else None,
#             "asesor": _normalize_text(row[cols["asesor"]]) if cols["asesor"] else None,
#         }
#         out[ref] = rec
#     return out

def extract_cartera_records(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    df = _norm_cols(df)
    mapping = {}

    for _, row in df.iterrows():
        ref = normalize_ref(row.get("nro_docto_cruce"))
        if not ref:
            continue

        payload = {
            "razon_social": _to_string_formateado(row.get("razon_social")),
            "nit_cliente": _to_string_formateado(row.get("nit_cliente")),
            "nro_docto_cruce": ref,
            "dias_vencidos": row.get("dias_vencidos"),
            "fecha_docto": row.get("fecha_docto"),
            "fecha_vcto": row.get("fecha_vcto"),
            "total_cop": _to_decimal(row.get("total_cop")),
            "telefono": _to_string_formateado(row.get("telefono")),
            "celular": _to_string_formateado(row.get("celular")),
            "asesor": _to_string_formateado(row.get("asesor")),
            "fecha_gestion": row.get("fecha_gestion"),
            "tipo": _to_string_formateado(row.get("tipo")),
        }
        mapping[ref] = payload

    return mapping

# ------------------- Parse recaudos (archivo 2) -------------------
FEV_PATTERN = re.compile(r'(?:\d{1,3}-)?(FEV-\d+)', re.IGNORECASE)

def normalize_fev_ref(s: str) -> Optional[str]:
    if not s:
        return None
    m = FEV_PATTERN.search(str(s))
    return m.group(1) if m else None

# def extract_recaudos_por_factura(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
#     """
#     Extrae por cada referencia FEV:
#       - 'recaudo' SOLO desde columnas que contengan 'credito' o 'debito'
#       - 'fecha_recaudo' desde una columna que contenga 'fecha'
#     """
#     cols = df.columns.tolist()

#     # Columna documento (e.g., '100-FEV-0003xxxx')
#     c_doc = None
#     for c in cols:
#         if c.startswith("unnamed:_0") or c == "unnamed:_0" or c == "unnamed:_0_":
#             c_doc = c
#             break
#     if c_doc is None:
#         c_doc = cols[0]

#     # Columna fecha
#     c_fecha = None
#     for c in cols:
#         if "fecha" in c:
#             c_fecha = c
#             break

#     # SOLO columnas de montos que sean creditos/debitos
#     monto_cols = [c for c in cols if ("credito" in c or "debito" in c)]

#     out: Dict[str, Dict[str, Any]] = {}
#     for _, row in df.iterrows():
#         ref = normalize_fev_ref(str(row.get(c_doc, "")))
#         if not ref:
#             continue

#         f = _to_date(row.get(c_fecha)) if c_fecha else None

#         amount: Optional[Decimal] = None
#         for mc in monto_cols:
#             v = _to_string_formateado(row.get(mc))
#             if v is not None and v != Decimal("0"):
#                 amount = v
#                 break                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              
#         out[ref] = {
#             "recaudo": amount,       # SOLO de credito/debito
#             "fecha_recaudo": f
#         }
#     return out

def extract_recaudos_por_factura(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    df = _norm_cols(df)
    mapping = {}

    for _, row in df.iterrows():
        ref = normalize_ref(row.get("docto_cruce"))
        if not ref:
            continue

        debito = _to_decimal(row.get("débito"))
        credito = _to_decimal(row.get("crédito"))
        fecha_raw = row.get("fecha")

        recaudo_val = debito if debito is not None else credito

        fecha_recaudo = None
        if isinstance(fecha_raw, (datetime, pd.Timestamp)):
            fecha_recaudo = fecha_raw.date()
        elif isinstance(fecha_raw, str):
            try:
                fecha_recaudo = pd.to_datetime(fecha_raw).date()
            except Exception:
                fecha_recaudo = None

        mapping[ref] = {
            "recaudo": recaudo_val,
            "fecha_recaudo": fecha_recaudo,
        }

    return mapping


# ------------------- Página principal con filtros y 2 vistas -------------------
@app.get("/")
def index(
    request: Request,
    db: Session = Depends(get_db),
    view: str = "flat",                                  # flat | group
    min_dias: Optional[str] = Query(default=None),       # ← strings para evitar 422 con ""
    max_dias: Optional[str] = Query(default=None),
    sort: str = "dias_desc",                             # dias_desc | dias_asc | razon_asc
):
    def _parse_int(v: Optional[str]) -> Optional[int]:
        if v is None:
            return None
        v = str(v).strip()
        if v == "":
            return None
        try:
            return int(v)
        except ValueError:
            return None

    min_dias_i = _parse_int(min_dias)
    max_dias_i = _parse_int(max_dias)

    filas_all = crud.get_clientes(db)  # lista de objetos 'cartera'

    if view == "flat":
        # Filtrar por días de CADA factura:
        filas = []
        for c in filas_all:
            dv = c.dias_vencidos or 0
            if min_dias_i is not None and dv < min_dias_i:
                continue
            if max_dias_i is not None and dv > max_dias_i:
                continue
            filas.append(c)

        # Orden
        if sort == "dias_asc":
            filas.sort(key=lambda x: (x.dias_vencidos or 0, (x.razon_social or "").lower()))
        elif sort == "razon_asc":
            filas.sort(key=lambda x: (x.razon_social or "").lower())
        else:
            filas.sort(key=lambda x: (x.dias_vencidos or 0), reverse=True)

        # Extras por fila (cuántas facturas MÁS del mismo cliente y máx días cliente dentro del conjunto filtrado)
        facturas_por_cliente = defaultdict(list)
        for c in filas:
            key = (c.nit_cliente or "").strip() or (c.razon_social or "").strip() or f"__{c.id}"
            facturas_por_cliente[key].append(c)
        extras_por_fila = {}
        for key, lst in facturas_por_cliente.items():
            total = len(lst)
            max_dias_cliente = max((x.dias_vencidos or 0) for x in lst) if lst else 0
            for x in lst:
                extras_por_fila[x.id] = {
                    "otras_facturas": max(0, total - 1),
                    "max_dias_cliente": max_dias_cliente,
                }

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "view": view,
                "filas": filas,
                "extras_por_fila": extras_por_fila,
                "min_dias": min_dias_i,   # pasar ints parseados
                "max_dias": max_dias_i,
                "sort": sort,
            },
        )

    # ---------------- Vista agrupada por cliente (acordeón) ----------------
    grupos = defaultdict(list)
    for c in filas_all:
        key = (c.nit_cliente or "").strip() or (c.razon_social or "").strip() or f"__{c.id}"
        grupos[key].append(c)

    clientes = []
    for key, lst in grupos.items():
        if not lst:
            continue
        razon = lst[0].razon_social
        nit = lst[0].nit_cliente
        client_max = max((x.dias_vencidos or 0) for x in lst)

        # Filtro por rango aplica sobre el MÁXIMO del cliente
        if min_dias_i is not None and client_max < min_dias_i:
            continue
        if max_dias_i is not None and client_max > max_dias_i:
            continue

        # Facturas internas ordenadas por días vencidos desc
        facturas_ordenadas = sorted(lst, key=lambda x: (x.dias_vencidos or 0), reverse=True)

        clientes.append({
            "razon_social": razon,
            "nit_cliente": nit,
            "max_dias": client_max,
            "facturas": facturas_ordenadas,
        })

    # Orden de clientes
    if sort == "dias_asc":
        clientes.sort(key=lambda x: (x["max_dias"] or 0, (x["razon_social"] or "").lower()))
    elif sort == "razon_asc":
        clientes.sort(key=lambda x: (x["razon_social"] or "").lower())
    else:
        clientes.sort(key=lambda x: (x["max_dias"] or 0), reverse=True)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "view": view,
            "clientes": clientes,
            "min_dias": min_dias_i,
            "max_dias": max_dias_i,
            "sort": sort,
        },
    )
@app.get("/buscar")
def buscar_cliente(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db)
):
    print(f"🟢 Buscando cliente con: {q}")

    if q.isdigit():
        cliente = db.query(Cliente).filter(Cliente.id == int(q)).first()
        if cliente:
            return RedirectResponse(url=f"/cliente/{cliente.id}", status_code=303)

    # Buscar ignorando mayúsculas
    cliente = db.query(Cliente).filter(
        func.upper(Cliente.razon_social).like(f"%{q.upper()}%")
    ).first()

    if cliente:
        return RedirectResponse(url=f"/cliente/{cliente.id}", status_code=303)

    return JSONResponse({"error": "Cliente no encontrado"}, status_code=404)

# ------------------- Export Excel -------------------
@app.get("/exportar_cartera.xlsx")
def exportar_cartera(db: Session = Depends(get_db)):
    filas = crud.get_clientes(db)
    data = []
    for c in filas:
        data.append({
            "Razon social": c.razon_social,
            "NIT": c.nit_cliente,
            "Nro docto cruce": c.nro_docto_cruce,
            "Dias vencidos": c.dias_vencidos,
            "Fecha docto": c.fecha_docto,
            "Fecha vcto": c.fecha_vcto,
            "Total COP": c.total_cop,
            "Recaudo": getattr(c, "recaudo", None),
            "Fecha recaudo": getattr(c, "fecha_recaudo", None),
            "Asesor": c.asesor,
        })
    df = pd.DataFrame(data)

    # Fuerza tipos monetarios a Decimal para un Excel limpio
    if not df.empty:
        for col in ["Total COP", "Recaudo"]:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: Decimal(str(x)) if x not in (None, "") else None)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
        df.to_excel(writer, index=False, sheet_name="Cartera")
        ws = writer.sheets["Cartera"]
        for i, col in enumerate(df.columns):
            width = max(12, min(45, int(df[col].astype(str).map(len).max() if not df.empty else 12) + 2))
            ws.set_column(i, i, width)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="cartera.xlsx"'},
    )

# ------------------- Importación doble -------------------
@app.post("/importar_excels")
async def importar_excels(
    request: Request,
    db: Session = Depends(get_db),
    excelFiles: List[UploadFile] = File(...),
):
    if len(excelFiles) != 2:
        raise HTTPException(
            status_code=400,
            detail="Debes subir exactamente 2 archivos: (1) Cartera y (2) Recaudos."
        )

    # Leer archivos
    df1 = _read_any(excelFiles[0])              # Cartera
    df2 = _read_any(excelFiles[1], skiprows=9)  # Recaudos (salta 9 filas de encabezado)

    # Extraer
    cartera_by_ref = extract_cartera_records(df1)
    recaudos_by_ref = extract_recaudos_por_factura(df2)

    # Estado actual en DB
    actuales = {c.nro_docto_cruce: c for c in crud.get_clientes(db)}

    to_create: List[Dict[str, Any]] = []
    to_update: List[Dict[str, Any]] = []
    refs_validas: Set[str] = set()

    # Merge por referencia
    for ref, base in cartera_by_ref.items():
        payload = dict(base)
        rec = recaudos_by_ref.get(ref)
        if rec:
            if rec.get("recaudo") is not None:
                payload["recaudo"] = rec["recaudo"]
            if rec.get("fecha_recaudo") is not None:
                payload["fecha_recaudo"] = rec["fecha_recaudo"]

        if ref in actuales:
            payload["id"] = actuales[ref].id
            to_update.append(payload)
        else:
            to_create.append(payload)
        refs_validas.add(ref)

    # Persistencia
    try:
        if to_create:
            if hasattr(crud, "bulk_create_clientes"):
                crud.bulk_create_clientes(db, to_create)
            else:
                for row in to_create:
                    crud.create_cliente(db, row)

        if to_update:
            if hasattr(crud, "bulk_update_clientes"):
                crud.bulk_update_clientes(db, to_update, pk_field="id")
            else:
                for row in to_update:
                    _id = row.pop("id")
                    crud.update_cliente(db, _id, row)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error importando: {e}")

    return RedirectResponse(url="/", status_code=303)

# ------------------- Vistas por cliente -------------------
@app.get("/cliente/{cliente_id}")
def ver_cliente(cliente_id: int, request: Request, db: Session = Depends(get_db)):
    cliente = crud.get_cliente(db, cliente_id)
    next_id = crud.get_next_cliente_id(db, cliente_id)
    prev_id = crud.get_prev_cliente_id(db, cliente_id)
    return templates.TemplateResponse("cliente.html", {
        "request": request,
        "cliente": cliente,
        "next_id": next_id,
        "prev_id": prev_id
    })

@app.post("/cliente/{cliente_id}/update")
def editar_cliente(
    cliente_id: int,
    request: Request,
    razon_social: str = Form(...),
    nit_cliente: str = Form(...),
    nro_docto_cruce: str = Form(...),
    telefono: str = Form(...),
    celular: str = Form(...),
    tipo: str = Form(...), 
    asesor: str = Form(...),
    observaciones: str = Form(None),  
    fecha_gestion: str = Form(None),  
    db: Session = Depends(get_db),
):
    
    data = {
        "razon_social": razon_social,
        "nit_cliente": nit_cliente,
        "nro_docto_cruce": nro_docto_cruce,
        "telefono": telefono,
        "celular": celular,
        "asesor": asesor,
        "tipo": tipo,
        "fecha_gestion": fecha_gestion,  
    }
    crud.update_cliente(db, cliente_id, data)

    # 👉 Guardar observación como registro aparte
    if observaciones and observaciones.strip():
        crud.add_observacion(db, cliente_id, observaciones)

    return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=303)


@app.post("/cliente/{cliente_id}/observacion")
def agregar_observacion(
    cliente_id: int, 
    texto: str = Form(...), 
    db: Session = Depends(get_db)
):
    crud.add_observacion(db, cliente_id, texto.strip())
    return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=303)

@app.get("/cliente/{cliente_id}/historial")
def historial_cliente(cliente_id: int, db: Session = Depends(get_db)):
    historial = crud.get_historial_cliente(db, cliente_id)
    return JSONResponse([
        {
            "id": obs.id,
            "fecha": obs.fecha_creacion.strftime("%Y-%m-%d %H:%M:%S") if obs.fecha_creacion else None,
            "texto": obs.texto,
        }
        for obs in historial
    ])

@app.post("/cliente/{cliente_id}/delete")
def eliminar_cliente(cliente_id: int, db: Session = Depends(get_db)):
    crud.delete_cliente(db, cliente_id)
    return RedirectResponse(url="/", status_code=303)



# version dos cambios para fecha y recaudo
# from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException, Query
# from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
# from fastapi.templating import Jinja2Templates
# from fastapi.staticfiles import StaticFiles
# from sqlalchemy.orm import Session
# import pandas as pd
# from io import BytesIO
# import unicodedata
# import re
# from typing import Dict, Any, List, Set, Optional
# from datetime import datetime
# from decimal import Decimal, InvalidOperation
# from collections import defaultdict
# import io

# import crud
# import models
# from database import SessionLocal, engine, Base

# Base.metadata.create_all(bind=engine)

# app = FastAPI()
# templates = Jinja2Templates(directory="templates")
# app.mount("/static", StaticFiles(directory="static"), name="static")
# app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# def fmt_money(value):
#     if value is None or value == "":
#         return "-"
#     try:
#         if isinstance(value, (int, float, Decimal)):
#             v = Decimal(str(value))
#         else:
#             s = str(value).strip().replace("\xa0", "").replace(" ", "")
#             has_dot = "." in s
#             has_comma = "," in s
#             if has_dot and has_comma:
#                 s = s.replace(".", "").replace(",", ".")
#             elif has_comma and not has_dot:
#                 parts = s.split(",")
#                 if len(parts) == 2 and parts[1].isdigit():
#                     s = s.replace(",", ".")
#                 else:
#                     s = s.replace(",", "")
#             elif has_dot and not has_comma:
#                 parts = s.split(".")
#                 if not (len(parts) == 2 and parts[1].isdigit()):
#                     s = s.replace(".", "")
#             v = Decimal(s)
#         return f"{v:,.2f}"
#     except Exception:
#         return str(value)

# templates.env.filters["fmt_money"] = fmt_money

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

# def _normalize_text(s: Any) -> str:
#     if s is None:
#         return ""
#     s = str(s).strip()
#     s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
#     return s

# def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
#     df = df.copy()
#     df.columns = [
#         _normalize_text(c).lower().replace("  ", " ").replace(" ", "_")
#         for c in df.columns
#     ]
#     return df

# def _to_date(x: Any) -> Optional[datetime.date]:
#     if pd.isna(x) or x is None or str(x).strip() == "":
#         return None
#     try:
#         if isinstance(x, (datetime, pd.Timestamp)):
#             return x.date()
#         s = str(x).strip()
#         try:
#             return pd.to_datetime(s, dayfirst=True).date()
#         except Exception:
#             return pd.to_datetime(s, dayfirst=False).date()
#     except Exception:
#         return None

# def _to_int(x: Any) -> Optional[int]:
#     if pd.isna(x) or x is None or str(x).strip() == "":
#         return None
#     try:
#         return int(float(str(x).replace(",", "").replace(".", "")))
#     except Exception:
#         try:
#             return int(float(x))
#         except Exception:
#             return None

# def _to_decimal_preciso(x: Any) -> Optional[Decimal]:
#     if x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and x.strip() == ""):
#         return None
#     s = str(x).strip().replace("\xa0", "").replace(" ", "")
#     if s.isdigit():
#         try:
#             return Decimal(s)
#         except InvalidOperation:
#             return None
#     has_dot = "." in s
#     has_comma = "," in s
#     try:
#         if has_dot and has_comma:
#             return Decimal(s.replace(".", "").replace(",", "."))
#         if has_comma and not has_dot:
#             parts = s.split(",")
#             if len(parts) == 2 and len(parts[1]) in (1, 2, 3):
#                 return Decimal(s.replace(",", "."))
#             else:
#                 return Decimal(s.replace(",", ""))
#         if has_dot and not has_comma:
#             parts = s.split(".")
#             if len(parts) == 2 and len(parts[1]) in (1, 2, 3):
#                 return Decimal(s)
#             else:
#                 return Decimal(s.replace(".", ""))
#         return Decimal(s)
#     except InvalidOperation:
#         cleaned = re.sub(r"[^\d,.\-]", "", s)
#         try:
#             return Decimal(cleaned.replace(".", "").replace(",", "."))
#         except InvalidOperation:
#             try:
#                 return Decimal(cleaned)
#             except InvalidOperation:
#                 return None

# def _read_any(upload: UploadFile) -> pd.DataFrame:
#     filename = (upload.filename or "").lower()
#     raw = upload.file.read()
#     if filename.endswith(".csv"):
#         df = pd.read_csv(BytesIO(raw), sep=";", engine="python")
#     elif filename.endswith(".xlsx") or filename.endswith(".xls"):
#         df = pd.read_excel(BytesIO(raw))
#     else:
#         try:
#             df = pd.read_excel(BytesIO(raw))
#         except Exception:
#             try:
#                 df = pd.read_csv(BytesIO(raw), sep=";")
#             except Exception:
#                 raise HTTPException(status_code=400, detail=f"No se pudo leer {upload.filename}")
#     if df is None or df.empty:
#         raise HTTPException(status_code=400, detail=f"El archivo {upload.filename} está vacío.")
#     return _norm_cols(df)

# # ---------- Mapeo Cartera ----------
# CARTERA_MAP = {
#     "razon_social": ["razon_social", "razon_social_", "razon", "razon__social"],
#     "nit_cliente": ["nit_cliente_despacho", "nit", "nit_cliente"],
#     "nro_docto_cruce": ["nro._docto._cruce", "nro_docto_cruce", "documento_cruce", "nro_doc_cruce"],
#     "dias_vencidos": ["dias_vencidos"],
#     "fecha_docto": ["fecha_docto.", "fecha_docto"],
#     "fecha_vcto": ["fecha_vcto.", "fecha_vcto"],
#     "total_cop": ["total_cop", "total_cop_", "total", "total_cop__"],
#     "telefono": ["telefono", "telefono_"],
#     "celular": ["celular"],
#     "asesor": ["razon_social_vend._cliente","razon_social_vend_cliente","asesor"]
# }
# def _pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
#     cols = set(df.columns)
#     for c in candidates:
#         if c in cols:
#             return c
#     return None

# def extract_cartera_records(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
#     cols = {k: _pick_col(df, cands) for k, cands in CARTERA_MAP.items()}
#     required = ["razon_social", "nit_cliente", "nro_docto_cruce", "total_cop"]
#     missing = [k for k in required if not cols.get(k)]
#     if missing:
#         raise HTTPException(status_code=400, detail=f"Al archivo de cartera le faltan columnas requeridas: {missing}. Encontradas: {df.columns.tolist()}")
#     out: Dict[str, Dict[str, Any]] = {}
#     for _, row in df.iterrows():
#         ref = str(row[cols["nro_docto_cruce"]]).strip() if cols["nro_docto_cruce"] else ""
#         if not ref:
#             continue
#         out[ref] = {
#             "razon_social": _normalize_text(row[cols["razon_social"]]) if cols["razon_social"] else None,
#             "nit_cliente": str(row[cols["nit_cliente"]]).strip() if cols["nit_cliente"] else None,
#             "nro_docto_cruce": ref,
#             "dias_vencidos": _to_int(row[cols["dias_vencidos"]]) if cols["dias_vencidos"] else None,
#             "fecha_docto": _to_date(row[cols["fecha_docto"]]) if cols["fecha_docto"] else None,
#             "fecha_vcto": _to_date(row[cols["fecha_vcto"]]) if cols["fecha_vcto"] else None,
#             "total_cop": _to_decimal_preciso(row[cols["total_cop"]]) if cols["total_cop"] else None,
#             "telefono": _normalize_text(row[cols["telefono"]]) if cols["telefono"] else None,
#             "celular": _normalize_text(row[cols["celular"]]) if cols["celular"] else None,
#             "asesor": _normalize_text(row[cols["asesor"]]) if cols["asesor"] else None,
#         }
#     return out

# # ---------- Recaudos (columna C = fecha) ----------
# FEV_PATTERN = re.compile(r'(?:\d{1,3}-)?(FEV-\d+)', re.IGNORECASE)
# def normalize_fev_ref(s: str) -> Optional[str]:
#     if not s:
#         return None
#     m = FEV_PATTERN.search(str(s))
#     return m.group(1) if m else None

# def extract_recaudos_por_factura(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
#     cols = list(df.columns)

#     # Documento = primera columna
#     c_doc = cols[0] if cols else None
#     if c_doc is None:
#         return {}

#     # Fecha = C (índice 2) si existe; si no, busca por nombre 'fecha'
#     c_fecha = cols[2] if len(cols) > 2 else next((c for c in cols if "fecha" in c), None)

#     # SOLO columnas de montos creditos/debitos (ya normalizadas, sin tildes)
#     monto_cols = [c for c in cols if ("credito" in c or "debito" in c)]

#     out: Dict[str, Dict[str, Any]] = {}
#     for _, row in df.iterrows():
#         ref = normalize_fev_ref(str(row.get(c_doc, "")))
#         if not ref:
#             continue

#         f = _to_date(row.get(c_fecha)) if c_fecha else None

#         amount: Optional[Decimal] = None
#         for mc in monto_cols:
#             v = _to_decimal_preciso(row.get(mc))
#             if v is not None and v != Decimal("0"):
#                 amount = v
#                 break

#         out[ref] = {
#             "recaudo": amount,
#             "fecha_recaudo": f
#         }
#     return out

# # ---------- Index agrupado por NIT (solo los campos que pediste) ----------
# @app.get("/")
# def index(
#     request: Request,
#     db: Session = Depends(get_db),
#     min_dias: Optional[str] = Query(default=None),
#     max_dias: Optional[str] = Query(default=None),
#     sort: str = "dias_desc",  # dias_desc | dias_asc | razon_asc | facturas_desc | facturas_asc
# ):
#     def _parse_int(v: Optional[str]) -> Optional[int]:
#         if v is None:
#             return None
#         v = str(v).strip()
#         if v == "":
#             return None
#         try:
#             return int(v)
#         except ValueError:
#             return None

#     min_dias_i = _parse_int(min_dias)
#     max_dias_i = _parse_int(max_dias)

#     filas_all = crud.get_clientes(db)
#     grupos_por_nit: Dict[str, List[Any]] = defaultdict(list)

#     for c in filas_all:
#         nit_key = (c.nit_cliente or "").strip()
#         if nit_key == "":
#             nit_key = (c.razon_social or "").strip() or f"__{c.id}"
#         grupos_por_nit[nit_key].append(c)

#     clientes = []
#     for nit_key, lst in grupos_por_nit.items():
#         if not lst:
#             continue
#         razon = next((x.razon_social for x in lst if (x.razon_social or "").strip()), lst[0].razon_social)
#         count_facturas = len(lst)
#         max_dias_cliente = max((x.dias_vencidos or 0) for x in lst)

#         if min_dias_i is not None and max_dias_cliente < min_dias_i:
#             continue
#         if max_dias_i is not None and max_dias_cliente > max_dias_i:
#             continue

#         facturas_ordenadas = sorted(lst, key=lambda x: (x.dias_vencidos or 0), reverse=True)

#         clientes.append({
#             "razon_social": razon,
#             "nit_cliente": nit_key,
#             "count": count_facturas,
#             "max_dias": max_dias_cliente,
#             "facturas": facturas_ordenadas,
#         })

#     if sort == "dias_asc":
#         clientes.sort(key=lambda x: (x["max_dias"] or 0, (x["razon_social"] or "").lower()))
#     elif sort == "razon_asc":
#         clientes.sort(key=lambda x: (x["razon_social"] or "").lower())
#     elif sort == "facturas_desc":
#         clientes.sort(key=lambda x: (x["count"] or 0), reverse=True)
#     elif sort == "facturas_asc":
#         clientes.sort(key=lambda x: (x["count"] or 0))
#     else:
#         clientes.sort(key=lambda x: (x["max_dias"] or 0), reverse=True)

#     return templates.TemplateResponse(
#         "index.html",
#         {
#             "request": request,
#             "clientes": clientes,
#             "min_dias": min_dias_i,
#             "max_dias": max_dias_i,
#             "sort": sort,
#         },
#     )

# # ---------- Export ----------
# @app.get("/exportar_cartera.xlsx")
# def exportar_cartera(db: Session = Depends(get_db)):
#     filas = crud.get_clientes(db)
#     data = []
#     for c in filas:
#         data.append({
#             "Razon social": c.razon_social,
#             "NIT": c.nit_cliente,
#             "Nro docto cruce": c.nro_docto_cruce,
#             "Dias vencidos": c.dias_vencidos,
#             "Fecha docto": c.fecha_docto,
#             "Fecha vcto": c.fecha_vcto,
#             "Total COP": c.total_cop,
#             "Recaudo": getattr(c, "recaudo", None),
#             "Fecha recaudo": getattr(c, "fecha_recaudo", None),
#             "Asesor": c.asesor,
#             "Tipo": getattr(c, "tipo", None),
#         })
#     df = pd.DataFrame(data)
#     if not df.empty:
#         for col in ["Total COP", "Recaudo"]:
#             if col in df.columns:
#                 df[col] = df[col].apply(lambda x: Decimal(str(x)) if x not in (None, "") else None)

#     buf = io.BytesIO()
#     with pd.ExcelWriter(buf, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
#         df.to_excel(writer, index=False, sheet_name="Cartera")
#         ws = writer.sheets["Cartera"]
#         for i, col in enumerate(df.columns):
#             width = max(12, min(45, int(df[col].astype(str).map(len).max() if not df.empty else 12) + 2))
#             ws.set_column(i, i, width)
#     buf.seek(0)

#     return StreamingResponse(
#         buf,
#         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         headers={"Content-Disposition": 'attachment; filename="cartera.xlsx"'},
#     )

# # ---------- Import doble ----------
# @app.post("/importar_excels")
# async def importar_excels(
#     request: Request,
#     db: Session = Depends(get_db),
#     excelFiles: List[UploadFile] = File(...),
# ):
#     if len(excelFiles) != 2:
#         raise HTTPException(status_code=400, detail="Debes subir exactamente 2 archivos: (1) Cartera y (2) Recaudos.")

#     df1 = _read_any(excelFiles[0])
#     df2 = _read_any(excelFiles[1])

#     cartera_by_ref = extract_cartera_records(df1)
#     recaudos_by_ref = extract_recaudos_por_factura(df2)

#     actuales = {c.nro_docto_cruce: c for c in crud.get_clientes(db)}

#     to_create: List[Dict[str, Any]] = []
#     to_update: List[Dict[str, Any]] = []
#     refs_validas: Set[str] = set()

#     for ref, base in cartera_by_ref.items():
#         payload = dict(base)
#         rec = recaudos_by_ref.get(ref)
#         if rec:
#             if rec.get("recaudo") is not None:
#                 payload["recaudo"] = rec["recaudo"]
#             if rec.get("fecha_recaudo") is not None:
#                 payload["fecha_recaudo"] = rec["fecha_recaudo"]

#         if ref in actuales:
#             payload["id"] = actuales[ref].id
#             to_update.append(payload)
#         else:
#             to_create.append(payload)
#         refs_validas.add(ref)

#     try:
#         if to_create:
#             if hasattr(crud, "bulk_create_clientes"):
#                 crud.bulk_create_clientes(db, to_create)
#             else:
#                 for row in to_create:
#                     crud.create_cliente(db, row)

#         if to_update:
#             if hasattr(crud, "bulk_update_clientes"):
#                 crud.bulk_update_clientes(db, to_update, pk_field="id")
#             else:
#                 for row in to_update:
#                     _id = row.pop("id")
#                     crud.update_cliente(db, _id, row)

#         # Borrado desactivado por defecto
#         # ...

#         db.commit()
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=f"Error importando: {e}")

#     return RedirectResponse(url="/", status_code=303)

# # ---------- Vistas por cliente ----------
# @app.get("/cliente/{cliente_id}")
# def ver_cliente(cliente_id: int, request: Request, db: Session = Depends(get_db)):
#     cliente = crud.get_cliente(db, cliente_id)
#     next_id = crud.get_next_cliente_id(db, cliente_id)
#     prev_id = crud.get_prev_cliente_id(db, cliente_id)
#     return templates.TemplateResponse("cliente.html", {
#         "request": request,
#         "cliente": cliente,
#         "next_id": next_id,
#         "prev_id": prev_id
#     })

# @app.post("/cliente/{cliente_id}/update")
# def editar_cliente(
#     cliente_id: int,
#     request: Request,
#     razon_social: str = Form(...),
#     nit_cliente: str = Form(...),
#     nro_docto_cruce: str = Form(...),
#     telefono: str = Form(""),
#     celular: str = Form(""),
#     asesor: str = Form(""),
#     tipo: str = Form(""),  # <-- NUEVO: guardar tipo
#     db: Session = Depends(get_db),
# ):
#     data = {
#         "razon_social": razon_social,
#         "nit_cliente": nit_cliente,
#         "nro_docto_cruce": nro_docto_cruce,
#         "telefono": telefono,
#         "celular": celular,
#         "asesor": asesor,
#         "tipo": tipo,  # <-- se persiste en BD (VARCHAR(50) OK)
#     }
#     crud.update_cliente(db, cliente_id, data)
#     return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=303)

# @app.post("/cliente/{cliente_id}/observacion")
# def agregar_observacion(cliente_id: int, texto: str = Form(...), db: Session = Depends(get_db)):
#     crud.add_observacion(db, cliente_id, texto)
#     return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=303)

# @app.get("/cliente/{cliente_id}/historial")
# def historial_cliente(cliente_id: int, db: Session = Depends(get_db)):
#     historial = crud.get_historial_cliente(db, cliente_id)
#     return JSONResponse([{"fecha": getattr(obs, "fecha", None), "observacion": getattr(obs, "observacion", None)} for obs in historial])

# @app.post("/cliente/{cliente_id}/delete")
# def eliminar_cliente(cliente_id: int, db: Session = Depends(get_db)):
#     crud.delete_cliente(db, cliente_id)
#     return RedirectResponse(url="/", status_code=303)