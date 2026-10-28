// Interfaz del Tutor de exámenes: pide eventos al servidor y los dibuja como tarjetas
const $ = (id) => document.getElementById(id);
const CLASES = { "Pregunta": "Pregunta", "Fragmentos encontrados": "Fragmentos", "Llamada a herramienta": "Llamada",
  "Resultado de la herramienta": "Resultado", "Aprobación humana": "Aprobacion", "Respuesta": "Respuesta",
  "Memoria": "Memoria", "Error": "Error" };
const NOMBRES = { 1: "Calendario + apuntes", 2: "Calificación con 150", 3: "Misma pregunta con VALIDAR",
  4: "Organiza mi semana (aprobación)", 5: "Pregunta fuera de sus fuentes", 6: "Recomienda una bebida",
  7: "Memoria: me cuesta Matemáticas" };
// Frase corta en español sencillo para cada tipo de tarjeta
const LEYENDAS = {
  "Pregunta": "Esto es lo que preguntó el estudiante.",
  "Llamada a herramienta": "El modelo no hace la acción: solo la pide. Nuestro programa la ejecuta.",
  "Fragmentos encontrados": "El programa buscó en los apuntes y trae lo más parecido, con su fuente.",
  "Resultado de la herramienta": "Esto regresó nuestro programa. El modelo lo lee para contestar.",
  "Aprobación humana": "El agente se detiene. Una persona decide si se guarda.",
  "Respuesta": "La respuesta final, armada solo con lo que encontró.",
  "Memoria": "El agente lee de MongoDB lo que ya le dijiste en esta conversación.",
  "Error": "Algo falló. Revisa la conexión y vuelve a intentarlo.",
};
let vistos = 0, sondeo = null, codigo = "", eventos = [], detalles = false;
let escenaCorriendo = null, estadoActual = "libre", validarActual = false, firma = "", dibujados = 0;
let previos = [], ultimaLibre = false;  // mensajes anteriores de la conversación libre
const botonesEscena = {};

async function api(ruta, datos) {
  const opciones = datos ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) } : {};
  const r = await fetch(ruta, opciones);
  return r.json();
}

