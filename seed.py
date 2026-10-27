"""Carga los datos de data/*.json en la base tutor_demo y crea los índices autoEmbed.

python seed.py           borra la base completa y la vuelve a crear
python seed.py --demo    solo borra lo que la demo cambia: planes guardados y memoria (segundos)
"""
import argparse
import json
import time

from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel
from rich.console import Console

from herramientas import BD, MODELO_EMBEDDINGS, bd, buscar

consola = Console()
VECTORIALES = {"apuntes": ("texto", ["materia"]), "bebidas": ("descripcion", [])}
MEMORIA = ["checkpoints", "checkpoint_writes"]


def reiniciar_demo():
    """Deja la demo como nueva sin tocar los datos ni los índices: borra planes y memoria."""
    borrados = bd().planes.delete_many({}).deleted_count
    for nombre in MEMORIA:
        bd()[nombre].delete_many({})
    return borrados


def cargar(nombre):
    return json.load(open(f"data/{nombre}.json", encoding="utf-8"))


def crear_indice(coleccion, campo_texto, filtros):
    # Atlas calcula los embeddings del campo de texto con Voyage AI (Automated Embedding)
    campos = [{"type": "autoEmbed", "modality": "text", "path": campo_texto, "model": MODELO_EMBEDDINGS}]
    campos += [{"type": "filter", "path": f} for f in filtros]
    modelo = SearchIndexModel(name="vector_index", type="vectorSearch", definition={"fields": campos})
    for _ in range(30):  # si el índice anterior aún se está borrando, reintentamos
        try:
            return bd()[coleccion].create_search_index(modelo)
        except OperationFailure:
            time.sleep(2)
    raise RuntimeError(f"No se pudo crear el índice de {coleccion}")


def esperar_indice(coleccion, campo_texto, limite=600):
    # Listo cuando el índice se puede consultar y ya tiene embeddings de todos los documentos
    total, inicio = bd()[coleccion].count_documents({}), time.time()
    while time.time() - inicio < limite:
        indices = list(bd()[coleccion].list_search_indexes("vector_index"))
        if indices and indices[0].get("queryable"):
            try:
                if len(buscar(coleccion, campo_texto, "prueba", k=total)) == min(total, 10):
                    return
            except OperationFailure:
                pass
        time.sleep(5)
    raise TimeoutError(f"El índice de {coleccion} no quedó listo")


def esperar_sin_indices(limite=120):
    # Al borrar la base, Atlas tarda unos segundos en quitar los índices de búsqueda
    inicio = time.time()
    while time.time() - inicio < limite:
        if not any(list(bd()[c].list_search_indexes()) for c in VECTORIALES):
            return
        time.sleep(3)


def main():
    # Desde cero: se borra la base completa (datos, índices, planes y memoria del agente)
    consola.print(f"Borrando la base [bold]{BD}[/]...")
    bd().client.drop_database(BD)
    esperar_sin_indices()
    for nombre in ["apuntes", "calendario", "reglas", "bebidas", "planes"]:
        bd().create_collection(nombre)
    bd().calendario.insert_many(cargar("calendario"))
    bd().reglas.insert_many(cargar("reglas"))
    for coleccion, (campo_texto, filtros) in VECTORIALES.items():
        bd()[coleccion].insert_many(cargar(coleccion))
        crear_indice(coleccion, campo_texto, filtros)
    for coleccion, (campo_texto, _) in VECTORIALES.items():
        consola.print(f"Esperando a que Atlas calcule los embeddings de [bold]{coleccion}[/]...")
        esperar_indice(coleccion, campo_texto)
    consola.print("[bold green]Listo: base tutor_demo cargada e índices listos.[/]")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Carga o reinicia la base tutor_demo")
    p.add_argument("--demo", action="store_true", help="solo borra planes guardados y memoria")
    if p.parse_args().demo:
        consola.print(f"[bold green]Demo reiniciada: {reiniciar_demo()} planes borrados y memoria vacía.[/]")
    else:
        main()
