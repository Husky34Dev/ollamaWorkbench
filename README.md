# Ollama Workbench

Ollama Workbench is a Flask-based application designed to simplify and enhance the use of Ollama's AI tools. This project is currently in its **alpha stage**, with a focus on providing a functional foundation for future development.
---

## Features
- Flask backend
- Dockerized setup with `docker-compose`
- Simple static and template structure
- Early implementation of requirements management

---

## Prerequisites
Ensure you have the following installed on your system:
- [Docker](https://www.docker.com/get-started)
- [Docker Compose](https://docs.docker.com/compose/install/)

---

## Project Structure
```
project-root/
|-- static/              # Static files (e.g., CSS, JS, images)
|-- templates/           # HTML templates
|-- .gitignore           # Ignored files for Git
|-- Dockerfile-flask      # Dockerfile for the Flask app
|-- app.py               # Main Flask application
|-- docker-compose.yaml  # Docker Compose configuration
|-- requirements.txt     # Python dependencies
```

---

## Setup Instructions

### Step 1: Clone the Repository
```bash
git clone https://github.com/Husky34Dev/ollamaWorkbench
cd <repository-folder>
```

### Step 2: Build and Run the App Using Docker Compose
Ensure you have `requirements.txt` properly configured with all necessary dependencies for your Flask app.

```bash
docker-compose up --build
```
This command will:
1. Build the Docker image based on the `Dockerfile-flask`.
2. Install Python dependencies listed in `requirements.txt`.
3. Start the Flask application on port `5001`.

### Step 3: Access the App
Once the container is running, you can access the application in your browser at:
```
http://localhost:5001
```

---

## Notes
1. **Early Alpha**: This is an early-stage implementation, and the project is under active development.
2. **Feedback Welcome**: Contributions and suggestions are encouraged.

---

## Known Issues
- Basic implementation with no advanced functionality.
- Limited error handling and input validation.

---

## Author
Developed by Bernardo Martínez Romero.