function texto(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

function codigoHtml() {
  // Resalta el bloque de validación para que el público vea qué cambia
  return codigo.split("\n").map((l) =>
    /VALIDAR|0 <= c <= 10|No puedo calcularlo/.test(l) ? `<span class="resaltado">${texto(l)}</span>` : texto(l)).join("\n");
}

function dibujarCodigo(validar) {
  $("codigo").innerHTML = codigoHtml();
  $("validar").checked = validar;
  $("validarTexto").textContent = validar ? "activada" : "apagada";
}

function valor(v) { return Array.isArray(v) ? v.join(", ") : String(v); }

function sencillo(e) {
  // Versión para el público: sin JSON ni números de similitud
  try {
    if (e.titulo === "Llamada a herramienta") {
      const { herramienta, argumentos } = JSON.parse(e.contenido);
      if (herramienta === "guardar_plan") return "El modelo pidió: guardar_plan (necesita tu permiso)";
      const args = Object.entries(argumentos).map(([k, v]) => `${k}: ${valor(v)}`).join("  |  ");
      return `El modelo pidió: ${herramienta}` + (args ? `\n${args}` : "");
    }
    if (e.titulo === "Fragmentos encontrados")
      return e.contenido.split("\n").filter((l) => !/Similitud:/.test(l)).join("\n");
    if (e.titulo === "Resultado de la herramienta" && e.subtitulo === "ver_calendario")
      return JSON.parse(e.contenido).map((x) => `${x.dia} ${x.fecha.slice(8)}: ${x.materia} (${x.temas.join(", ")})`).join("\n");
  } catch (_) { /* si no se puede simplificar, se muestra tal cual */ }
  return e.contenido;
}

// Títulos cortos de los pasos, como el uso de herramientas en ChatGPT o Claude
const RESUMEN = {
  "Llamada a herramienta": "Pidió usar una herramienta", "Fragmentos encontrados": "Buscó en los apuntes",
  "Resultado de la herramienta": "Resultado de la herramienta", "Aprobación humana": "Esperó tu permiso",
  "Memoria": "Recordó la conversación",
};

function mensaje(clase, contenido) {
  // Burbuja del estudiante o respuesta del agente
  const div = document.createElement("div");
  div.className = "msg " + clase;
  div.innerHTML = (clase === "usuario" ? "" : `<div class="avatar">TE</div>`) + `<div class="texto">${texto(contenido)}</div>`;
  return div;
}

function base(titulo, clase, paso, abierto) {
  // Paso intermedio: bloque compacto que se abre y se cierra
  const det = document.createElement("details");
  det.className = "panel paso-bloque " + clase;
  if (abierto) det.open = true;
  det.innerHTML = `<summary>${paso ? `<span class="paso">${paso}</span>` : ""}${texto(titulo)}</summary>` +
    `<div class="cuerpo">${LEYENDAS[titulo] ? `<div class="leyenda">${texto(LEYENDAS[titulo])}</div>` : ""}</div>`;
  return det;
}

function tarjeta(e, paso) {
  if (e.titulo === "Pregunta") return mensaje("usuario", e.contenido);
  if (e.titulo === "Respuesta") return mensaje("agente", e.contenido);
  if (e.titulo === "Error") return mensaje("agente error", e.contenido);
  let titulo = RESUMEN[e.titulo] || e.titulo;
  if (e.titulo === "Llamada a herramienta") {
    try { titulo = `Pidió usar ${JSON.parse(e.contenido).herramienta}`; } catch (_) { /* título genérico */ }
  } else if (e.subtitulo && e.titulo !== "Aprobación humana" && e.titulo !== "Memoria") {
    titulo += ` · ${e.subtitulo}`;
  }
  const det = base(titulo, CLASES[e.titulo] || "Resultado", paso, true);
  const crudo = detalles && e.es_json;
  det.querySelector(".cuerpo").insertAdjacentHTML("beforeend",
    `<pre class="${crudo ? "json" : ""}">${texto(detalles ? e.contenido : sencillo(e))}</pre>` +
    (detalles && e.subtitulo ? `<div class="sub">${texto(e.subtitulo)}</div>` : ""));
  return det;
}

function agrupar(lista) {
  // En la vista sencilla, las llamadas y búsquedas seguidas se juntan en una sola tarjeta
  const grupos = [];
  lista.forEach((e) => {
    const ultimo = grupos[grupos.length - 1];
    const juntable = !detalles && ["Llamada a herramienta", "Fragmentos encontrados"].includes(e.titulo);
    if (juntable && ultimo && ultimo[0].titulo === e.titulo) ultimo.push(e);
    else grupos.push([e]);
  });
  return grupos;
}

function tarjetaGrupo(grupo, paso) {
  if (grupo.length === 1) return tarjeta(grupo[0], paso);
  const e = grupo[0];
  let titulo, resumen;
  if (e.titulo === "Llamada a herramienta") {
    titulo = `Pidió ${grupo.length} herramientas`;
    resumen = grupo.map((x) => "- " + sencillo(x).replace("El modelo pidió: ", "").replace("\n", ": ")).join("\n");
  } else {
    const fuentes = [...new Set(grupo.flatMap((x) => x.contenido.split("\n")
      .filter((l) => l.includes("Fuente:")).map((l) => l.split("Fuente:")[1].trim())))];
    titulo = `Hizo ${grupo.length} búsquedas en los apuntes`;
    resumen = "Fuentes:\n" + fuentes.map((f) => "- " + f).join("\n");
  }
  const det = base(titulo, CLASES[e.titulo], paso, true);
  det.querySelector(".cuerpo").insertAdjacentHTML("beforeend", `<div class="leyenda">${texto(LEYENDAS[e.titulo])}</div>` +
    `<pre>${texto(resumen)}</pre><details><summary>Ver todo</summary><pre>${texto(grupo.map(sencillo).join("\n\n"))}</pre></details>`);
  return det;
}

function tarjetaCodigo() {
  // En las escenas 2 y 3 el público ve el código que cambia el interruptor VALIDAR
  const det = base(`Nuestro código: VALIDAR = ${validarActual ? "True" : "False"}`, "Codigo", null, true);
  det.querySelector(".cuerpo").insertAdjacentHTML("beforeend", `<div class="leyenda">${validarActual
    ? "La validación está prendida: el programa revisa que las calificaciones estén entre 0 y 10."
    : "La validación está apagada: el programa calcula con cualquier número."}</div><pre class="codigo">${codigoHtml()}</pre>`);
  return det;
}

function bienvenida() {
  const div = document.createElement("div");
  div.className = "bienvenida";
  div.innerHTML = "<h2>¿En qué te ayudo esta semana?</h2>Elige una escena a la izquierda o escribe tu pregunta abajo.";
  return div;
}

function dibujar() {
  const traza = $("traza");
  // Los bloques que el presentador abrió o cerró se quedan así al redibujar
  const estadoAbierto = [...traza.querySelectorAll("details.paso-bloque")].map((d) => d.open);
  traza.innerHTML = "";
  const todos = previos.concat(eventos);
  if (!todos.length && estadoActual !== "corriendo") { traza.appendChild(bienvenida()); return; }
  if (escenaCorriendo === 2 || escenaCorriendo === 3) traza.appendChild(tarjetaCodigo());
  const grupos = agrupar(todos);
  let paso = 0;  // solo se numeran los pasos del agente, no los mensajes
  grupos.forEach((g, i) => {
    const esMensaje = ["Pregunta", "Respuesta", "Error"].includes(g[0].titulo);
    if (g[0].titulo === "Pregunta") paso = 0;
    const t = tarjetaGrupo(g, esMensaje ? null : ++paso);
    if (i >= dibujados) t.classList.add("nuevo");
    traza.appendChild(t);
  });
  [...traza.querySelectorAll("details.paso-bloque")].forEach((d, i) => {
    if (i < estadoAbierto.length) d.open = estadoAbierto[i];
  });
  dibujados = grupos.length;
  if (estadoActual === "corriendo") {
    const p = document.createElement("div");
    p.className = "msg agente";
    p.innerHTML = `<div class="avatar">TE</div><div class="escribiendo"><span></span><span></span><span></span></div>`;
    traza.appendChild(p);
  }
}

function limpiar() {
  $("traza").innerHTML = "";
  eventos = []; previos = []; ultimaLibre = false;
  firma = ""; dibujados = 0; estadoActual = "libre"; escenaCorriendo = null;
}

function redibujar() { dibujados = 0; dibujar(); }

function mostrarAprobacion() {
  // Pausa visible: el agente se detuvo y una persona decide
  const plan = [...eventos].reverse().find((e) => e.titulo === "Aprobación humana")?.contenido || "";
  const div = document.createElement("div");
  div.className = "overlay";
  div.id = "aprobar";
  div.innerHTML = `<div class="caja"><h2>El agente se detuvo</h2>
    <p>Quiere guardar este plan. Nada se guarda sin tu permiso.</p><pre>${texto(plan)}</pre>
    <div class="botones"><button class="si">Sí, guardar (S)</button><button class="no">No (N)</button></div></div>`;
  div.querySelector(".si").onclick = () => decidir("s");
  div.querySelector(".no").onclick = () => decidir("n");
  document.body.appendChild(div);
}

async function decidir(decision) {
  $("aprobar")?.remove();
  await api("/api/aprobar", { decision });
}

function bloquear(si) {
  document.querySelectorAll("aside button").forEach((b) => (b.disabled = si));
  $("enviar").disabled = si;
  if (!si) Object.values(botonesEscena).forEach((b) => b.classList.remove("activa"));
}

async function revisarEventos() {
  const r = await api(`/api/eventos?desde=${vistos}`);
  escenaCorriendo = r.escena;
  eventos.push(...r.eventos.filter((e) => e.subtitulo !== "respuesta del estudiante"));
  vistos += r.eventos.length;
  estadoActual = r.estado;
  validarActual = r.validar;
  if (r.estado !== "terminado") botonesEscena[r.escena]?.classList.add("activa");
  dibujarCodigo(r.validar);
  const nueva = `${eventos.length}|${r.estado}|${r.validar}`;
  if (nueva !== firma) {
    firma = nueva;
    dibujar();
  }
  if (r.estado === "esperando_aprobacion" && !$("aprobar")) mostrarAprobacion();
  if (r.estado === "terminado" || r.estado === "libre") {
    clearInterval(sondeo);
    bloquear(false);
  }
}

function empezarSondeo() {
  bloquear(true);
  clearInterval(sondeo);
  sondeo = setInterval(revisarEventos, 500);
  revisarEventos();
}

async function correr(datos) {
  const r = await api("/api/correr", datos);
  if (r.error) { $("estado").textContent = r.error; return; }
  $("estado").textContent = "";
  // La pregunta libre sigue la misma conversación: los mensajes anteriores se quedan en pantalla
  const libre = !datos.escena;
  previos = libre && ultimaLibre ? previos.concat(eventos) : [];
  ultimaLibre = libre;
  vistos = 0;
  eventos = [];
  firma = "";
  dibujados = 0;
  escenaCorriendo = datos.escena || null;
  empezarSondeo();
  botonesEscena[datos.escena]?.classList.add("activa");
}

function presentar(si) { document.body.classList.toggle("presentacion", si); }

function atajos(e) {
  // Teclas para el escenario: 1-7 escenas, V validar, S/N aprobar, P presentación
  if (["TEXTAREA", "INPUT"].includes(e.target.tagName) && e.target.type !== "checkbox") return;
  const tecla = e.key.toLowerCase();
  if ((tecla === "s" || tecla === "n") && $("aprobar")) decidir(tecla);
  else if (tecla === "escape") presentar(false);
  else if (tecla === "p") presentar(!document.body.classList.contains("presentacion"));
  else if (sondeo_activo()) return;
  else if (/^[1-7]$/.test(tecla)) correr({ escena: Number(tecla) });
  else if (tecla === "v") $("validar").click();
}

function sondeo_activo() { return document.querySelector("aside button")?.disabled; }

function enviarPregunta() {
  const pregunta = $("pregunta").value.trim();
  if (!pregunta || sondeo_activo()) return;
  $("pregunta").value = "";
  crecer();
  correr({ pregunta });
}

function crecer() {
  // La caja de mensaje crece con el texto, como en ChatGPT
  const t = $("pregunta");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 200) + "px";
}

