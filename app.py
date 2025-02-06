import os
import re
import time
import sqlite3
import subprocess
import requests
import json
import shutil

from flask import Flask, render_template, request, jsonify, url_for
from bs4 import BeautifulSoup
from werkzeug.utils import redirect

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
        return False, f"Ya tienes el modelo '{nombre_modelo}'."

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
#   RUTAS DE FLASK
# ---------------------------------------------------------------------
@app.route("/")
def index():
    """Página principal."""
    modelos_ollama = listar_modelos_ollama()
    return render_template("index.html", modelos_ollama=modelos_ollama)


@app.route("/descargar_modelo", methods=["POST"])
def descargar_modelo():
    """Descarga un modelo vía 'ollama pull'."""
    nombre_modelo = request.form.get("nombre_modelo", "").strip()
    if not nombre_modelo:
        return jsonify({"ok": False, "error": "Nombre de modelo vacío"}), 400

    # Validar el formato del nombre del modelo
    if not re.match(r'^[a-zA-Z0-9\-_\.]+$', nombre_modelo):
        return jsonify({"ok": False, "error": "Formato de nombre de modelo inválido."}), 400

    ok, mensaje = descargar_modelo_ollama(nombre_modelo)
    if ok:
        return jsonify({"ok": True, "mensaje": mensaje})
    else:
        return jsonify({"ok": False, "error": mensaje}), 400


@app.route("/inferencia", methods=["POST"])
def inferencia():
    modelo = request.form.get("modelo", "").strip()
    prompt = request.form.get("prompt", "").strip()
    temperature = float(request.form.get("temperature", 0.7))  # Valor por defecto 0.7

    if not modelo or not prompt:
        return jsonify({"error": "Modelo o prompt vacío"}), 400

    url = f"{OLLAMA_SERVER_URL}/api/generate"
    payload = {"model": modelo, "prompt": prompt, "options": {"temperature": temperature}}
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
                    if data.get("done", False):
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


@app.route("/listar_modelos", methods=["GET"])
def listar_modelos():
    """Retorna la lista de modelos instalados en formato JSON."""
    modelos_ollama = listar_modelos_ollama()
    return jsonify(modelos_ollama)


@app.route("/buscar_modelo", methods=["POST"])
def buscar_modelo():
    """Realiza búsqueda de modelos mediante web scraping en Ollama Search."""
    data = request.get_json()
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"ok": False, "error": "Consulta de búsqueda vacía."}), 400

    try:
        resultados = realizar_web_scraping(query)
        return jsonify({"ok": True, "resultados": resultados})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def realizar_web_scraping(query: str):
    """
    Realiza web scraping en Ollama Search para obtener modelos que coincidan con la consulta.
    Retorna una lista de diccionarios con la información de cada modelo.
    """
    url = f"https://ollama.com/search?q={requests.utils.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Bot/1.0; +http://yourdomain.com/bot)"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Error al acceder a Ollama Search: {response.status_code}")

    soup = BeautifulSoup(response.text, 'html.parser')

    # Encontrar todos los enlaces de modelos
    enlaces_modelos = soup.find_all('a', href=True, class_='group w-full')

    resultados = []

    for enlace in enlaces_modelos:
        nombre = enlace.find('span', {'x-test-search-response-title': True})
        descripcion = enlace.find('p', class_='max-w-lg break-words text-neutral-800 text-md')

        if nombre and descripcion:
            modelo_info = {
                "nombre": nombre.get_text(strip=True),
                "descripcion": descripcion.get_text(strip=True),
                "url": enlace['href']
            }
            resultados.append(modelo_info)

    return resultados


# ---------------------------------------------------------------------
#   FUNCIONES AUXILIARES
# ---------------------------------------------------------------------

def is_ollama_installed():
    """Verifica si Ollama está instalado en el sistema."""
    return shutil.which("ollama") is not None


def start_ollama_serve():
    """
    Lanza 'ollama serve' en segundo plano con subprocess.Popen.
    Espera hasta que Ollama responda en 127.0.0.1:11434.
    """
    if not is_ollama_installed():
        print("❌ Ollama no está instalado en tu sistema.")
        print("Por favor, instala Ollama desde el siguiente enlace:")
        print("👉 https://github.com/ollama/ollama")
        exit(1)  # Finaliza la ejecución de la aplicación

    try:
        serve_process = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ Iniciando 'ollama serve' en segundo plano...")

        url = f"{OLLAMA_SERVER_URL}/api/generate"
        max_retries = 20
        for i in range(max_retries):
            time.sleep(1)
            try:
                # Si da 200, 404, etc., significa que contesta algo
                response = requests.get(url, timeout=2)
                if response.status_code:
                    print("✅ Servidor Ollama detectado. Continuando con la aplicación.")
                    return serve_process
            except requests.RequestException:
                print(f"⌛ Esperando al servidor Ollama... (intento {i + 1}/{max_retries})")

        # Si no arrancó, matamos el proceso y lanzamos error
        print("❌ No se pudo conectar con 'ollama serve' después de varios intentos.")
        serve_process.kill()
        exit(1)  # Finaliza la ejecución de la aplicación

    except Exception as e:
        print(f"❌ Error al intentar iniciar 'ollama serve': {e}")
        exit(1)  # Finaliza la ejecución de la aplicación


# ---------------------------------------------------------------------
#   MAIN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Verifica si Ollama está instalado y arranca el servidor si es así
    serve_proc = start_ollama_serve()

    try:
        # Arranca Flask
        print("🚀 Iniciando la aplicación Flask...")
        app.run(host="127.0.0.1", port=5000, debug=True)
    except KeyboardInterrupt:
        print("\n🛑 Aplicación interrumpida por el usuario.")
    finally:
        # Al parar Flask, si quieres, matar ollama serve:
        if serve_proc.poll() is None:
            print("🛑 Terminando 'ollama serve'...")
            serve_proc.terminate()
            serve_proc.wait()
        print("✅ Aplicación finalizada correctamente.")
