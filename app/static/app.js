"use strict";

const form = document.getElementById("analyze-form");
const message = document.getElementById("message");
const counter = document.getElementById("character-count");
const analyzeButton = document.getElementById("analyze-button");
const clearButton = document.getElementById("clear-button");
const result = document.getElementById("result");
const error = document.getElementById("error");
const loading = document.getElementById("loading");
const notice = document.getElementById("model-notice");
let busy = false;

function updateCount() {
  counter.textContent = `${message.value.length.toLocaleString("es-ES")} / 5.000`;
}
message.addEventListener("input", () => {
  updateCount();
  // Evitar que un resultado anterior parezca corresponder al texto recién editado.
  result.hidden = true;
  error.hidden = true;
});

function reset() {
  if (busy) return;
  message.value = "";
  updateCount();
  result.hidden = true;
  error.hidden = true;
  message.focus();
}
clearButton.addEventListener("click", reset);
document.getElementById("another-button").addEventListener("click", reset);

function showError(text) {
  error.textContent = text;
  error.hidden = false;
}

function render(data) {
  result.dataset.level = data.nivel;
  result.dataset.uncertain = String(data.incertidumbre);
  document.getElementById("category").textContent = data.categoria;
  document.getElementById("result-icon").textContent = data.incertidumbre ? "⚠" : { bajo: "ⓘ", alto: "⛔" }[data.nivel];
  const uncertainty = document.getElementById("uncertainty-warning");
  uncertainty.textContent = data.aviso_incertidumbre || "";
  uncertainty.hidden = !data.incertidumbre;
  document.getElementById("explanation").textContent = data.explicacion;
  document.getElementById("demo-warning").hidden = !data.datos_demostrativos;
  const signals = document.getElementById("signals");
  signals.replaceChildren();
  if (!data.senales.length) {
    const item = document.createElement("li");
    item.textContent = "No se detectaron las señales previstas por las reglas. Esto no garantiza seguridad.";
    signals.append(item);
  }
  for (const signal of data.senales) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = signal.titulo;
    const description = document.createElement("span");
    description.textContent = signal.descripcion;
    item.append(title, description);
    signals.append(item);
  }
  const recommendations = document.getElementById("recommendations");
  recommendations.replaceChildren();
  for (const text of data.recomendaciones) {
    const item = document.createElement("li");
    item.textContent = text;
    recommendations.append(item);
  }
  result.hidden = false;
  document.getElementById("result-title").focus();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  error.hidden = true;
  result.hidden = true;
  if (!message.value.trim()) {
    showError("Pega o escribe un mensaje antes de analizarlo.");
    message.focus();
    return;
  }
  busy = true;
  analyzeButton.disabled = true;
  clearButton.disabled = true;
  message.readOnly = true;
  loading.hidden = false;
  form.setAttribute("aria-busy", "true");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch("/analizar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto: message.value }),
      signal: controller.signal,
      cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo analizar el mensaje.");
    }
    render(data);
  } catch (problem) {
    showError(problem.name === "AbortError"
      ? "El análisis tardó demasiado. Comprueba que el servidor esté funcionando y vuelve a intentarlo."
      : problem instanceof TypeError
        ? "No se pudo conectar con el servidor local. Comprueba que esté en ejecución."
        : problem.message);
  } finally {
    clearTimeout(timeout);
    busy = false;
    loading.hidden = true;
    analyzeButton.disabled = false;
    clearButton.disabled = false;
    message.readOnly = false;
    form.setAttribute("aria-busy", "false");
  }
});

async function checkModel() {
  try {
    const response = await fetch("/estado", { cache: "no-store" });
    if (!response.ok) throw new Error("estado");
    const state = await response.json();
    notice.textContent = !state.modelo_disponible
      ? "No hay un modelo disponible. Ejecuta python -m training.train y reinicia el servidor para analizar mensajes."
      : state.datos_demostrativos
        ? "Modo demostración: modelo entrenado con mensajes ficticios. Sus resultados no validan la eficacia real del sistema."
        : "Modelo local disponible. Su evaluación es orientativa y puede cometer errores.";
  } catch {
    notice.textContent = "No se pudo comprobar el modelo. Comprueba la conexión con el servidor local.";
  }
}
checkModel();
