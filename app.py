from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import UploadFile, File, Form, Query, status
from fastapi.responses import StreamingResponse
from database import SessionLocal, engine, Base
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from sqlalchemy import tuple_
from typing import Optional
from decimal import Decimal
from io import BytesIO
import pandas as pd
import models
import math
import crud
import re


# ------------------- Inicialización -------------------
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# ------------------- Helpers -------------------
def fmt_money(value):
    """Filtro para mostrar números como moneda"""
    if value is None or value == "":
        return "-"
    try:
        v = Decimal(str(value))
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


def to_float(val):
    try:
        if pd.isna(val):
            return None
        val_str = str(val).replace(",", ".")
        val_str = re.sub(r"[^0-9.]", "", val_str)
        return float(val_str) if val_str else None
    except (ValueError, TypeError):
        return None
    
def clean_phone(val):
    """Normaliza teléfonos: quita .0, separadores y deja solo dígitos."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()

    # 3046304674.0 -> 3046304674
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]

    # 3.046304674E+09 -> 3046304674
    try:
        if re.fullmatch(r"\d+(\.\d+)?[eE][+-]?\d+", s):
            s = str(int(float(s)))
    except Exception:
        pass

    # 1234.00 -> 1234 si es entero exacto
    if re.fullmatch(r"\d+\.\d+", s):
        try:
            f = float(s)
            if f.is_integer():
                s = str(int(f))
        except Exception:
            pass

    # Dejar solo dígitos (quita espacios, guiones, paréntesis, etc.)
    s = re.sub(r"[^\d]", "", s)
    return s or None

# ------------------- Exportar cartera a Excel -------------------
@app.get("/exportar_cartera.xlsx", name="exportar_cartera_xlsx")
def exportar_cartera_xlsx(
    db: Session = Depends(get_db),
    min_dias: Optional[str] = Query(None),
    max_dias: Optional[str] = Query(None),
    sort: Optional[str] = Query("dias_desc"),
):
    # --- Helpers ---
    def to_int_or_none(val: Optional[str]):
        try:
            return int(val) if val not in (None, "") else None
        except (ValueError, TypeError):
            return None

    min_val = to_int_or_none(min_dias)
    max_val = to_int_or_none(max_dias)

    # --- Query + filtros + orden ---
    query = db.query(models.Cliente)
    if min_val is not None:
        query = query.filter(models.Cliente.dias_vencidos >= min_val)
    if max_val is not None:
        query = query.filter(models.Cliente.dias_vencidos <= max_val)

    order_map = {
        "dias_desc": models.Cliente.dias_vencidos.desc(),
        "dias_asc": models.Cliente.dias_vencidos.asc(),
    }
    query = query.order_by(order_map.get(sort, order_map["dias_desc"]))
    clientes = query.all()

    # --- Filas planas ---
    rows = []
    for c in clientes:
        valor_docto = Decimal(str(c.valor_docto or 0))
        total_cop = Decimal(str(c.total_cop or 0))
        recaudo = Decimal(str(c.recaudo)) if c.recaudo is not None else (valor_docto - total_cop)

        obs_txt = ""
        if getattr(c, "observaciones", None):
            obs_txt = "\n".join(
                f"{(o.fecha_creacion.strftime('%Y-%m-%d %H:%M') if o.fecha_creacion else '')} - {o.texto}"
                for o in c.observaciones
            )

        rows.append({
            "ID": c.id,
            "Razón social": c.razon_social,
            "NIT": c.nit_cliente,
            "Docto cruce": c.nro_docto_cruce,
            "Días vencidos": c.dias_vencidos,
            "Fecha docto": c.fecha_docto,
            "Fecha vcto": c.fecha_vcto,
            "Valor docto": float(valor_docto),
            "Total COP (saldo)": float(total_cop),
            "Recaudo": float(recaudo),
            "Teléfono": c.telefono,
            "Celular": c.celular,
            "Asesor": c.asesor,
            "Fecha gestión": c.fecha_gestion,
            "Tipo": c.tipo,
            "Observaciones": obs_txt,
        })

    df = pd.DataFrame(rows)

    # Normaliza fechas a datetime (Excel-friendly)
    for col in ["Fecha docto", "Fecha vcto", "Fecha gestión"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # --- Resumen por cliente ---
    if not df.empty:
        resumen = (
            df.groupby(["NIT", "Razón social"], dropna=False)
              .agg({
                  "Valor docto": "sum",
                  "Total COP (saldo)": "sum",
                  "Recaudo": "sum",
                  "Días vencidos": "max",
              })
              .rename(columns={
                  "Valor docto": "Total Valor Docto",
                  "Total COP (saldo)": "Saldo Total",
                  "Recaudo": "Recaudo Total",
                  "Días vencidos": "Max Días Vencidos",
              })
              .reset_index()
        )
        ref = (
            df.sort_values(["NIT"]).groupby(["NIT", "Razón social"], dropna=False)
              .agg({"Teléfono": "first", "Celular": "first", "Asesor": "first"})
              .reset_index()
        )
        resumen = resumen.merge(ref, on=["NIT", "Razón social"], how="left")

        facturas = (
            df.groupby(["NIT", "Razón social"], dropna=False)
              .size()
              .reset_index(name="# Facturas")
        )
        resumen = resumen.merge(facturas, on=["NIT", "Razón social"], how="left")
        resumen["# Facturas"] = resumen["# Facturas"].fillna(0).astype(int)
    else:
        resumen = pd.DataFrame(columns=[
            "NIT","Razón social","Total Valor Docto","Saldo Total","Recaudo Total",
            "Max Días Vencidos","Teléfono","Celular","Asesor","# Facturas"
        ])

    # --- Excel en memoria ---
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter",
                        datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd") as writer:
        # Escribir hojas
        df.to_excel(writer, index=False, sheet_name="cartera")
        resumen.to_excel(writer, index=False, sheet_name="resumen")

        wb = writer.book
        ws1 = writer.sheets["cartera"]
        ws2 = writer.sheets["resumen"]

        # Congelar encabezado
        for ws in (ws1, ws2):
            ws.freeze_panes(1, 0)

        # --- Formatos ---
        fmt_header = wb.add_format({
            'bold': True, 'bg_color': '#D9E1F2', 'border': 1,
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_money0 = wb.add_format({'num_format': '#,##0', 'border': 1})
        fmt_int = wb.add_format({'num_format': '#,##0', 'border': 1})
        fmt_date = wb.add_format({'num_format': 'yyyy-mm-dd', 'border': 1})
        fmt_text = wb.add_format({'text_wrap': True, 'border': 1, 'valign': 'top'})
        fmt_default = wb.add_format({'border': 1})

        def table_with_formats(ws, df_sheet, money_cols, date_cols, wrap_cols):
            """Crea tabla con formatos por columna y calcula anchos."""
            rows, cols = df_sheet.shape
            headers = list(df_sheet.columns)

            # Mapear formato por columna
            per_col_format = {}
            for col in headers:
                if col in money_cols:
                    per_col_format[col] = fmt_money0
                elif col in date_cols:
                    per_col_format[col] = fmt_date
                elif col in wrap_cols:
                    per_col_format[col] = fmt_text
                elif df_sheet[col].dtype.kind in ("i", "u"):  # enteros
                    per_col_format[col] = fmt_int
                else:
                    per_col_format[col] = fmt_default

            # Definir columnas de la tabla con formato (esto sí aplica dentro de la tabla)
            columns_def = [{'header': h, 'format': per_col_format[h]} for h in headers]

            # Crear tabla (si hay datos). Si no, solo pintamos encabezados.
            if rows > 0:
                ws.add_table(0, 0, rows, cols - 1, {
                    'style': 'Table Style Medium 9',
                    'banded_rows': True,
                    'columns': columns_def
                })
            else:
                for c_idx, h in enumerate(headers):
                    ws.write(0, c_idx, h, fmt_header)

            # Auto–ancho aproximado por columna
            col_widths = {}
            for c_idx, col in enumerate(headers):
                max_len = len(str(col)) + 2
                serie = df_sheet[col]

                if col in money_cols:
                    # medir como miles sin decimales
                    for v in serie.dropna():
                        try:
                            s = f"{int(round(float(v))):,}"
                            max_len = max(max_len, len(s))
                        except Exception:
                            pass
                elif col in date_cols:
                    max_len = max(max_len, 12)
                else:
                    # considerar saltos de línea (tomar la línea más larga)
                    for v in serie.dropna():
                        s = str(v).replace("\r", "")
                        max_len = max(max_len, max((len(seg) for seg in s.split("\n")), default=0))
                    # límite práctico
                    if col in wrap_cols:
                        max_len = min(max(max_len, 40), 80)
                    else:
                        max_len = min(max_len, 40)

                width = max_len + 1
                col_widths[col] = width
                ws.set_column(c_idx, c_idx, width, per_col_format[col])

            return col_widths, per_col_format

        def autofit_row_heights(ws, df_sheet, wrap_cols, col_widths):
            """Ajusta alto de fila según # líneas estimadas en columnas wrap."""
            if df_sheet.empty or not wrap_cols:
                return
            base_height = 15  # pts aprox por línea
            max_height = 300

            for r in range(1, len(df_sheet) + 1):  # +1 por header
                max_lines = 1
                for col in wrap_cols:
                    if col not in df_sheet.columns:
                        continue
                    val = df_sheet.iloc[r - 1][col]
                    if pd.isna(val) or val is None:
                        continue
                    text = str(val).replace("\r", "")
                    if text == "":
                        continue

                    # Estimar caracteres por línea a partir del ancho de columna
                    col_w = int(col_widths.get(col, 40))
                    chars_per_line = max(col_w - 2, 10)

                    total_lines = 0
                    for seg in text.split("\n"):
                        seg = seg.strip()
                        if seg == "":
                            total_lines += 1
                        else:
                            total_lines += math.ceil(len(seg) / chars_per_line)

                    max_lines = max(max_lines, total_lines)

                ws.set_row(r, min(base_height * max_lines + 4, max_height))

        # Columnas por tipo (cartera)
        money_cols_cartera = ["Valor docto", "Total COP (saldo)", "Recaudo"]
        date_cols_cartera = ["Fecha docto", "Fecha vcto", "Fecha gestión"]
        wrap_cols_cartera = ["Razón social", "Observaciones"]  # ⇦ ajustar ancho/alto por texto

        # Columnas por tipo (resumen)
        money_cols_resumen = ["Total Valor Docto", "Saldo Total", "Recaudo Total"]
        date_cols_resumen = []
        wrap_cols_resumen = ["Razón social"]

        # Aplicar tabla + formatos + anchos
        widths_cartera, _ = table_with_formats(ws1, df, money_cols_cartera, date_cols_cartera, wrap_cols_cartera)
        widths_resumen, _ = table_with_formats(ws2, resumen, money_cols_resumen, date_cols_resumen, wrap_cols_resumen)

        # Ajustar alturas (solo donde hay wrap)
        autofit_row_heights(ws1, df, wrap_cols_cartera, widths_cartera)
        autofit_row_heights(ws2, resumen, wrap_cols_resumen, widths_resumen)

    output.seek(0)
    filename = f"cartera_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# ------------------- Importar cartera -------------------
