# Mensaje Seguro

MVP académico de un **Sistema Inteligente para la Detección de Estafas en Mensajes**. Permite pegar un mensaje, obtener una clasificación orientativa y revisar señales y recomendaciones comprensibles. FastAPI, scikit-learn y una interfaz HTML/CSS/JavaScript sin frameworks ni servicios externos de IA. No necesita base de datos ni servicios de pago.

> **Esta evaluación es orientativa y puede cometer errores.** El CSV incluido es ficticio y exclusivamente demostrativo. Las métricas calculadas sobre esos datos no validan la eficacia real del sistema.

## Requisitos

- Python **3.11 o 3.12** (verificado localmente con 3.11).
- Conexión para instalar dependencias la primera vez; entrenamiento y análisis funcionan sin conexión.
- Ejecutar los comandos desde la raíz del proyecto. No abrir `index.html` con doble clic: FastAPI sirve la página y la API en el mismo origen.

## Instalación y ejecución en Windows (PowerShell)

```powershell
cd "C:\Users\dario\OneDrive\Desktop\Detector de estafas"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m training.train
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si `py` no está disponible, usa `python -m venv .venv`. Se invoca directamente el Python del entorno para evitar cambios de política de ejecución en PowerShell. Opcionalmente, puedes activarlo con `.\.venv\Scripts\Activate.ps1` y usar `python`.

Abre **http://127.0.0.1:8000**. Para detener el servidor, pulsa `Ctrl+C` en su terminal.

## Instalación y ejecución en Linux

```bash
cd "/ruta/Detector de estafas"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m training.train
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si tu distribución no incluye `venv`, instala el paquete `python3-venv` mediante su gestor de paquetes antes de crear el entorno.

## Uso de la interfaz

1. Pega el mensaje, sin contraseñas reales ni datos personales.
2. Pulsa **Analizar mensaje** y espera el resultado.
3. Revisa la categoría del modelo, las señales complementarias y las recomendaciones.
4. Usa **Limpiar** o **Analizar otro mensaje** para borrar el contenido de la página.

Hay un aviso visible sobre datos demostrativos, botones amplios, navegación con teclado, estado de carga y diseño para pantallas pequeñas. No se muestra un porcentaje de probabilidad de estafa.

## Entrenamiento y evaluación

El archivo `data/mensajes_demo.csv` tiene 80 ejemplos ficticios, 40 por clase. Consulta `data/README.md`.

```powershell
# Windows: entrenar con otro CSV
.\.venv\Scripts\python.exe -m training.train --data "data\mensajes_reales.csv"
# Identificar otros datasets ficticios
.\.venv\Scripts\python.exe -m training.train --data "data\otros_ejemplos.csv" --demo
```

En Linux, utiliza `python -m training.train --data data/mensajes_reales.csv`. `--output` permite elegir otro directorio de artefactos. Sin opciones se usa el CSV demostrativo, identificado automáticamente por su huella SHA-256 incluso si se copia con otro nombre. Para versiones modificadas de datos ficticios, utiliza siempre `--demo`.

### Formato del CSV

UTF-8, separado por comas; encierra entre comillas los textos que contengan comas:

```csv
texto,etiqueta
"Te espero en casa a las cinco.",legitimo
"Envía tu contraseña ahora para evitar el bloqueo.",fraudulento
```

Este fragmento ilustra el formato; por sí solo no basta para entrenar.

El script:

