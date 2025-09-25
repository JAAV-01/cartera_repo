import webbrowser
import uvicorn

if __name__ == "__main__":
    # Abrir navegador automáticamente en la app
    webbrowser.open("http://127.0.0.1:8000")
    
    # Iniciar el servidor FastAPI
    uvicorn.run("app:app", host="127.0.0.1", port=8000)
