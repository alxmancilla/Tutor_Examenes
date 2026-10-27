"""Tutor de exámenes: agente de demostración con traza visible en la terminal."""
import argparse
import json
import os
import time
from functools import cache

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelCallLimitMiddleware
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

import herramientas
from herramientas import HERRAMIENTAS, a_json, bd, buscar

MODELO, LIMITE_PASOS = "claude-opus-5-5", 6
MEMORIA_HORAS = 24  # la memoria guardada en Atlas se borra sola después de este tiempo
consola = Console()
ESCENAS = {
    1: "¿Qué temas vienen en el examen de Biología y qué dice mi apunte de fotosíntesis?",
    2: "Saqué 8, 9 y 150 en los parciales. ¿Qué necesito en el final para terminar con 8?",
    3: "Saqué 8, 9 y 150 en los parciales. ¿Qué necesito en el final para terminar con 8?",
    4: "Organiza mi semana de exámenes",
    5: "¿Quién va a ganar el próximo Mundial?",
    6: "¿Me recomiendas una bebida para estudiar?",
    7: ["Me cuesta mucho Matemáticas.", "Organiza mi semana de exámenes"],
}


def preguntas_de(escena):
    """Una escena puede tener una pregunta o varias seguidas en la misma conversación."""
    preguntas = ESCENAS[escena]
    return preguntas if isinstance(preguntas, list) else [preguntas]
PROMPT = """Eres el Tutor de exámenes, un tutor amable para estudiantes de preparatoria en México.
Reglas:
- Responde SOLO con información de tus herramientas. Usa ver_calendario para fechas y temas,
  y buscar_apuntes para el contenido de las materias.
- Cuando uses apuntes, cita la fuente entre paréntesis, por ejemplo (Apuntes de Biología, unidad 2).
- Si la información no está en tus fuentes, dilo claramente: "No tengo esa información en mis fuentes".
  Nunca adivines.
- Para calcular calificaciones usa SIEMPRE calificacion_necesaria con los números exactamente como
  los dio el estudiante, sin corregirlos ni revisarlos tú: la herramienta es la que valida.
  Después comunica el resultado de la herramienta.
- Si te piden organizar la semana, consulta ver_calendario y, en la misma respuesta, buscar_apuntes
  una vez por materia. Arma un plan breve día por día con un dato clave de cada apunte y llama a
  guardar_plan con ese plan. Si un tema no salió en los fragmentos, búscalo por separado antes de
  decir que no está en tus fuentes.
  El sistema le pedirá permiso al estudiante; nunca se guarda nada sin su aprobación.
- Recuerda lo que el estudiante te dijo antes en esta conversación (por ejemplo, qué materia le
  cuesta) y úsalo para ajustar tus respuestas y tus planes. Si solo te cuenta algo, contesta breve.
- Respuestas cortas: máximo 6 líneas, en español de México, texto plano sin Markdown ni emojis."""
COLORES = {"Pregunta": "cyan", "Fragmentos encontrados": "magenta", "Llamada a herramienta": "yellow",
           "Resultado de la herramienta": "blue", "Aprobación humana": "red", "Respuesta": "green",
           "Memoria": "white", "Error": "red"}


def mostrar(titulo, contenido, subtitulo=None, es_json=False):
    cuerpo = Syntax(contenido, "json", theme="ansi_dark", word_wrap=True) if es_json else f"[bold]{contenido}[/]"
    consola.print(Panel(cuerpo, title=f"[bold]{titulo}[/]", subtitle=subtitulo,
                        border_style=COLORES[titulo], padding=(1, 2)))


def modelo():
    return ChatAnthropic(model=MODELO, effort="low", max_tokens=2000, timeout=60, max_retries=2,
                         api_key=os.environ["AI_GATEWAY_API_KEY"], base_url=os.environ["ANTHROPIC_BASE_URL"])