1. Exige las columnas `texto` y `etiqueta` y etiquetas exactas `legitimo` / `fraudulento`.
2. Elimina filas vacías y duplicadas. Para detectar duplicados compara espacios normalizados y mayúsculas/minúsculas; no reescribe el contenido restante. Informa los descartes.
3. Detiene el proceso ante textos equivalentes con etiquetas contradictorias, para revisarlos manualmente. No resuelve el conflicto por mayoría.
4. Requiere ambas clases y al menos cinco ejemplos distintos por clase como mínimo técnico. Este mínimo **no equivale a disponer de datos suficientes para una evaluación fiable**.
5. Separa de forma estratificada un 75 % de entrenamiento y un 25 % de prueba, con semilla 42, **antes de ajustar TF-IDF**.
6. Compara `TfidfVectorizer → LogisticRegression` y `TfidfVectorizer → MultinomialNB` mediante `GridSearchCV` estratificado dentro del entrenamiento: prueba `C` = 1, 0,1 y 10 para regresión logística y `alpha` = 1, 0,5 y 0,1 para Naive Bayes. Usa hasta cinco particiones, reducidas si la clase menor no permite cinco. Cada partición ajusta su propio vectorizador, evitando filtración de vocabulario e IDF. Las métricas de validación corresponden a la mejor configuración de cada familia y pueden ser optimistas por la selección; se conserva una prueba aparte.
7. Selecciona por F1 medio de `fraudulento` (en empate, regresión logística por orden fijo), ajusta solo con entrenamiento y evalúa una vez sobre prueba. No reajusta con los datos de prueba.

TF-IDF utiliza unigramas y bigramas. Se conservan las palabras, las expresiones de urgencia, los signos y los elementos de los enlaces; los signos también se tokenizan. No se eliminan enlaces ni se aplican listas de stopwords. El paso a minúsculas es una simplificación explícita: reduce variantes, aunque pierde la señal de las mayúsculas.

### Artefactos y métricas

- `artifacts/modelo.joblib`: pipeline entrenado y metadatos, sin los mensajes originales.
- `artifacts/metricas.json`: limpieza, distribución por clase, tamaños de particiones, versiones, semilla, huella del dataset, comparación y evaluación final.
- La consola imprime los mismos resultados calculados; no hay métricas prefijadas.

Se informa **exactitud, precisión, recall y F1**, con `fraudulento` como clase positiva. La matriz usa filas reales y columnas predichas, ambas en orden `[legitimo, fraudulento]`:

```text
                       Pred. legitimo   Pred. fraudulento
Real legitimo                 VN                FP
Real fraudulento              FN                VP
```

Cuando no hay predicciones positivas se informa precisión/F1 cero (`zero_division=0`). Con pocos mensajes las métricas son inestables. Las métricas corresponden a la **clasificación binaria nativa** del modelo, que ahora también muestra la interfaz; no validan el aviso de incertidumbre.

Tras entrenar, **reinicia el servidor**. El modelo se carga una vez al arrancar; no se recarga por solicitud. Si falta o es incompatible, la interfaz sigue disponible y `/analizar` devuelve 503, sin fingir resultados. Si falla un entrenamiento, un artefacto anterior puede seguir existiendo; revisa siempre la salida y los metadatos.

## Categorías y explicaciones

El modelo tiene dos clases. Su puntuación interna para `fraudulento`, obtenida con `predict_proba`, se usa como **puntuación del clasificador**, no como una probabilidad real de estafa ni como garantía de seguridad. No se ha calibrado frente al uso real.

| Clase elegida por el clasificador | Resultado principal |
| --- | --- |
| `legitimo` | Legítimo según el modelo |
| `fraudulento` | Fraudulento según el modelo |

**Desde la versión 1.1, «Sospechoso» no es una categoría de salida.** Antes se utilizaba como zona intermedia: con el primer modelo, 75 de los 80 textos ficticios caían en esa zona pese a tener una predicción binaria. Esa distribución fue un diagnóstico sobre el CSV completo, no una evaluación independiente.

Ahora siempre se muestra la clase elegida por la mayor puntuación del clasificador. Si la puntuación interna para `fraudulento` está entre 0,35 inclusive y 0,70 exclusive, se añade un **aviso separado de resultado incierto**, sin sustituir la clase ni inventar una tercera etiqueta. El color ámbar y el icono de atención destacan ese aviso. El aviso no es una medida calibrada de confianza. Estar fuera de esa zona tampoco garantiza un acierto.