@app.post("/importar_excel")
async def importar_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        contents = await file.read()
        df = pd.read_excel(
            BytesIO(contents),
            dtype={
                "Nit cliente despacho": str,
                "Nro. docto. cruce": str,
                "Celular": str,
                "Teléfono": str,
            }
        )

        rename_map = {
            "Razón social": "razon_social",
            "Nit cliente despacho": "nit_cliente",
            "Nro. docto. cruce": "nro_docto_cruce",
            "Fecha docto.": "fecha_docto",
            "Dias vencidos": "dias_vencidos",
            "Valor docto": "valor_docto",
            "Total COP": "total_cop",
            "Fecha vcto.": "fecha_vcto",
            "Celular": "celular",
            "Teléfono": "telefono",
            "Razón social vend. cliente": "asesor"
        }
        df.rename(columns=rename_map, inplace=True)
        for col in ("telefono", "celular"):
         if col in df.columns:
             df[col] = df[col].apply(clean_phone)

        if df.empty:
            return RedirectResponse(url="/", status_code=303)

        # Claves en Excel
        excel_claves = set(
            (str(row["nit_cliente"]), str(row["nro_docto_cruce"]))
            for _, row in df.iterrows()
            if row.get("nit_cliente") and row.get("nro_docto_cruce")
        )

        # Claves en BD
        bd_clientes = db.query(models.Cliente).all()
        bd_claves = set((c.nit_cliente, c.nro_docto_cruce) for c in bd_clientes)

        # Eliminar clientes que no están en Excel
        claves_a_eliminar = bd_claves - excel_claves
        if claves_a_eliminar:
            db.query(models.Cliente).filter(
                tuple_(
                    models.Cliente.nit_cliente,
                    models.Cliente.nro_docto_cruce
                ).in_(claves_a_eliminar)
            ).delete(synchronize_session=False)

        # Insertar o actualizar
        for _, row in df.iterrows():
            nit = str(row.get("nit_cliente")).strip() if row.get("nit_cliente") else None
            docto = str(row.get("nro_docto_cruce")).strip() if row.get("nro_docto_cruce") else None
            if not nit or not docto:
                continue

            valor_docto = to_float(row.get("valor_docto")) or 0.0
            total_excel = to_float(row.get("total_cop")) if row.get("total_cop") is not None else valor_docto

            # >>> NUEVO: calcular recaudo y normalizar a 2 decimales (no negativo)
            recaudo_calc = round(max((valor_docto or 0.0) - (total_excel or 0.0), 0.0), 2)

            cliente = db.query(models.Cliente).filter_by(
                nit_cliente=nit,
                nro_docto_cruce=docto
            ).first()

            if cliente:
                # Actualizar existente
                cliente.razon_social = row.get("razon_social")
                cliente.dias_vencidos = row.get("dias_vencidos")
                cliente.fecha_docto = row.get("fecha_docto")
                cliente.fecha_vcto = row.get("fecha_vcto")
                cliente.valor_docto = valor_docto
                cliente.total_cop = total_excel
                cliente.recaudo = recaudo_calc  # <<< persistir recaudo
                cliente.telefono = clean_phone(row.get("telefono"))
                cliente.celular  = clean_phone(row.get("celular"))
                cliente.asesor = row.get("asesor")
            else:
                # Insertar nuevo
                nuevo = models.Cliente(
                    razon_social=row.get("razon_social"),
                    nit_cliente=nit,
                    nro_docto_cruce=docto,
                    dias_vencidos=row.get("dias_vencidos"),
                    fecha_docto=row.get("fecha_docto"),
                    fecha_vcto=row.get("fecha_vcto"),
                    valor_docto=valor_docto,
                    total_cop=total_excel,
                    recaudo=recaudo_calc,  # <<< persistir recaudo
                    telefono=clean_phone(row.get("telefono")),
                    celular=clean_phone(row.get("celular")),
                    asesor=row.get("asesor"),
                )
                db.add(nuevo)

        db.commit()
        return RedirectResponse(url="/", status_code=303)

    except Exception as e:
        print("❌ Error importar_excel:", e)
        return RedirectResponse(url="/", status_code=303)


