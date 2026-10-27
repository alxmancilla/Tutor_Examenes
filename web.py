"""Interfaz web del Tutor de exámenes. Corre: python web.py y abre http://localhost:8000"""
import argparse
import inspect
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent
import herramientas

CARPETA = os.path.join(os.path.dirname(__file__), "web")
ARCHIVOS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript")}


class Corrida:
    """Estado de la escena en curso. Solo hay una a la vez: la del presentador."""

    def __init__(self, escena=None):
        self.eventos, self.estado, self.decision, self.escena = [], "libre", None, escena
        self.listo = threading.Event()

    def agregar(self, titulo, contenido, subtitulo=None, es_json=False):
        self.eventos.append({"titulo": titulo, "contenido": contenido, "subtitulo": subtitulo, "es_json": es_json})

    def pedir_aprobacion(self, plan):
        # El agente se detiene aquí hasta que alguien presione Aprobar o Rechazar en el navegador
        self.estado, self.decision = "esperando_aprobacion", None
        self.listo.clear()
        self.listo.wait()
        self.estado = "corriendo"
        return {"decisions": [{"type": "approve"} if self.decision == "s" else
                              {"type": "reject", "message": "El estudiante NO aprobó guardar el plan."}]}


corrida = Corrida()
# Conversación de la pregunta libre: se conserva en Atlas hasta presionar "Nueva conversación"
conversacion = f"web-libre-{time.time()}"


def correr_en_vivo(preguntas, hilo):
    try:
        agente = agent.crear_agente()
        for pregunta in preguntas:
            agent.ejecutar_turno(agente, pregunta, hilo, [], corrida.agregar, corrida.pedir_aprobacion)
    except Exception as e:
        corrida.agregar("Error", f"Algo falló ({type(e).__name__}). Revisa la conexión y vuelve a intentarlo.")


def memoria_guardada():
    """Lo que Atlas tiene guardado de la conversación libre."""
    estado = agent.crear_agente().get_state({"configurable": {"thread_id": conversacion}})
    mensajes = [m.text for m in estado.values.get("messages", []) if m.type == "human"]
    return {"conversacion": conversacion, "mensajes": mensajes,
            "documentos": agent.memoria().checkpoint_collection.count_documents({"thread_id": conversacion})}


def iniciar(datos):
    global corrida
    if corrida.estado in ("corriendo", "esperando_aprobacion"):
        return {"error": "Ya hay una escena corriendo."}
    escena = datos.get("escena")
    corrida = Corrida(escena)
    corrida.estado = "corriendo"
    if escena in agent.ESCENAS:
        # Cada escena empieza una conversación nueva para que siempre se vea igual
        argumentos = (agent.preguntas_de(escena), f"web-escena-{escena}-{time.time()}")
    else:
        pregunta = (datos.get("pregunta") or "").strip()
        if not pregunta:
            corrida.estado = "libre"
            return {"error": "Escribe una pregunta."}
        argumentos = ([pregunta], conversacion)
    threading.Thread(target=con_validar_de_escena, args=(escena, correr_en_vivo, argumentos), daemon=True).start()
    return {"ok": True}


def con_validar_de_escena(escena, objetivo, argumentos):
    # La escena 3 prende VALIDAR solo mientras corre; al terminar se regresa como estaba
    previo = herramientas.VALIDAR
    if escena == 3:
        herramientas.VALIDAR = True
    try:
        objetivo(*argumentos)
    finally:
        if escena == 3:
            herramientas.VALIDAR = previo
        corrida.estado = "terminado"


class Manejador(BaseHTTPRequestHandler):
    def responder(self, datos, tipo="application/json"):
        cuerpo = datos if isinstance(datos, bytes) else json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path in ARCHIVOS:
            nombre, tipo = ARCHIVOS[self.path]
            return self.responder(open(os.path.join(CARPETA, nombre), "rb").read(), tipo)
        if self.path == "/api/info":
            return self.responder({"modelo": agent.MODELO, "limite": agent.LIMITE_PASOS,
                                   "validar": herramientas.VALIDAR, "escenas": agent.ESCENAS,
                                   "codigo": inspect.getsource(herramientas.calificacion_necesaria.func)})
        if self.path.startswith("/api/eventos"):
            desde = int(self.path.split("desde=")[-1]) if "desde=" in self.path else 0
            return self.responder({"eventos": corrida.eventos[desde:], "estado": corrida.estado,
                                   "validar": herramientas.VALIDAR, "escena": corrida.escena})
        if self.path == "/api/memoria":
            try:
                return self.responder(memoria_guardada())
            except Exception as e:
                return self.responder({"error": f"No pude leer la memoria ({type(e).__name__})."})
        if self.path == "/api/revisar":
            return self.responder([{"nombre": n, "estado": e} for n, e in agent.revisiones()])
        self.send_error(404)

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        datos = json.loads(self.rfile.read(largo) or b"{}")
        if self.path == "/api/correr":
            return self.responder(iniciar(datos))
        if self.path == "/api/nueva":
            global conversacion
            if corrida.estado in ("corriendo", "esperando_aprobacion"):
                return self.responder({"error": "Espera a que termine la escena."})
            conversacion = f"web-libre-{time.time()}"
            return self.responder({"ok": True})
        if self.path == "/api/validar":
            herramientas.VALIDAR = bool(datos.get("valor"))
            return self.responder({"validar": herramientas.VALIDAR})
        if self.path == "/api/aprobar" and corrida.estado == "esperando_aprobacion":
            corrida.decision = "s" if datos.get("decision") == "s" else "n"
            corrida.listo.set()
            return self.responder({"ok": True})
        self.send_error(404)

    def log_message(self, *args):
        pass  # sin ruido en la terminal


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Interfaz web del Tutor de exámenes")
    p.add_argument("--puerto", type=int, default=8000)
    puerto = p.parse_args().puerto
    print(f"Tutor de exámenes en http://localhost:{puerto}  (Ctrl+C para salir)")
    try:
        ThreadingHTTPServer(("127.0.0.1", puerto), Manejador).serve_forever()
    except KeyboardInterrupt:
        print("Hasta luego.")