@cache
def memoria():
    # La memoria del agente vive en Atlas: tutor_demo.checkpoints y tutor_demo.checkpoint_writes.
    # Con ttl, Atlas borra solo cada documento 24 horas después de guardarlo (índice TTL).
    return MongoDBSaver(bd().client, db_name=herramientas.BD, ttl=MEMORIA_HORAS * 3600)


def crear_agente():
    return create_agent(modelo(), HERRAMIENTAS, system_prompt=PROMPT, checkpointer=memoria(), middleware=[
        HumanInTheLoopMiddleware(interrupt_on={"guardar_plan": {"allowed_decisions": ["approve", "reject"]}}),
        ModelCallLimitMiddleware(run_limit=LIMITE_PASOS, exit_behavior="end")])


def eventos_de(mensaje):
    """Convierte un mensaje del agente en eventos de la traza (titulo, contenido, subtitulo, es_json)."""
    if mensaje.type == "ai":
        for llamada in mensaje.tool_calls:
            yield ("Llamada a herramienta", a_json({"herramienta": llamada["name"], "argumentos": llamada["args"]}),
                   "El modelo solo PIDE la llamada; nuestro programa la ejecuta", True)
        if mensaje.text.strip() and not mensaje.tool_calls:
            yield ("Respuesta", mensaje.text.strip(), None, False)
    elif mensaje.type == "tool" and mensaje.name in ("buscar_apuntes", "recomendar_bebida"):
        lineas = [f"{i}. {f['texto']}\n   Fuente: {f['fuente']}\n   Similitud: {f['similitud']}"
                  f"  |  Relevancia (rerank): {f['relevancia']}"
                  for i, f in enumerate(json.loads(mensaje.text), 1)]
        yield ("Fragmentos encontrados", "\n\n".join(lineas), mensaje.name, False)
    elif mensaje.type == "tool" and mensaje.status == "error" and mensaje.name == "guardar_plan":
        yield ("Resultado de la herramienta", "El estudiante rechazó el plan. No se guardó nada.", mensaje.name, False)
    elif mensaje.type == "tool":
        yield ("Resultado de la herramienta", mensaje.text, mensaje.name, False)


def aprobar(plan):
    respuesta = Prompt.ask("[bold red]¿Apruebas guardar este plan? (s/n)[/]").strip().lower()
    return {"decisions": [{"type": "approve"} if respuesta == "s" else
                          {"type": "reject", "message": "El estudiante NO aprobó guardar el plan."}]}


def ejecutar_turno(agente, pregunta, hilo, traza, mostrar_evento=None, pedir_aprobacion=None):
    """Corre un turno del agente. La terminal y la web solo cambian cómo se muestra y cómo se aprueba."""
    mostrar_evento, pedir_aprobacion = mostrar_evento or mostrar, pedir_aprobacion or aprobar

    def registrar(*evento):
        traza.append(evento)
        mostrar_evento(*evento)

    registrar("Pregunta", pregunta, None, False)
    entrada, vistos = {"messages": [{"role": "user", "content": pregunta}]}, set()
    config = {"configurable": {"thread_id": hilo}, "recursion_limit": 4 * LIMITE_PASOS}
    # Lo que ya está guardado en Atlas para esta conversación
    anteriores = [m.text for m in agente.get_state(config).values.get("messages", []) if m.type == "human"]
    if anteriores:
        registrar("Memoria", "El agente recuerda lo que dijiste antes en esta conversación:\n"
                  + "\n".join(f"- {t}" for t in anteriores), "guardado en Atlas: tutor_demo.checkpoints", False)
    while entrada is not None:
        siguiente = None
        for actualizacion in agente.stream(entrada, config, stream_mode="updates"):
            for nodo, valor in actualizacion.items():
                if nodo == "__interrupt__":
                    plan = valor[0].value["action_requests"][0]["args"].get("plan", "")
                    registrar("Aprobación humana", plan, "guardar_plan espera tu permiso", False)
                    siguiente = Command(resume=pedir_aprobacion(plan))
                    traza.append(("Aprobación humana", "s" if siguiente.resume["decisions"][0]["type"] == "approve"
                                  else "n", "respuesta del estudiante", False))
                    continue
                for mensaje in (valor or {}).get("messages", []):
                    if mensaje.id not in vistos:
                        vistos.add(mensaje.id)
                        for evento in eventos_de(mensaje):
                            registrar(*evento)
        entrada = siguiente