async function revisar() {
  limpiar();
  $("estado").textContent = "Revisando conexiones...";
  const filas = await api("/api/revisar");
  const div = document.createElement("div");
  div.className = "panel Resultado";
  div.innerHTML = "<h3>Revisión previa</h3><table class='tabla'>" + filas.map((f) =>
    `<tr><td>${texto(f.nombre)}</td><td class="${f.estado === "OK" ? "ok" : "falla"}">${texto(f.estado)}</td></tr>`).join("") + "</table>";
  $("traza").appendChild(div);
  $("estado").textContent = "";
}

async function verMemoria() {
  // Muestra lo que Atlas tiene guardado de la conversación libre
  limpiar();
  $("estado").textContent = "";
  const m = await api("/api/memoria");
  const div = document.createElement("div");
  div.className = "panel Memoria";
  div.innerHTML = m.error ? `<h3>Memoria en Atlas</h3><pre>${texto(m.error)}</pre>` :
    `<h3>Memoria en Atlas</h3><div class="leyenda">Base tutor_demo, colección checkpoints: ` +
    `${m.documentos} documentos para esta conversación.</div><pre>${texto(m.mensajes.length
      ? "Lo que el agente recuerda que dijiste:\n" + m.mensajes.map((t) => "- " + t).join("\n")
      : "Todavía no hay nada guardado. Haz una pregunta libre.")}</pre>`;
  $("traza").appendChild(div);
}

