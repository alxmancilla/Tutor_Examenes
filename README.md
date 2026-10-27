# Tutor de exámenes

Agente de IA de demostración que ayuda a un estudiante de prepa a organizar su semana de exámenes.
Usa Claude Opus 5.5 (vía AI Gateway), LangChain y MongoDB Atlas Vector Search.
Atlas calcula los embeddings por su cuenta (Automated Embedding, modelo `voyage-4`) y reordena
los resultados con Native Reranking (`$rerank`, modelo `rerank-2.5`), así que no hace falta llave de Voyage AI.

Ambas funciones están en Preview. Requisitos del clúster:

- MongoDB 8.3 o más reciente (versión "Latest" con actualizaciones automáticas).
- Native Reranking activado en **Project Settings** de Atlas.
- En clústeres dedicados (M10 o mayor), storage auto-scaling activado.

## 1. Instalación

Requiere Python 3.12 o más reciente.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # y llena las llaves
```

## 2. Cuenta de Atlas y llaves

1. Entra a https://cloud.mongodb.com y crea un clúster con MongoDB 8.3 o más reciente.
2. En **Project Settings** activa Native Reranking.
3. En **Database Access** crea un usuario con contraseña.
4. En **Network Access** agrega tu IP (o la de la red desde donde vas a correr la demo).
5. En **Connect > Drivers** copia la cadena `mongodb+srv://...` y ponla en `MONGODB_URI`.
6. Llave del AI Gateway: ponla en `AI_GATEWAY_API_KEY`. `ANTHROPIC_BASE_URL` ya viene configurada.

### Correr la demo sin costo (opcional)

La configuración principal usa un clúster de pago (por `$rerank`) y el AI Gateway. Para correrla
gratis hay que hacer tres ajustes. Revisa los precios y límites vigentes antes de usarla:
cambian con frecuencia y algunas funciones están en Preview.

| Pieza | Costo | Opción gratuita |
|---|---|---|
| Python, LangChain, página web, pruebas | Gratis (código abierto) | Ya es gratis |
| Clúster de Atlas | De pago (MongoDB 8.3+) | Clúster **M0** gratuito (512 MB, MongoDB 8.0) |
| Embeddings automáticos (`voyage-4`) | Tokens | 200 millones de tokens gratis por organización (una sola vez) |
| Reordenamiento (`$rerank`) | Tokens y clúster 8.3+ | **No existe en M0**: hay que quitarlo |
| Memoria del agente (checkpoints) | Almacenamiento | Funciona en M0 |
| Claude Opus 5.5 | Por token | Sin nivel gratuito; a través del AI Gateway de tu empresa no pagas tú |

**Pasos:**

1. **Crea un clúster M0 gratuito** en https://cloud.mongodb.com y sigue los pasos de la sección 2,
   excepto activar Native Reranking (no aplica en M0).
2. **Agrega un método de pago a la organización.** No genera cobros mientras uses los tokens
   gratuitos, pero sin tarjeta un M0 solo permite 3 búsquedas por minuto y la escena 4 hace 4
   búsquedas seguidas, así que se atoraría. Con tarjeta, el límite sube a 2,000
   por minuto. Después de probarla, revisa la página **Billing** de Atlas para confirmar $0.
3. **Quita el reordenamiento** en `herramientas.py`. Reemplaza el cuerpo de la función `buscar` por:

   ```python
   resultados = vector_store(coleccion, campo_texto).similarity_search_with_score(
       consulta, k=k, pre_filter=filtro)
   return [(d, round(s, 3), round(s, 3)) for d, s in resultados]
   ```

   Las tarjetas mostrarán el mismo número en Similitud y Relevancia. En las pruebas, el agua de
   tamarindo sale primero también sin reordenamiento.
4. **Modelo:** usa la llave del AI Gateway de tu empresa (`AI_GATEWAY_API_KEY`). Si no tienes acceso
   a uno, el costo de Claude es por uso: correr las 7 escenas cuesta, como estimación,
   menos de un dólar.
5. Corre `python seed.py` y luego `python agent.py --revisar`.

**Sin verificar en M0:** que `seed.py` pueda crear los índices desde código (si falla, créalos en
**Atlas Search** desde la interfaz con las mismas definiciones de `seed.py`) y la velocidad de las
escenas. Pruébala completa en el clúster gratuito antes de usarla.

## 3. Cargar los datos

```bash
python seed.py
```

Borra la base `tutor_demo` completa (datos, índices, planes y memoria) y la vuelve a crear:
inserta solo texto, crea los índices `autoEmbed` y espera a que Atlas termine de calcular
los embeddings y las búsquedas funcionen. Tarda alrededor de 2 minutos. Se puede correr varias veces.

### Reiniciar la demo (rápido)

```bash
python seed.py --demo
```