def reproducir(n):
    ruta = f"grabaciones/escena_{n}.json"
    if not os.path.exists(ruta):
        return mostrar("Error", f"No existe la grabación {ruta}. Grábala antes con --escena {n} --grabar.")
    for titulo, contenido, subtitulo, es_json in json.load(open(ruta, encoding="utf-8")):
        time.sleep(1.2)
        if subtitulo == "respuesta del estudiante":
            consola.print(f"[bold red]¿Apruebas guardar este plan? (s/n)[/]: {contenido}")
        else:
            mostrar(titulo, contenido, subtitulo, es_json)


def revisiones():
    """Corre la revisión previa y regresa una lista de (verificación, resultado)."""
    pruebas = [(f"Variable {v}", lambda v=v: os.environ[v]) for v in
               ("AI_GATEWAY_API_KEY", "ANTHROPIC_BASE_URL", "MONGODB_URI")]
    pruebas.append(("Conexión a Atlas", lambda: bd().command("ping")))
    # Una búsqueda real prueba el índice, los embeddings automáticos y $rerank
    for c, campo in (("apuntes", "texto"), ("bebidas", "descripcion")):
        pruebas.append((f"Búsqueda + rerank en {c}", lambda c=c, campo=campo: buscar(c, campo, "estudiar")[0]))
    pruebas.append(("API de Anthropic (AI Gateway)", lambda: modelo().invoke("Responde solo: OK")))
    resultados = []
    for nombre, prueba in pruebas:
        try:
            prueba()
            resultados.append((nombre, "OK"))
        except Exception as e:
            resultados.append((nombre, f"ERROR: {type(e).__name__}"))
    return resultados


def revisar():
    tabla = Table(title="Revisión previa", show_lines=True)
    tabla.add_column("Verificación", style="bold")
    tabla.add_column("Estado", style="bold")
    for nombre, estado in revisiones():
        tabla.add_row(nombre, f"[green]{estado}[/]" if estado == "OK" else f"[red]{estado}[/]")
    consola.print(tabla)


def main():
    p = argparse.ArgumentParser(description="Tutor de exámenes")
    p.add_argument("--escena", type=int, choices=ESCENAS)
    p.add_argument("--grabar", action="store_true")
    p.add_argument("--reproducir", type=int, choices=ESCENAS)
    p.add_argument("--revisar", action="store_true")
    args = p.parse_args()
    if args.revisar:
        return revisar()
    numero = args.escena or args.reproducir
    consola.print(Panel(f"[bold]Tutor de exámenes[/]   Modelo: {MODELO}   Límite de pasos: {LIMITE_PASOS}"
                        + (f"   Escena {numero}" if numero else ""), border_style="white"))
    if args.reproducir:
        return reproducir(args.reproducir)
    if args.escena == 3:
        herramientas.VALIDAR = True
    agente, traza = crear_agente(), []
    preguntas = preguntas_de(args.escena) if args.escena else iter(lambda: Prompt.ask("\n[bold cyan]Tú[/]"), "salir")
    hilo = f"terminal-{args.escena or 'libre'}-{time.time()}"  # cada corrida empieza una conversación nueva
    for pregunta in preguntas:
        try:
            ejecutar_turno(agente, pregunta, hilo, traza)
        except Exception as e:
            mostrar("Error", f"Algo falló ({type(e).__name__}). Revisa la conexión o usa --reproducir.")
    if args.grabar and args.escena:
        os.makedirs("grabaciones", exist_ok=True)
        json.dump(traza, open(f"grabaciones/escena_{args.escena}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        consola.print("\n[bold]Hasta luego.[/]")
    except Exception as e:
        mostrar("Error", f"No pude iniciar ({type(e).__name__}). Corre: python agent.py --revisar")