Los umbrales del aviso son provisionales. Deben validarse con datos representativos, estudiando falsos negativos, falsas alarmas y cuántos casos quedan en incertidumbre. No se han optimizado usando el conjunto de prueba. Reentrenar sin cambiar datos, semilla o configuración no aporta conocimiento nuevo. La búsqueda de hiperparámetros amplía la comparación, pero no sustituye un dataset real más amplio y diverso.

Configuración en PowerShell, antes de iniciar el servidor:

```powershell
$env:UMBRAL_BAJO = "0.35"
$env:UMBRAL_ALTO = "0.70"
# Opcional, para un artefacto en otra ubicación:
$env:MODEL_PATH = "C:\ruta\modelo.joblib"
```

En Linux: `export UMBRAL_BAJO=0.35`, `export UMBRAL_ALTO=0.70` y, opcionalmente, `export MODEL_PATH=/ruta/modelo.joblib`. Se exige `0 < UMBRAL_BAJO < UMBRAL_ALTO < 1`.

Las reglas locales identifican menciones de credenciales, presión temporal, premios, pagos y enlaces. Se muestran **por separado** y no alteran la categoría del modelo. Son patrones de texto, no una comprensión completa de la intención: pueden señalar «no compartas tu contraseña» o una entrega legítima de premios. Por eso las plantillas describen menciones observadas y no afirman que se haya cometido fraude. Un enlace por sí solo no demuestra fraude. No se verifica el remitente, la autenticidad de ofertas ni la reputación de una URL. Las explicaciones de señales tampoco representan una atribución de características del modelo.

## API

### `POST /analizar`

Cabecera `Content-Type: application/json`. Cuerpo:

```json
{"texto": "Mensaje que deseas revisar"}
```

Respuesta 200 con los campos:

| Campo | Contenido |
| --- | --- |
| `categoria` | `Legítimo según el modelo` o `Fraudulento según el modelo` |
| `etiqueta_modelo` | Clase nativa `legitimo` o `fraudulento` |
| `nivel` | `bajo` para legítimo o `alto` para fraudulento; orientación de presentación, no riesgo verificado |
| `incertidumbre` | Si se activa el aviso independiente por umbrales provisionales |
| `aviso_incertidumbre` | Texto del aviso o `null` |
| `senales` | Lista de objetos con `codigo`, `titulo` y `descripcion` |
| `explicacion` | Plantilla de interpretación y límites |
| `recomendaciones` | Lista de acciones sugeridas |
| `datos_demostrativos` | Indicador del origen ficticio del modelo |
| `aviso` | Advertencia de posibles errores |

No devuelve el texto analizado ni una probabilidad de estafa. Los errores usan `{"detail": "explicación"}`:

- **422**: JSON inválido, campos adicionales, texto no textual, vacío, solo espacios o superior a 5.000 caracteres. Se valida el tamaño antes de recortar espacios externos.
- **503**: modelo ausente, incompatible o no utilizable; incluye instrucciones.

Ejemplo desde PowerShell, con el servidor iniciado en otra terminal:

```powershell
$body = @{ texto = "Hola, nos vemos mañana para comer." } | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/analizar" -Method Post -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

Linux:

```bash
curl http://127.0.0.1:8000/analizar -H 'Content-Type: application/json' \
  -d '{"texto":"Hola, nos vemos mañana para comer."}'