# ------------------- Observaciones -------------------
@app.post("/cliente/{cliente_id}/observacion")
def agregar_observacion(cliente_id: int, texto: str = Form(...), db: Session = Depends(get_db)):
    crud.add_observacion(db, cliente_id, texto)
    return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=303)

# ------------------- Actualizar cliente (editar recaudo) -------------------
@app.post("/cliente/{cliente_id}/update")
async def update_cliente(
    request: Request,
    cliente_id: int,
    db: Session = Depends(get_db)
):
    form_data = await request.form()

    # Buscar cliente
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # ---- Campos texto: actualizar solo si llegan con valor (no sobrescribir con vacío) ----
    for campo in ["telefono", "celular", "fecha_gestion", "tipo", "asesor"]:
        val = form_data.get(campo)
        if val is not None and val != "":
            setattr(cliente, campo, val)

    # ---- NUMÉRICOS coherentes: identidad recaudo = valor_docto - total_cop ----
    valor_docto = float(cliente.valor_docto or 0.0)

    raw_recaudo = form_data.get("recaudo")
    raw_total_cop = form_data.get("total_cop")

    has_recaudo = raw_recaudo is not None and raw_recaudo.strip() != ""
    has_total_cop = raw_total_cop is not None and raw_total_cop.strip() != ""

    if has_recaudo:
        # Interpreta recaudo como ABONO (delta)
        delta = to_float(raw_recaudo)
        if delta is not None:
            old_total = float(cliente.total_cop or 0.0)
            new_total = max(round(old_total - delta, 2), 0.0)
            cliente.total_cop = new_total
            cliente.recaudo = round(max(valor_docto - new_total, 0.0), 2)

    elif has_total_cop:
        # Ajuste explícito de saldo total_cop => recalcular recaudo
        nuevo_total = to_float(raw_total_cop)
        if nuevo_total is not None:
            nuevo_total = max(nuevo_total, 0.0)
            # No dejar que el saldo supere el valor del documento
            if nuevo_total > valor_docto:
                nuevo_total = valor_docto
            cliente.total_cop = round(nuevo_total, 2)
            cliente.recaudo = round(max(valor_docto - nuevo_total, 0.0), 2)

    # ---- Nueva observación ----
    nueva_obs = form_data.get("observaciones")
    if nueva_obs and nueva_obs.strip():
        obs = models.Observacion(
            cliente_id=cliente.id,
            texto=nueva_obs.strip(),
        )
        db.add(obs)

    db.commit()
    return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=status.HTTP_303_SEE_OTHER)