Borra solo lo que la demo cambia: los planes guardados y la memoria del agente. No toca los
apuntes ni los índices, así que tarda menos de un segundo. En la página web, el botón
**Reiniciar demo** hace lo mismo y además apaga VALIDAR.

En pantalla, cada fragmento muestra dos números: **Similitud** (qué tan cerca está en
`$vectorSearch`) y **Relevancia** (la calificación del reranker, que decide el orden final).

## 4. Revisión previa

```bash
python agent.py --revisar
```

Muestra OK o ERROR para las variables de entorno, Atlas, una búsqueda real con rerank en
cada colección y Anthropic.

## 5. Interfaz web

```bash
python web.py            # abre http://localhost:8000 en el navegador
```

- **Escenas:** un botón por escena. Cada paso aparece como una tarjeta grande de color.
- **Todo es en vivo:** cada escena llama al modelo y a Atlas en ese momento.
- **Interruptor VALIDAR:** muestra el código de `calificacion_necesaria` y prende o apaga la
  validación al momento, sin editar archivos.
- **Aprobación:** en la escena 4 el agente se detiene y aparecen los botones "Sí, guardar" y "No".
- **Pregunta libre** y **Revisión previa** (la misma de `--revisar`).
- La escena que corre queda resaltada. La página no se desplaza sola: usa la rueda o las flechas.
- **Aprobación:** en la escena 4 se abre una ventana al centro con el plan y los botones.
- En las escenas 2 y 3 aparece una tarjeta con el código de `calificacion_necesaria` y el valor de VALIDAR.
- Las llamadas y búsquedas seguidas se juntan en una tarjeta con "Ver todo".
- **Teclas:** `1` a `7` corren las escenas, `V` prende o apaga VALIDAR, `S` / `N` aprueban o rechazan.
- **Si algo falla**, la tarjeta de error pide revisar la conexión; vuelve a presionar la escena.
- **Si recargas la página** a mitad de una escena, la página la retoma.
- La escena 3 prende VALIDAR solo mientras corre y al terminar lo deja como estaba.
- **Memoria en MongoDB:** la conversación del agente se guarda en Atlas, en `tutor_demo.checkpoints`
  y `tutor_demo.checkpoint_writes` (con `MongoDBSaver` de `langgraph-checkpoint-mongodb`).
  - La **escena 7** hace dos preguntas seguidas ("Me cuesta mucho Matemáticas." y "Organiza mi semana")
    y el plan le da más tiempo a Matemáticas. Una tarjeta "Memoria" muestra lo que el agente recordó.
  - Las escenas 1 a 6 siempre empiezan una conversación nueva.
  - La **pregunta libre** recuerda lo anterior hasta presionar **Nueva conversación**.
  - **Ver memoria en Atlas** muestra cuántos documentos hay guardados y qué dijo el estudiante.
  - Atlas borra sola la memoria 24 horas después de guardarla (índice TTL sobre `created_at`).
    Para cambiar el tiempo, edita `MEMORIA_HORAS` en `agent.py` y corre `python seed.py`.
  - `python seed.py`, `python seed.py --demo` o el botón **Reiniciar demo** borran la memoria al momento.
- **Vista sencilla:** cada tarjeta trae una frase en español sencillo y oculta el JSON y los
  números de similitud. Activa **Ver detalles técnicos** para mostrar los datos completos.

Solo escucha en tu computadora (`127.0.0.1`). Usa `--puerto 8080` si el 8000 está ocupado.

## 6. Escenas en la terminal

| Comando | Qué muestra |
|---|---|
| `python agent.py --escena 1` | Calendario + apuntes con cita de la fuente |
| `python agent.py --escena 2` | Calificación 150: la herramienta da un resultado absurdo |
| `python agent.py --escena 3` | Misma pregunta con `VALIDAR = True`: rechaza el 150 |
| `python agent.py --escena 4` | Plan de la semana y aprobación humana antes de guardar |
| `python agent.py --escena 5` | Pregunta fuera de sus fuentes: dice que no tiene la información |
| `python agent.py --escena 6` | Búsqueda semántica: recomienda agua de tamarindo |
| `python agent.py` | Modo interactivo (escribe `salir` para terminar) |

La escena 3 activa la validación por sí sola. Para hacerlo a mano, cambia
`VALIDAR = False` a `VALIDAR = True` en `herramientas.py` y corre la escena 2 otra vez.

## 7. Grabar y reproducir (respaldo sin internet)

Atlas consulta a Voyage AI en cada búsqueda, así que sin red solo funciona la reproducción.

```bash
python agent.py --escena 1 --grabar     # guarda grabaciones/escena_1.json
python agent.py --reproducir 1          # repite la traza sin llamadas a la red
```

## 8. Pruebas

```bash
pytest -q
```
