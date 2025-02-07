import os
import re
import time
import sqlite3
import subprocess
import requests
import json
import shutil
import sys
import subprocess
import logging
import docker
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Cargar las variables de entorno desde el archivo .env

app = Flask(__name__)
load_dotenv()

# ---------------------------------------------------------------------
#   CONFIGURACIÓN DE LA BASE DE DATOS
# ---------------------------------------------------------------------
DB_PATH = "data/data.db"


def init_db():
    """Crea la tabla 'prompts' si no existe y agrega un índice para la fecha."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                modelo TEXT,
                prompt TEXT,
                respuesta TEXT,
                duracion REAL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fecha ON prompts (fecha)")


def guardar_en_base_de_datos(modelo, prompt, respuesta, duracion):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO prompts (modelo, prompt, respuesta, duracion)
            VALUES (?, ?, ?, ?)
            """,
            (modelo, prompt, respuesta, duracion),
        )


init_db()

# ---------------------------------------------------------------------
#   CONSTANTES / REGEX
# ---------------------------------------------------------------------

# URL del contenedor 'ollama'
OLLAMA_SERVER_URL = "http://ollama:11434"


# ---------------------------------------------------------------------
#   FUNCIONES SUBPROCESS: listar / pull
# ---------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def listar_modelos_ollama():
    """Obtiene la lista de modelos instalados de Ollama"""
    try:
        response = requests.get(f"{OLLAMA_SERVER_URL}/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        return [model["name"] for model in models]
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al listar modelos: {e}")
        return []
    except Exception as e:
        logger.error(f"Error al listar modelos: {str(e)}")
        return []


def descargar_modelo_ollama(nombre_modelo: str):
    """Descarga un modelo usando Docker."""
    try:
        client = docker.from_env()  # variables de entorno de Docker
        container = client.containers.get("ollama")  # Obtener el contenedor de Ollama

        # Ejecuta 'ollama pull' dentro del contenedor
        result = container.exec_run(cmd=["ollama", "pull", nombre_modelo], stream=False)

        if result.exit_code == 0:
            return True, f"Modelo {nombre_modelo} descargado exitosamente"
        else:
            error_msg = f"Error al descargar el modelo: {result.output.decode()}"
            logger.error(error_msg)
            return False, error_msg

    except docker.errors.NotFound:
        error_msg = "Contenedor 'ollama' no encontrado."
        logger.error(error_msg)
        return False, error_msg
    except docker.errors.APIError as e:
        error_msg = f"Error de la API de Docker: {e}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Error inesperado: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


# ---------------------------------------------------------------------
#   FUNCIONES DE WEB SCRAPING
# ---------------------------------------------------------------------
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

    soup = BeautifulSoup(response.text, "html.parser")

    # Encontrar todos los enlaces de modelos
    enlaces_modelos = soup.find_all("a", href=True, class_="group w-full")

    resultados = []

    for enlace in enlaces_modelos:
        nombre = enlace.find("span", {"x-test-search-response-title": True})
        descripcion = enlace.find(
            "p", class_="max-w-lg break-words text-neutral-800 text-md"
        )

        if nombre and descripcion:
            modelo_info = {
                "nombre": nombre.get_text(strip=True),
                "descripcion": descripcion.get_text(strip=True),
                "url": enlace["href"],
            }
            resultados.append(modelo_info)

    return resultados


# ---------------------------------------------------------------------
#   MANEJAR INFERENCIAS
# ---------------------------------------------------------------------
def obtener_datos_request():
    modelo = request.form.get("modelo", "").strip()
    prompt = request.form.get("prompt", "").strip()
    temperature = float(request.form.get("temperature", 0.7))
    return modelo, prompt, temperature


def enviar_a_ollama(modelo, prompt, temperature):
    url = f"{OLLAMA_SERVER_URL}/api/generate"
    payload = {
        "model": modelo,
        "prompt": prompt,
        "options": {"temperature": temperature},
    }
    print(f"Enviando a Ollama: {payload}")
    return requests.post(url, json=payload, stream=True)


def validar_entrada(modelo, prompt):
    if not modelo or not prompt:
        return jsonify({"error": "Modelo o prompt vacío"}), 400
    return None


def procesar_respuesta(resp):
    response_text = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if chunk:
            try:
                json_objects = chunk.strip().splitlines()
                for json_str in json_objects:
                    if json_str:
                        data = json.loads(json_str)
                        print(f"Fragmento recibido: {data}")
                        if "response" in data:
                            response_text += data["response"]
                        if data.get("done", False):
                            return response_text
            except json.JSONDecodeError as e:
                print(f"Error al decodificar JSON: {e}, Chunk: {chunk}")
    return response_text


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
    """Descargar un modelo de Ollama usando la API."""
    modelo_nombre = request.form.get("nombre_modelo", "").strip()

    if not modelo_nombre:
        return jsonify({"error": "Nombre de modelo no proporcionado"}), 400

    # Usar la función de descarga
    success, message = descargar_modelo_ollama(modelo_nombre)

    if success:
        return jsonify({"message": message}), 200
    else:
        return jsonify({"error": message}), 500


@app.route("/inferencia", methods=["POST"])
def inferencia():
    modelo, prompt, temperature = obtener_datos_request()
    error = validar_entrada(modelo, prompt)
    if error:
        return error

    try:
        start_time = time.time()
        resp = enviar_a_ollama(modelo, prompt, temperature)

        if resp.status_code != 200:
            error_message = resp.text
            print(f"Error de Ollama ({resp.status_code}): {error_message}")
            return (
                jsonify({"error": f"Error de Ollama: {error_message}"}),
                resp.status_code,
            )

        response_text = procesar_respuesta(resp)
        end_time = time.time()
        duracion = end_time - start_time

        guardar_en_base_de_datos(modelo, prompt, response_text, duracion)

        return jsonify({"respuesta": response_text, "duracion": duracion})

    except requests.exceptions.RequestException as e:
        print(f"Error de conexión: {e}")
        return jsonify({"error": f"Error de conexión: {e}"}), 500


@app.route("/historial")
def historial():
    """Muestra el historial de prompts."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT id, modelo, prompt, respuesta, duracion, fecha
            FROM prompts
            ORDER BY id DESC
        """
        )
        registros = cursor.fetchall()
    return render_template("historial.html", registros=registros)


@app.route("/listar_modelos", methods=["GET"])
def listar_modelos():
    """Retorna la lista de modelos instalados en formato JSON."""
    modelos_ollama = listar_modelos_ollama()
    return jsonify(modelos_ollama)  # Devuelve la lista directamente


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


# ---------------------------------------------------------------------
#   MAIN: ARRANQUE DEL SERVIDOR
# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