# ------------------- historial cliente -------------------
@app.get("/cliente/{cliente_id}/historial")
def historial_cliente(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        return JSONResponse(content=[], status_code=200)

    historial = [
        {
            "texto": obs.texto,
            "fecha": obs.fecha_creacion.strftime("%d/%m/%Y %H:%M")
            if obs.fecha_creacion else None
        }
        for obs in cliente.observaciones
    ]

    return JSONResponse(content=historial, status_code=200)

# ------------------- Vista cliente -------------------
@app.get("/cliente/{cliente_id}")
def ver_cliente(cliente_id: int, request: Request, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return templates.TemplateResponse("cliente.html", {"request": request, "cliente": cliente})

# ------------------- Index agrupado -------------------
@app.get("/")
def index(
    request: Request,
    db: Session = Depends(get_db),
    view: Optional[str] = Query(None),
    min_dias: Optional[str] = Query(None),
    max_dias: Optional[str] = Query(None),
    sort: Optional[str] = Query("dias_desc"),
):
    # ---- Helpers locales ----
    def to_int_or_none(val: Optional[str]):
        try:
            return int(val) if val not in (None, "") else None
        except (ValueError, TypeError):
            return None

    min_val = to_int_or_none(min_dias)
    max_val = to_int_or_none(max_dias)

    # ---- Base query ----
    query = db.query(models.Cliente)

    # ---- Filtros de días vencidos (solo si llegan válidos) ----
    if min_val is not None:
        query = query.filter(models.Cliente.dias_vencidos >= min_val)
    if max_val is not None:
        query = query.filter(models.Cliente.dias_vencidos <= max_val)

    # ---- Ordenamiento seguro por mapa ----
    order_map = {
        "dias_desc": models.Cliente.dias_vencidos.desc(),
        "dias_asc": models.Cliente.dias_vencidos.asc(),
    }
    query = query.order_by(order_map.get(sort, order_map["dias_desc"]))

    clientes = query.all()

    # ====================================
    # VISTA PLANA
    # ====================================
    if view == "flat":
        filas = []
        for c in clientes:
            valor_docto = Decimal(str(c.valor_docto or 0))
            total_cop = Decimal(str(c.total_cop or 0))
            recaudo = valor_docto - total_cop

            filas.append({
                "id": c.id,
                "razon_social": c.razon_social,
                "nit_cliente": c.nit_cliente,
                "nro_docto_cruce": c.nro_docto_cruce,
                "dias_vencidos": c.dias_vencidos,
                "fecha_docto": c.fecha_docto,
                "fecha_vcto": c.fecha_vcto,
                "valor_docto": float(valor_docto),
                "total_cop": float(total_cop),
                "recaudo": float(recaudo),
                "asesor": c.asesor,
            })

        return templates.TemplateResponse(
            "index.html",
            {"request": request, "view": "flat", "filas": filas}
        )

    # ====================================
    # VISTA AGRUPADA
    # ====================================
    agrupados = {}
    for c in clientes:
        if c.nit_cliente not in agrupados:
            agrupados[c.nit_cliente] = {
                "nit_cliente": c.nit_cliente,
                "razon_social": c.razon_social,
                "telefono": c.telefono,
                "celular": c.celular,
                "asesor": c.asesor,
                "facturas": []
            }

        valor_docto = Decimal(str(c.valor_docto or 0))
        total_cop = Decimal(str(c.total_cop or 0))
        recaudo = valor_docto - total_cop

        agrupados[c.nit_cliente]["facturas"].append({
            "id": c.id,
            "nro_docto_cruce": c.nro_docto_cruce,
            "dias_vencidos": c.dias_vencidos,
            "fecha_docto": c.fecha_docto,
            "fecha_vcto": c.fecha_vcto,
            "valor_docto": float(valor_docto),
            "total_cop": float(total_cop),
            "recaudo": float(recaudo),
            "fecha_gestion": c.fecha_gestion,
            "tipo": c.tipo,
            "asesor": c.asesor,
            "observaciones": [obs.texto for obs in c.observaciones]
        })

    # 👉 calcular max_dias por cliente
    for cl in agrupados.values():
        dias = [f["dias_vencidos"] for f in cl["facturas"] if f["dias_vencidos"] is not None]
        cl["max_dias"] = max(dias) if dias else None

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "clientes": list(agrupados.values())}
    )







