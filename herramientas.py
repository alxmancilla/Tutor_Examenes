"""Herramientas del Tutor de exámenes. El modelo lee los docstrings para decidir cuál usar."""
import json
import os
from datetime import datetime
from functools import cache

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_mongodb.pipelines import rerank_stage
from pymongo import MongoClient

load_dotenv()
BD = "tutor_demo"
# Atlas genera los embeddings (autoEmbed) y reordena con $rerank: no necesitamos llave de Voyage
MODELO_EMBEDDINGS, MODELO_RERANK, CANDIDATOS = "voyage-4", "rerank-2.5", 10
REGLAS = json.load(open(os.path.join(os.path.dirname(__file__), "data", "reglas.json")))[0]

# Interruptor para la demo en vivo: cámbialo a True para validar calificaciones
VALIDAR = False


@cache
def bd():
    cliente = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=8000, timeoutMS=20000)
    return cliente[BD]


def vector_store(coleccion, campo_texto):
    return MongoDBAtlasVectorSearch(bd()[coleccion], MODELO_EMBEDDINGS, index_name="vector_index",
                                    text_key=campo_texto, embedding_key=None, relevance_score_fn=None,
                                    auto_create_index=False)


def buscar(coleccion, campo_texto, consulta, filtro=None, k=3):
    """$vectorSearch trae candidatos, $rerank los reordena y nos quedamos con los k mejores."""
    reordenar = [{"$set": {"similitud": "$score"}},
                 *rerank_stage(consulta, campo_texto, CANDIDATOS, MODELO_RERANK), {"$limit": k}]
    resultados = vector_store(coleccion, campo_texto).similarity_search_with_score(
        consulta, k=CANDIDATOS, pre_filter=filtro, post_filter_pipeline=reordenar)
    return [(d, round(d.metadata["similitud"], 3), round(s, 3)) for d, s in resultados]


def a_json(datos):
    return json.dumps(datos, ensure_ascii=False, indent=2)


@tool
def buscar_apuntes(pregunta: str, materia: str | None = None) -> str:
    """Busca en los apuntes de clase del estudiante los 3 fragmentos más parecidos a la pregunta.
    Úsala para cualquier duda sobre el contenido de una materia.
    materia (opcional) debe ser exactamente "Biología", "Matemáticas" o "Historia de México".
    Cada fragmento trae su fuente, que debes citar en tu respuesta."""
    filtro = {"materia": materia} if materia else None
    return a_json([{"texto": d.page_content, "fuente": d.metadata["fuente"], "similitud": sim, "relevancia": rel}
                   for d, sim, rel in buscar("apuntes", "texto", pregunta, filtro)])


@tool
def ver_calendario() -> str:
    """Devuelve el calendario de exámenes de la semana: fecha, día, materia y temas que vienen."""
    return a_json(list(bd().calendario.find({}, {"_id": 0}).sort("fecha", 1)))


@tool
def calificacion_necesaria(parciales: list[float], meta: float) -> str:
    """Calcula qué calificación necesita el estudiante en el examen final para terminar con la meta.
    parciales: calificaciones de los exámenes parciales. meta: calificación final deseada.
    Regla: final = 60% promedio de parciales + 40% examen final, en escala de 0 a 10."""
    if VALIDAR:
        if any(not 0 <= c <= 10 for c in [*parciales, meta]):
            return "No puedo calcularlo: las calificaciones deben estar entre 0 y 10. Revisa tus datos."
    promedio = sum(parciales) / len(parciales)
    necesaria = (meta - REGLAS["peso_parciales"] * promedio) / REGLAS["peso_final"]
    return f"Promedio de parciales: {promedio:.2f}. Necesitas {necesaria:.2f} en el examen final."


@tool
def guardar_plan(plan: str) -> str:
    """Guarda el plan de estudio del estudiante en la base de datos.
    Solo se ejecuta si el estudiante lo aprueba en la terminal."""
    bd().planes.insert_one({"plan": plan, "creado": datetime.now()})
    return "Plan guardado."


@tool
def recomendar_bebida(gusto: str) -> str:
    """Recomienda una bebida según lo que se le antoja al estudiante (por ejemplo "algo fresco").
    Devuelve las bebidas más parecidas a su gusto."""
    return a_json([{"texto": d.page_content, "fuente": d.metadata["nombre"], "similitud": sim, "relevancia": rel}
                   for d, sim, rel in buscar("bebidas", "descripcion", gusto)])


HERRAMIENTAS = [buscar_apuntes, ver_calendario, calificacion_necesaria, guardar_plan, recomendar_bebida]
