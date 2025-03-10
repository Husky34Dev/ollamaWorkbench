document.addEventListener('DOMContentLoaded', function() {
    console.log("DOMContentLoaded ejecutado"); // Para verificar que el evento se dispara
    console.log("Tipo de marked:", typeof marked); // Debe imprimir "function"

    // Manejo de Autocomplete
    const nombreModeloInput = document.getElementById('nombre_modelo');
    const suggestionsList = document.getElementById('suggestions');
    const downloadForm = document.getElementById('downloadForm');
    const downloadStatus = document.getElementById('downloadStatus');

    // Debounce
    function debounce(func, delay) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), delay);
        };
    }

    // Obtener sugerencias
    async function getSuggestions(query) {
        if (!query) {
            suggestionsList.innerHTML = '';
            suggestionsList.classList.add('hidden');
            return;
        }

        try {
            const response = await fetch(window.endpoints.buscarModelo, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: query })
            });

            const data = await response.json();

            if (data.ok) {
                const modelos = data.resultados;
                suggestionsList.innerHTML = modelos.length === 0
                  ? '<li class="p-2 text-gray-700">No se encontraron modelos.</li>'
                  : modelos.map(modelo => `
                        <li class="p-2 hover:bg-indigo-100 cursor-pointer" data-modelo="${modelo.nombre}">
                            ${modelo.nombre}
                        </li>
                    `).join('');
                suggestionsList.classList.remove('hidden');
            } else {
                suggestionsList.innerHTML = `<li class="p-2 text-red-500">${data.error}</li>`;
                suggestionsList.classList.remove('hidden');
            }
        } catch (error) {
            suggestionsList.innerHTML = `<li class="p-2 text-red-500">Error al obtener sugerencias.</li>`;
            suggestionsList.classList.remove('hidden');
        }
    }

    // Eventos Autocomplete
    nombreModeloInput.addEventListener('input', debounce(event => {
        const query = event.target.value.trim();
        getSuggestions(query);
    }, 300));

    suggestionsList.addEventListener('click', event => {
        if (event.target && event.target.matches('li[data-modelo]')) {
            const modeloSeleccionado = event.target.getAttribute('data-modelo');
            nombreModeloInput.value = modeloSeleccionado;
            suggestionsList.innerHTML = '';
            suggestionsList.classList.add('hidden');
            iniciarDescarga(modeloSeleccionado);
        }
    });

   async function iniciarDescarga(modelo) {
    downloadStatus.textContent = "Descargando, espera...";
    downloadStatus.classList.remove("text-green-500", "text-red-500", "text-gray-600");
    downloadStatus.classList.add("text-gray-600");

    const formData = new FormData();
    formData.append("nombre_modelo", modelo);

    try {
        const resp = await fetch(window.endpoints.descargarModelo, {
            method: "POST",
            body: formData
        });

        const result = await resp.json();
        console.log("Respuesta JSON:", result);

        // Verifica si la API envió un mensaje de éxito
        if (result.message) {
            downloadStatus.textContent = result.message;
            downloadStatus.classList.add("text-green-500");
        } else {
            downloadStatus.textContent = "Error: No se recibió respuesta válida.";
            downloadStatus.classList.add("text-red-500");
        }
    } catch (error) {
        console.error("Error en la descarga:", error);
        downloadStatus.textContent = `Error al descargar el modelo.`;
        downloadStatus.classList.add("text-red-500");
    }
}



    // Formulario de prompts
    const promptForm = document.getElementById('promptForm');
    const spinner = document.getElementById('spinner');
    const respuestaDiv = document.getElementById('respuesta');
    const temperatureValue = document.getElementById('temperatureValue');
    const temperatureSlider = document.getElementById('temperature');

    promptForm.addEventListener('submit', async event => {
        event.preventDefault(); // También necesario en el submit

        const selectModelo = document.getElementById('selectModelo');
        const promptInput = document.getElementById('prompt');
        const temperature = temperatureSlider.value;

        spinner.classList.remove('hidden');
        respuestaDiv.innerHTML = '';

        const modelo = selectModelo.value;
        const prompt = promptInput.value;

        const formData = new FormData();
        formData.append("modelo", modelo);
        formData.append("prompt", prompt);
        formData.append("temperature", temperature);

        try {
            const resp = await fetch(window.endpoints.inferencia, {
                method: "POST",
                body: formData
            });

            if (!resp.ok) {
                const errorData = await resp.json();
                throw new Error(errorData.error || `Error en la solicitud: ${resp.status}`);
            }

            const result = await resp.json();
            spinner.classList.add('hidden');
            respuestaDiv.innerHTML = marked.parse(result.respuesta); // Usa marked.parse()

        } catch (error) {
            spinner.classList.add('hidden');
            respuestaDiv.innerHTML = `<p class="text-red-500">${error.message}</p>`;
            console.error("Error:", error);
        }
    });

    temperatureSlider.addEventListener('input', () => {
        temperatureValue.textContent = temperatureSlider.value;
    });
}); // Fin de DOMContentLoaded
