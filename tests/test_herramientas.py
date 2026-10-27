import os
import sys
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import agent
import herramientas


def calcular(parciales, meta):
    return herramientas.calificacion_necesaria.invoke({"parciales": parciales, "meta": meta})


def test_sin_validacion_da_resultado_absurdo(monkeypatch):
    monkeypatch.setattr(herramientas, "VALIDAR", False)
    # promedio 55.67 -> (8 - 0.6*55.67)/0.4 = -63.50
    assert "-63.50" in calcular([8, 9, 150], 8)


def test_con_validacion_rechaza_fuera_de_rango(monkeypatch):
    monkeypatch.setattr(herramientas, "VALIDAR", True)
    assert "entre 0 y 10" in calcular([8, 9, 150], 8)


def test_con_validacion_calcula_caso_normal(monkeypatch):
    monkeypatch.setattr(herramientas, "VALIDAR", True)
    # promedio 8.5 -> (8 - 5.1)/0.4 = 7.25
    assert "7.25" in calcular([8, 9], 8)


class ModeloFalso(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture(autouse=True)
def memoria_local(monkeypatch):
    # Las pruebas no tocan Atlas: la memoria vive en RAM
    from langgraph.checkpoint.memory import InMemorySaver
    saver = InMemorySaver()
    monkeypatch.setattr(agent, "memoria", lambda: saver)


def test_memoria_recuerda_turno_anterior(monkeypatch):
    falso = ModeloFalso(messages=iter([AIMessage(content="Entendido."), AIMessage(content="Plan con más Matemáticas."),
                                       AIMessage(content="Hola.")]))
    monkeypatch.setattr(agent, "modelo", lambda: falso)
    agente, traza = agent.crear_agente(), []
    agent.ejecutar_turno(agente, "Me cuesta mucho Matemáticas.", "prueba-memoria", traza)
    assert "Memoria" not in [e[0] for e in traza]
    agent.ejecutar_turno(agente, "Organiza mi semana", "prueba-memoria", traza)
    memoria = [e for e in traza if e[0] == "Memoria"]
    assert len(memoria) == 1 and "Me cuesta mucho Matemáticas." in memoria[0][1]
    otra = []
    agent.ejecutar_turno(agente, "Hola", "otra-conversacion", otra)
    assert "Memoria" not in [e[0] for e in otra]


@pytest.mark.parametrize("respuesta,guardado", [("n", False), ("x", False), ("s", True)])
def test_guardar_plan_solo_con_aprobacion(monkeypatch, respuesta, guardado):
    base = MagicMock()
    monkeypatch.setattr(herramientas, "bd", lambda: base)
    monkeypatch.setattr(agent.Prompt, "ask", lambda *a, **k: respuesta)
    llamada = {"name": "guardar_plan", "args": {"plan": "Lunes: Biología"}, "id": "1", "type": "tool_call"}
    falso = ModeloFalso(messages=iter([AIMessage(content="", tool_calls=[llamada]), AIMessage(content="Listo.")]))
    monkeypatch.setattr(agent, "modelo", lambda: falso)
    agent.ejecutar_turno(agent.crear_agente(), "Organiza mi semana", "prueba", [])
    assert base.planes.insert_one.called is guardado


@pytest.mark.parametrize("decision,guardado", [("n", False), ("s", True)])
def test_web_guarda_solo_con_boton_aprobar(monkeypatch, decision, guardado):
    import threading
    import time
    import web

    base = MagicMock()
    monkeypatch.setattr(herramientas, "bd", lambda: base)
    llamada = {"name": "guardar_plan", "args": {"plan": "Lunes: Biología"}, "id": "1", "type": "tool_call"}
    falso = ModeloFalso(messages=iter([AIMessage(content="", tool_calls=[llamada]), AIMessage(content="Listo.")]))
    monkeypatch.setattr(agent, "modelo", lambda: falso)
    monkeypatch.setattr(web, "corrida", web.Corrida())
    hilo = threading.Thread(target=web.con_validar_de_escena,
                            args=(None, web.correr_en_vivo, (["Organiza mi semana"], "prueba-web")))
    hilo.start()
    while web.corrida.estado != "esperando_aprobacion":
        time.sleep(0.05)
    assert not base.planes.insert_one.called
    web.corrida.decision = decision
    web.corrida.listo.set()
    hilo.join(timeout=10)
    assert base.planes.insert_one.called is guardado
    assert web.corrida.estado == "terminado"


def test_escena_3_regresa_validar_como_estaba(monkeypatch):
    import web

    monkeypatch.setattr(herramientas, "VALIDAR", False)
    monkeypatch.setattr(web, "corrida", web.Corrida(3))
    durante = []
    web.con_validar_de_escena(3, lambda: durante.append(herramientas.VALIDAR), ())
    assert durante == [True]
    assert herramientas.VALIDAR is False
    assert web.corrida.estado == "terminado"
