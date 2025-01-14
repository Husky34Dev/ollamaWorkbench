import os
import re
import time
import sqlite3
import subprocess
import requests
import json

from flask import Flask, render_template, request, jsonify, url_for

app = Flask(__name__)

# ---------------------------------------------------------------------
#   CONFIGURACIÓN DE LA BASE DE DATOS
# ---------------------------------------------------------------------
DB_PATH = "data.db"

def init_db():
    """
    Crea la tabla 'prompts' si no existe, para guardar:
      - modelo (TEXT)
      - prompt (TEXT)
      - respuesta (TEXT)
      - duracion (REAL)
      - fecha (TIMESTAMP)
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                modelo TEXT,
                prompt TEXT,
                respuesta TEXT,
                duracion REAL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

# ---------------------------------------------------------------------
#   CONSTANTES / REGEX
# ---------------------------------------------------------------------
OLLAMA_SERVER_URL = "http://127.0.0.1:11434"

# Para eliminar secuencias de escape ANSI
ANSI_ESCAPE_RE = re.compile(
    r'\x1B\[[0-?]*[ -/]*[@-~]|'
    r'\x1B[@-Z\\-_]'
)

# Para eliminar caracteres de spinner braille (⠙, ⠹, etc.)
BRAILLE_SPINNER_RE = re.compile('[⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋]+')

def remove_ansi_sequences(text: str) -> str:
    return ANSI_ESCAPE_RE.sub('', text)

def remove_braille_spinners(text: str) -> str:
    return BRAILLE_SPINNER_RE.sub('', text)

def remove_repeated_pulling(text: str) -> str:
    lines = text.splitlines()
    filtered = []
    for line in lines:
        if "pulling manifest" in line:
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()

# ---------------------------------------------------------------------
#   FUNCIONES SUBPROCESS: listar / pull
# ---------------------------------------------------------------------
def listar_modelos_ollama():
    """
    Llama a 'ollama list' localmente y extrae los nombres de modelo.
    """
    comando = ["ollama", "list"]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        return []

    lineas = resultado.stdout.strip().split("\n")
    if len(lineas) < 2:
        return []

    modelos = []
    for linea in lineas[1:]:
        partes = linea.split()
        if partes:
            modelos.append(partes[0])
    return modelos

def descargar_modelo_ollama(nombre_modelo: str):
    """
    Ejecuta 'ollama pull <nombre_modelo>'.
    Comprueba si ya está descargado.
    Retorna (True, salida) o (False, error).
    """
    existentes = listar_modelos_ollama()
    if nombre_modelo in existentes:
        return False, f"El modelo '{nombre_modelo}' ya está descargado."

    comando = ["ollama", "pull", nombre_modelo]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode == 0:
        stdout_limpio = remove_braille_spinners(remove_ansi_sequences(resultado.stdout))
        return True, stdout_limpio
    else:
        stderr_limpio = remove_ansi_sequences(resultado.stderr)
        stderr_limpio = remove_braille_spinners(stderr_limpio)
        stderr_limpio = remove_repeated_pulling(stderr_limpio)
        return False, stderr_limpio

# ---------------------------------------------------------------------
#   LISTA DE MODELOS DISPONIBLES PARA DESCARGA
# ---------------------------------------------------------------------
MODELOS_DISPONIBLES = [
    "llama3.3",
    "phi4",
    "qwq",
    "llama3.2",
    "llama3.1",
    # Añade más modelos
]

# ---------------------------------------------------------------------
#   RUTAS DE FLASK
# ---------------------------------------------------------------------
@app.route("/")
def index():
    """Página principal."""
    modelos_ollama = listar_modelos_ollama()
    modelos_disponibles = MODELOS_DISPONIBLES
    return render_template("index.html", modelos_ollama=modelos_ollama, modelos_disponibles=modelos_disponibles)

@app.route("/descargar_modelo", methods=["POST"])
def descargar_modelo():
    """Descarga un modelo vía 'ollama pull'."""
    nombre_modelo = request.form.get("nombre_modelo", "").strip()
    if not nombre_modelo:
        return jsonify({"ok": False, "error": "Nombre de modelo vacío"}), 400

    # Verifica si el modelo está en la lista de modelos disponibles
    if nombre_modelo not in MODELOS_DISPONIBLES:
        return jsonify({"ok": False, "error": "Modelo no disponible para descarga."}), 400

    ok, mensaje = descargar_modelo_ollama(nombre_modelo)
    if ok:
        return jsonify({"ok": True, "mensaje": mensaje})
    else:
        return jsonify({"ok": False, "error": mensaje}), 400


@app.route("/inferencia", methods=["POST"])
def inferencia():
    modelo = request.form.get("modelo", "").strip()
    prompt = request.form.get("prompt", "").strip()

    if not modelo or not prompt:
        return jsonify({"error": "Modelo o prompt vacío"}), 400

    url = f"{OLLAMA_SERVER_URL}/api/generate"
    payload = {"model": modelo, "prompt": prompt}
    response_text = ""  # Variable para acumular la respuesta

    try:
        # Iniciar el temporizador justo antes de enviar la solicitud
        start_time = time.time()

        # Enviar el prompt a Ollama
        print(f"Enviando a Ollama: {payload}")
        resp = requests.post(url, json=payload, stream=True)  # Usamos 'stream=True'

        # Leer la respuesta en fragmentos
        for line in resp.iter_lines():
            if line:
                try:
                    # Cada línea está en formato JSON
                    data = json.loads(line.decode('utf-8'))  # Decode bytes to string and parse JSON
                    print(f"Fragmento recibido: {data}")

                    # Acumular la respuesta en la variable response_text
                    if "response" in data:
                        response_text += data["response"]

                    # Si está 'done', terminamos
                    if data.ge t("done", False):
                        break
                except json.JSONDecodeError as e:
                    print(f"Error al decodificar JSON: {e}")
                    continue
        print(f"Respuesta final completa: {response_text}")

        # Detener el temporizador después de recibir la respuesta completa
        end_time = time.time()
        duracion = end_time - start_time

    except requests.exceptions.RequestException as e:
        print(f"Error al conectar con Ollama: {e}")
        return jsonify({"error": f"Error al conectar con Ollama: {e}"}), 500

    # Guardamos la respuesta en la base de datos
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO prompts (modelo, prompt, respuesta, duracion)
            VALUES (?, ?, ?, ?)
        """, (modelo, prompt, response_text, duracion))

    return jsonify({
        "respuesta": response_text,
        "duracion": duracion
    })