async function reiniciarDemo() {
  // Borra planes guardados y memoria en Atlas, y apaga VALIDAR: la demo queda como nueva
  if (!confirm("¿Reiniciar la demo? Se borran los planes guardados y la memoria del agente.")) return;
  $("estado").textContent = "Reiniciando...";
  const r = await api("/api/reiniciar", {});
  if (r.error) { $("estado").textContent = r.error; return; }
  limpiar();
  dibujar();
  $("detalles").checked = detalles = false;
  dibujarCodigo(false);
  $("estado").textContent = `Demo reiniciada: ${r.planes} planes borrados, memoria vacía y VALIDAR apagado.`;
}

async function nuevaConversacion() {
  const r = await api("/api/nueva", {});
  $("estado").textContent = r.error || "Conversación nueva: el agente ya no recuerda lo anterior.";
  if (!r.error) { limpiar(); dibujar(); }
}

async function iniciar() {
  const info = await api("/api/info");
  $("modelo").textContent = info.modelo;
  $("limite").textContent = info.limite;
  codigo = info.codigo;
  dibujarCodigo(info.validar);
  Object.keys(info.escenas).forEach((n) => {
    const b = document.createElement("button");
    b.textContent = `${n}. ${NOMBRES[n]}`;
    b.onclick = () => correr({ escena: Number(n) });
    botonesEscena[n] = b;
    $("escenas").appendChild(b);
  });
  $("presentar").onclick = () => presentar(true);
  $("salirPresentacion").onclick = () => presentar(false);
  $("validar").onchange = async (e) => dibujarCodigo((await api("/api/validar", { valor: e.target.checked })).validar);
  $("enviar").onclick = enviarPregunta;
  $("pregunta").addEventListener("input", crecer);
  $("pregunta").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarPregunta(); }
  });
  $("revisar").onclick = revisar;
  $("verMemoria").onclick = verMemoria;
  $("nueva").onclick = nuevaConversacion;
  $("reiniciar").onclick = reiniciarDemo;
  $("detalles").onchange = (e) => { detalles = e.target.checked; redibujar(); };
  document.addEventListener("keydown", atajos);
  // Si se recargó la página a mitad de una escena, retomarla
  const actual = await api("/api/eventos?desde=0");
  if (actual.estado === "corriendo" || actual.estado === "esperando_aprobacion") empezarSondeo();
  else dibujar();
}

iniciar();