```

`GET /estado` indica disponibilidad del modelo, datos demostrativos y longitud máxima. `GET /openapi.json` expone el esquema local. No se cargan Swagger/ReDoc desde servicios externos.

## Privacidad y ejecución local

- La aplicación procesa los mensajes en memoria. No los escribe en archivos, no usa base de datos, almacenamiento del navegador, analítica ni APIs externas.
- Los logs predeterminados de Uvicorn muestran método, ruta y estado, no el cuerpo. Los errores de validación están adaptados para no reproducir el contenido enviado. No envíes mensajes en la URL.
- Las reglas no abren enlaces ni descargan adjuntos. No hay solicitudes externas en el frontend.
- La interfaz utiliza `textContent` y creación de nodos, no interpolación HTML. Los mensajes no se convierten en enlaces clicables. Se añaden cabeceras de no almacenamiento en caché, CSP, no sniff y no referrer.
- El contenido permanece en el campo de texto hasta limpiarlo o cerrar la página; el borrado no promete eliminación forense de la memoria del dispositivo.
- Por defecto el servidor se escucha solo en `127.0.0.1`. El MVP es local: no incluye autenticación, TLS ni límites de tráfico para un despliegue público.
- Carga únicamente artefactos `joblib` de confianza, generados por ti: ese formato puede ejecutar código al deserializarse. El vocabulario TF-IDF puede contener términos de los datos de entrenamiento; anonimízalos antes de entrenar y no publiques modelos entrenados con información sensible.

## Pruebas

Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Linux, con el entorno activo:

```bash
python -m pytest -q
```

Las pruebas entrenan un artefacto temporal real. Comprueban validación/limpieza del CSV, conflictos, aislamiento del vocabulario de prueba, métricas generadas, persistencia y carga, artefactos ausentes o dañados, límites de incertidumbre, señales, endpoint, validaciones, ausencia de eco del contenido y recursos de la interfaz. No dependen de un modelo precalculado ni fijan métricas artificiales.

## Incorporar datos reales en español

1. Obtén mensajes con procedencia y autorización de uso documentadas. Elimina datos personales y secretos; no subas mensajes privados al repositorio.
2. Define criterios de etiquetado. Revisa legitimidad/fraude con evidencia independiente y, cuando sea posible, dos anotadores; resuelve desacuerdos y deja fuera casos sin etiqueta fiable.
3. Recoge variedad de países, edades, remitentes, canales y épocas: mensajes familiares, avisos legítimos urgentes, enlaces legítimos, fraudes sin enlaces y estilos que no aparezcan en la demo.
4. Revisa duplicados semánticos y plantillas similares. El script detecta duplicados por texto normalizado, **no campañas ni paráfrasis**. Para datos de campañas o conversaciones repetidas, adapta la separación y la validación con grupos (por campaña/fuente/conversación) y considera una prueba temporal independiente. El split aleatorio actual no basta para ese caso.
5. Reserva una prueba representativa antes de seleccionar modelos y umbrales. Ajusta umbrales/calibración solo en entrenamiento o una validación adicional; no consultes repetidamente la prueba para mejorar resultados. Evalúa por separado la clasificación binaria y el aviso de incertidumbre. Las sucesivas versiones de la demo reutilizan la partición ficticia; no constituyen una nueva validación independiente.
6. Ejecuta el entrenamiento con tu CSV, inspecciona errores y falsos negativos, documenta el conjunto y reinicia la API. Sustituir el CSV no convierte automáticamente el sistema en una herramienta validada.

## Organización

```text
app/main.py                 API, ciclo de carga, rutas web y WebSockets
app/schemas.py              Validaciones y contratos de respuesta
app/predictor.py            Carga y umbrales del clasificador
app/signals.py              Reglas locales y recomendaciones
app/chat_manager.py         Gestor de conexiones WebSocket y memoria de mensajes
app/static/index.html       Interfaz web principal (Analizador de mensajes)
app/static/chat.html        Interfaz de la mensajería en tiempo real
app/static/chat.js          Cliente WebSocket de mensajería y alertas en vivo
app/static/chat.css         Estilos y tarjetas de riesgo para la mensajería
training/train.py           Limpieza, comparación, entrenamiento y evaluación
data/                       CSV demostrativo y su documentación
artifacts/                  Modelo y métricas generados al entrenar
tests/test_chat.py          Pruebas automatizadas de la mensajería y WebSockets
tests/test_api.py           Pruebas del endpoint /analizar y la web
tests/test_predictor.py     Pruebas del clasificador y umbrales de incertidumbre
tests/test_training.py      Pruebas del pipeline de entrenamiento y validación
```

---

## Mensajería en Tiempo Real con Detección de Estafas (`/chat`)

Además del analizador manual, el sistema cuenta con su propia **aplicación de mensajería instantánea protegida** que funciona entre **números telefónicos reales**.

### ¿Cómo funciona?

1. **Identidad por número real:** Dos personas se conectan con su número telefónico internacional (ej: `+591 70011223` y `+591 69876543`).
2. **Inspección automática en el servidor:** Cuando el Número A envía un mensaje al Número B, el backend de FastAPI evalúa el texto inmediatamente mediante el modelo de Machine Learning (`modelo.joblib`) y las reglas de seguridad (`detect_signals`).
3. **Alerta preventiva al destinatario:** 
   * Si el mensaje es **legítimo**: El receptor lo ve con una confirmación sutil de verificación segura.
   * Si el mensaje es **sospechoso o fraudulento**: El receptor ve el mensaje resaltado con una tarjeta de advertencia interactiva (`🚨 POSIBLE ESTAFA`), el nivel de riesgo, los indicadores detectados (urgencia, enlaces, códigos, premios, etc.) y recomendaciones de seguridad.

### Cómo probar la mensajería con dos números:

1. **Inicia el servidor:**
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. **Abre el Usuario A (Ventana normal):**
   * Ve a **[http://127.0.0.1:8000/chat](http://127.0.0.1:8000/chat)**.
   * Ingresa tu primer número (ej: `+591 70011223`) y pulsa **Conectar**.

3. **Abre el Usuario B (Ventana de incógnito o desde tu celular en la misma red):**
   * Abre una ventana de incógnito en **[http://127.0.0.1:8000/chat](http://127.0.0.1:8000/chat)**.
   * Ingresa tu segundo número (ej: `+591 69876543`) y pulsa **Conectar**.

4. **Inicia la conversación:**
   * En cualquiera de las dos ventanas, escribe el número del otro en *Nueva conversación* o selecciónalo de la lista de *Usuarios en línea*.
   * Envía un mensaje seguro (ej: *"Hola, nos vemos en la tarde"*): llegará limpio y verificado.
   * Envía un mensaje engañoso (ej: *"Felicidades, ganaste Bs 5.000. Entra inmediatamente al siguiente enlace https://premio.com y danos tu contraseña"*): **el destinatario verá en tiempo real la alerta roja con todas las señales detectadas.**

---

## Integración con Telegram ("Mensaje Seguro Bot")

Además de la interfaz web, el sistema permite recibir mensajes sospechosos directamente a través de Telegram utilizando la **Telegram Bot API oficial** con **long polling** (sin requerir dominio público ni configuración de webhooks).

El bot actúa como un cliente independiente que consulta el mismo endpoint `/analizar` de la API FastAPI y utiliza exactamente el mismo modelo ML y las mismas reglas de seguridad que la aplicación web.

### 1. Crear el bot en Telegram (BotFather)

1. Abre Telegram y busca al usuario oficial **[@BotFather](https://t.me/BotFather)**.
2. Inicia una conversación y envía el comando `/newbot`.
3. Sigue las instrucciones:
   - **Nombre:** Escribe `Mensaje Seguro` (o el nombre que prefieras).
   - **Username:** Escribe un nombre de usuario único terminado en `bot` (por ejemplo, `mensaje_seguro_ejemplo_bot`).
4. BotFather te responderá con un mensaje de confirmación que incluye tu **token de acceso HTTP API** (formato `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`). **Guarda este token.**

### 2. Configurar variables de entorno (`.env`)

Crea un archivo `.env` en la raíz del proyecto a partir de la plantilla `.env.example`:

En Windows (PowerShell):
```powershell
Copy-Item .env.example .env
```

Abre `.env` con un editor de texto y define tus valores:
```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
API_URL=http://127.0.0.1:8000
API_TIMEOUT_SECONDS=10.0
MAX_TEXT_LENGTH=5000
```

> [!IMPORTANT]
> El archivo `.env` se encuentra ignorado en `.gitignore` para garantizar que tu token de Telegram nunca se suba al repositorio.

### 3. Puesta en marcha

Para que el bot pueda analizar mensajes, **la API debe estar en ejecución**. Ejecuta los dos procesos en terminales separadas desde la raíz del proyecto:

**Terminal 1 — Iniciar la API FastAPI:**
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Iniciar el Bot de Telegram:**
```powershell
.\.venv\Scripts\python.exe -m bot.main
```

Verás un mensaje confirmando el arranque:
```text
Iniciando Bot de Telegram 'Mensaje Seguro' con long polling...
Conectando con la API en: http://127.0.0.1:8000
```

Para detener cualquiera de los dos servicios, pulsa `Ctrl + C` en su respectiva terminal.

### 4. Uso y prueba del bot en Telegram

1. Abre Telegram y busca el `@username` de tu bot.
2. Pulsa **Iniciar** o envía `/start`: el bot te dará la bienvenida y explicará su función.
3. Envía `/ayuda`: verás la guía de uso detallada.
4. **Prueba de mensaje seguro:**
   > "Hola mamá, mañana voy a visitarte para comer."  
   *Resultado:* `✅ MENSAJE APARENTEMENTE LEGÍTIMO` (Nivel de riesgo: BAJO).
5. **Prueba de mensaje fraudulento:**
   > "URGENTE: Banco informa que tu cuenta ha sido suspendida. Envía tu contraseña y transfiere dinero inmediatamente a este enlace para reactivarla."  
   *Resultado:* `🚨 POSIBLE ESTAFA` (Nivel de riesgo: ALTO), lista de indicadores detectados y recomendaciones claras.
6. **Reenvío de mensajes:** Puedes reenviar directamente al bot cualquier mensaje que recibas en otros chats.
7. **Contenido no textual:** Si envías una foto, audio, sticker o documento, el bot te indicará amablemente que actualmente solo analiza mensajes de texto.

### 5. Solución de problemas frecuentes

* **Error: `TELEGRAM_BOT_TOKEN no está configurado`:**
  Asegúrate de haber creado el archivo `.env` en la raíz del proyecto y de haber asignado el token real entregado por BotFather.
* **Respuesta: `⚠️ No pude conectar con el servicio de análisis en este momento`:**
  La API FastAPI no está en ejecución o la URL en `API_URL` es incorrecta. Asegúrate de iniciar la API en la Terminal 1 con `uvicorn`.
* **Respuesta: `⚠️ El modelo de detección no está disponible temporalmente`:**
  El archivo `artifacts/modelo.joblib` no existe o no se pudo cargar. Ejecuta `.\.venv\Scripts\python.exe -m training.train` y reinicia la API.
* **El bot no recibe mensajes o no responde:**
  Verifica tu conexión a internet y asegúrate de no tener otra instancia del bot ejecutándose simultáneamente con el mismo token (Telegram solo permite una conexión de long polling por token).

### Límites de esta versión

TF-IDF aprende asociaciones léxicas y no verifica hechos ni comprende todo el contexto. Puede fallar ante ironía, negación, cambios de idioma, mensajes breves, palabras desconocidas o campañas nuevas. Las reglas pueden dar falsas alarmas. Solo se muestran las dos clases aprendidas; la incertidumbre se comunica como aviso separado según umbrales provisionales. Incluso un texto sin vocabulario conocido recibirá una clase binaria, que no debe interpretarse como un juicio fiable. Ninguna categoría garantiza seguridad o confirma un delito. El objetivo de esta versión es demostrar y evaluar un flujo reproducible; la eficacia real exige datos y validación independientes.