@app.route("/historial")
def historial():
    """Muestra la tabla 'prompts'."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT id, modelo, prompt, respuesta, duracion, fecha
            FROM prompts
            ORDER BY id DESC
        """)
        registros = cursor.fetchall()
    return render_template("historial.html", registros=registros)

# ---------------------------------------------------------------------
#   LÓGICA PARA EJECUTAR 'OLLAMA SERVE' AUTOMÁTICAMENTE
# ---------------------------------------------------------------------
def start_ollama_serve():
    """
    Lanza 'ollama serve' en segundo plano con subprocess.Popen.
    Espera hasta que Ollama responda en 127.0.0.1:11434.
    """
    serve_process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print("Iniciando ollama serve en segundo plano...")

    url = f"{OLLAMA_SERVER_URL}/api/generate"
    max_retries = 20
    for i in range(max_retries):
        time.sleep(1)
        try:
            # Si da 200, 404, etc., significa que contesta algo
            requests.get(url, timeout=2)
            print("Servidor Ollama detectado. Continuamos.")
            return serve_process
        except requests.RequestException:
            print(f"Esperando al servidor Ollama... (intento {i+1}/{max_retries})")

    # Si no arrancó, matamos el proceso y lanzamos error
    print("No se pudo conectar con Ollama serve.")
    serve_process.kill()
    raise RuntimeError("ollama serve no se inició correctamente.")

# ---------------------------------------------------------------------
#   MAIN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Lanza ollama serve en segundo plano y espera que responda
    serve_proc = start_ollama_serve()

    # Arranca Flask
    app.run(host="127.0.0.1", port=5000, debug=True)

    # Al parar Flask, si quieres, matas ollama serve:
    # serve_proc.terminate()
    # serve_proc.wait()
