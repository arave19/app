let selectedPhoto = null;

let map = null;

let marker = null;


const evidenceForm =
    document.getElementById("evidenceForm");

const saveCrawlingUrl =
    evidenceForm.dataset.saveUrl;

const extractMapsCoordinatesUrl =
    evidenceForm.dataset.extractUrl;

const detectPhonesUrl =
    evidenceForm.dataset.detectPhonesUrl;

const maxPhoneCount =
    5;

const photoInput =
    document.getElementById("photoInput");

const takePhotoBtn =
    document.getElementById("takePhotoBtn");

const removePhotoBtn =
    document.getElementById("removePhotoBtn");

const photoPreview =
    document.getElementById("photoPreview");

const emptyPhotoMessage =
    document.getElementById("emptyPhotoMessage");

const photoStatus =
    document.getElementById("photoStatus");

const phoneList =
    document.getElementById("phoneList");

const addPhoneBtn =
    document.getElementById("addPhoneBtn");

const phoneStatus =
    document.getElementById("phoneStatus");

const phoneSpinner =
    document.getElementById("phoneSpinner");

const getLocationBtn =
    document.getElementById("getLocationBtn");

const mapsUrlInput =
    document.getElementById("mapsUrlInput");

const useMapsUrlBtn =
    document.getElementById("useMapsUrlBtn");

const locationStatus =
    document.getElementById("locationStatus");

const submitFormBtn =
    document.getElementById("submitFormBtn");

const submitFormBtnContent =
    submitFormBtn.innerHTML;


takePhotoBtn.addEventListener(
    "click",
    function () {

        photoInput.click();

    }
);


photoInput.addEventListener(
    "change",
    function (event) {

        const file =
            event.target.files[0];


        if (!file) {
            return;
        }


        selectedPhoto = file;


        const imageUrl =
            URL.createObjectURL(file);


        photoPreview.src =
            imageUrl;


        photoPreview.style.display =
            "block";


        emptyPhotoMessage.style.display =
            "none";


        removePhotoBtn.classList.remove(
            "d-none"
        );

        detectPhonesFromPhoto(
            file
        );


        photoStatus.textContent =
            `Fotografía seleccionada: ${file.name}`;

    }
);


removePhotoBtn.addEventListener(
    "click",
    function () {

        selectedPhoto = null;

        photoInput.value = "";

        photoPreview.src = "";

        photoPreview.style.display =
            "none";

        emptyPhotoMessage.style.display =
            "block";

        removePhotoBtn.classList.add(
            "d-none"
        );

        photoStatus.textContent =
            "No hay fotografía seleccionada.";

        phoneStatus.textContent =
            "Puedes agregar hasta 5 teléfonos.";

    }
);


addPhoneBtn.addEventListener(
    "click",
    function () {

        addPhoneField();

    }
);


function addPhoneField(value = "") {

    const currentRows =
        phoneList.querySelectorAll(".phone-row");


    if (currentRows.length >= maxPhoneCount) {

        phoneStatus.textContent =
            "Máximo 5 teléfonos.";

        return false;

    }


    const row =
        document.createElement("div");

    row.className =
        "phone-row";


    const input =
        document.createElement("input");

    input.type =
        "tel";

    input.className =
        "form-control";

    input.name =
        "telefonos";

    input.placeholder =
        "Número de teléfono";

    input.value =
        value;


    const removeButton =
        document.createElement("button");

    removeButton.type =
        "button";

    removeButton.className =
        "btn btn-secondary-habi phone-action-btn";

    removeButton.setAttribute(
        "aria-label",
        "Quitar teléfono"
    );

    removeButton.innerHTML =
        '<i class="fa-solid fa-minus" aria-hidden="true"></i>';

    removeButton.addEventListener(
        "click",
        function () {

            row.remove();

            updatePhoneControls();

        }
    );


    row.append(
        input,
        removeButton
    );

    phoneList.appendChild(
        row
    );

    updatePhoneControls();

    return true;

}


function fillDetectedPhones(phones) {

    const existingPhones =
        getPhoneValues();

    let addedCount =
        0;


    for (const phone of phones) {

        if (existingPhones.includes(phone)) {

            continue;

        }

        const emptyInput =
            Array.from(
                phoneList.querySelectorAll("input")
            ).find(
                function (input) {
                    return !input.value.trim();
                }
            );


        if (emptyInput) {

            emptyInput.value =
                phone;

            existingPhones.push(phone);
            addedCount += 1;

            continue;

        }


        if (
            phoneList.querySelectorAll(".phone-row").length >=
            maxPhoneCount
        ) {

            continue;

        }


        if (addPhoneField(phone)) {

            existingPhones.push(phone);
            addedCount += 1;

        }

    }

    updatePhoneControls();


    if (addedCount > 0) {

        phoneStatus.textContent =
            `Se detectaron ${addedCount} teléfono(s) desde la fotografía.`;

    }

    else {

        phoneStatus.textContent =
            "No se detectaron teléfonos nuevos en la fotografía.";

    }

}


function getPhoneValues() {

    return Array.from(
        phoneList.querySelectorAll("input")
    ).map(
        function (input) {
            return input.value.trim();
        }
    ).filter(Boolean);

}


function updatePhoneControls() {

    const currentCount =
        phoneList.querySelectorAll(".phone-row").length;

    addPhoneBtn.disabled =
        currentCount >= maxPhoneCount;

    if (currentCount >= maxPhoneCount) {

        phoneStatus.textContent =
            "Máximo 5 teléfonos.";

    }

    else if (currentCount === 0) {

        phoneStatus.textContent =
            "Puedes agregar hasta 5 teléfonos.";

    }

}


function setPhoneLoading(isLoading) {

    phoneSpinner.classList.toggle(
        "is-hidden",
        !isLoading
    );

    addPhoneBtn.disabled =
        isLoading ||
        phoneList.querySelectorAll(".phone-row").length >= maxPhoneCount;

}


async function detectPhonesFromPhoto(file) {

    const formData =
        new FormData();

    formData.append(
        "photo",
        file
    );


    phoneStatus.textContent =
        "Buscando teléfonos en la fotografía...";

    setPhoneLoading(
        true
    );


    try {

        if (!detectPhonesUrl) {

            phoneStatus.textContent =
                "No esta configurada la ruta de deteccion OCR.";

            return;

        }


        const response =
            await fetch(
                detectPhonesUrl,
                {
                    method: "POST",
                    body: formData
                }
            );


        if (!response.ok) {

            const errorData =
                await response.json().catch(
                    function () {
                        return {};
                    }
                );

            phoneStatus.textContent =
                errorData.message || "No fue posible analizar la fotografía.";

            console.error(
                "Error OCR",
                response.status,
                errorData
            );

            return;

        }


        const data =
            await response.json();

        fillDetectedPhones(
            data.phones || []
        );

    }

    catch (error) {

        console.error(error);

        phoneStatus.textContent =
            "No fue posible analizar la fotografía.";

    }

    finally {

        setPhoneLoading(
            false
        );

    }

}


addPhoneField();


getLocationBtn.addEventListener(
    "click",
    function () {

        if (!navigator.geolocation) {

            locationStatus.textContent =
                "La geolocalización no está disponible.";

            return;

        }


        locationStatus.textContent =
            "Obteniendo ubicación...";


        navigator.geolocation.getCurrentPosition(

            function (position) {

                const latitude =
                    position.coords.latitude;

                const longitude =
                    position.coords.longitude;

                const accuracy =
                    position.coords.accuracy;


                document.getElementById(
                    "latitude"
                ).textContent =
                    latitude;


                document.getElementById(
                    "longitude"
                ).textContent =
                    longitude;


                document.getElementById(
                    "accuracy"
                ).textContent =
                    Math.round(accuracy);


                document.getElementById(
                    "latitudeInput"
                ).value =
                    latitude;


                document.getElementById(
                    "longitudeInput"
                ).value =
                    longitude;


                document.getElementById(
                    "accuracyInput"
                ).value =
                    accuracy;


                document.getElementById(
                    "locationInfo"
                ).style.display =
                    "block";


                document.getElementById(
                    "mapContainer"
                ).style.display =
                    "block";


                locationStatus.textContent =
                    "Ubicación capturada correctamente.";


                showMap(
                    latitude,
                    longitude
                );

            },


            function (error) {

                let message =
                    "No fue posible obtener la ubicación.";


                if (
                    error.code ===
                    error.PERMISSION_DENIED
                ) {

                    message =
                        "Permiso de ubicación denegado.";

                }


                else if (
                    error.code ===
                    error.POSITION_UNAVAILABLE
                ) {

                    message =
                        "La ubicación no está disponible.";

                }


                else if (
                    error.code ===
                    error.TIMEOUT
                ) {

                    message =
                        "La solicitud excedió el tiempo de espera.";

                }


                locationStatus.textContent =
                    message;

            },


            {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 0
            }

        );

    }
);


useMapsUrlBtn.addEventListener(
    "click",
    async function () {

        let coordinates =
            extractCoordinatesFromGoogleMapsUrl(
                mapsUrlInput.value
            );


        if (!coordinates) {

            coordinates =
                await fetchCoordinatesFromMapsUrl(
                    mapsUrlInput.value
                );

        }


        if (!coordinates) {

            locationStatus.textContent =
                "No fue posible extraer latitud y longitud de la URL.";

            return;

        }


        document.getElementById(
            "latitude"
        ).textContent =
            coordinates.latitude;


        document.getElementById(
            "longitude"
        ).textContent =
            coordinates.longitude;


        document.getElementById(
            "accuracy"
        ).textContent =
            "Manual";


        document.getElementById(
            "latitudeInput"
        ).value =
            coordinates.latitude;


        document.getElementById(
            "longitudeInput"
        ).value =
            coordinates.longitude;


        document.getElementById(
            "accuracyInput"
        ).value =
            "";


        document.getElementById(
            "locationInfo"
        ).style.display =
            "block";


        document.getElementById(
            "mapContainer"
        ).style.display =
            "block";


        locationStatus.textContent =
            "Ubicacion cargada desde URL de Google Maps.";


        showMap(
            coordinates.latitude,
            coordinates.longitude
        );

    }
);


function extractCoordinatesFromGoogleMapsUrl(url) {

    const value =
        url.trim();


    if (!value) {
        return null;
    }


    let decodedValue =
        value;


    try {

        decodedValue =
            decodeURIComponent(value);

    }

    catch (error) {

        decodedValue =
            value;

    }

    const coordinatePatterns = [
        /@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
        /[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
        /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,
        /\/(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)(?:[/?]|$)/
    ];


    for (const pattern of coordinatePatterns) {

        const match =
            decodedValue.match(pattern);


        if (!match) {
            continue;
        }


        const latitude =
            Number(match[1]);

        const longitude =
            Number(match[2]);


        if (isValidCoordinate(latitude, longitude)) {

            return {
                latitude,
                longitude
            };

        }

    }


    return null;

}


async function fetchCoordinatesFromMapsUrl(url) {

    try {

        locationStatus.textContent =
            "Validando URL de Google Maps...";

        const response =
            await fetch(
                extractMapsCoordinatesUrl,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        url
                    })
                }
            );


        if (!response.ok) {
            return null;
        }


        return await response.json();

    }

    catch (error) {

        console.error(error);

        return null;

    }

}


function isValidCoordinate(
    latitude,
    longitude
) {

    return Number.isFinite(latitude) &&
        Number.isFinite(longitude) &&
        latitude >= -90 &&
        latitude <= 90 &&
        longitude >= -180 &&
        longitude <= 180;

}


function showMap(
    latitude,
    longitude
) {

    const location = {
        lat: latitude,
        lng: longitude
    };


    if (
        typeof google === "undefined" ||
        !google.maps
    ) {

        return;

    }


    if (!map) {

        map =
            new google.maps.Map(

                document.getElementById(
                    "map"
                ),

                {
                    zoom: 17,
                    center: location,
                    mapTypeControl: false,
                    streetViewControl: false,
                    fullscreenControl: false
                }

            );


        marker =
            new google.maps.Marker({

                position: location,

                map: map

            });

    }


    else {

        map.setCenter(
            location
        );


        marker.setPosition(
            location
        );

    }

}


document.getElementById(
    "evidenceForm"
).addEventListener(

    "submit",

    async function (event) {

        event.preventDefault();


        if (!selectedPhoto) {

            alert(
                "Debe tomar o seleccionar una fotografía."
            );

            return;

        }


        const latitude =
            document.getElementById(
                "latitudeInput"
            ).value;


        if (!latitude) {

            alert(
                "Debe capturar su ubicación actual."
            );

            return;

        }


        submitFormBtn.disabled =
            true;

        submitFormBtn.innerHTML =
            '<i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i> Enviando...';


        const formData =
            new FormData(
                event.target
            );


        formData.append(
            "photo",
            selectedPhoto
        );


        try {

            const response =
                await fetch(

                    saveCrawlingUrl,

                    {
                        method: "POST",
                        body: formData
                    }

                );


            if (!response.ok) {

                throw new Error(
                    "Error al enviar el formulario."
                );

            }


            alert(
                "Registro enviado correctamente."
            );


            event.target.reset();


            selectedPhoto = null;

            photoPreview.src = "";

            photoPreview.style.display =
                "none";

            emptyPhotoMessage.style.display =
                "block";

            removePhotoBtn.classList.add(
                "d-none"
            );

            phoneList.innerHTML =
                "";

            addPhoneField();


            document.getElementById(
                "locationInfo"
            ).style.display =
                "none";


            document.getElementById(
                "mapContainer"
            ).style.display =
                "none";


            locationStatus.textContent =
                "Ubicación no capturada.";


            photoStatus.textContent =
                "No hay fotografía seleccionada.";

            submitFormBtn.disabled =
                false;

            submitFormBtn.innerHTML =
                submitFormBtnContent;

        }


        catch (error) {

            console.error(error);

            alert(
                "Ocurrió un error al enviar el registro."
            );

            submitFormBtn.disabled =
                false;

            submitFormBtn.innerHTML =
                submitFormBtnContent;

        }

    }

);


evidenceForm.addEventListener(
    "reset",
    function () {

        setTimeout(
            function () {

                selectedPhoto = null;

                photoPreview.src =
                    "";

                photoPreview.style.display =
                    "none";

                emptyPhotoMessage.style.display =
                    "block";

                removePhotoBtn.classList.add(
                    "d-none"
                );

                phoneList.innerHTML =
                    "";

                addPhoneField();

                document.getElementById(
                    "locationInfo"
                ).style.display =
                    "none";

                document.getElementById(
                    "mapContainer"
                ).style.display =
                    "none";

                locationStatus.textContent =
                    "Ubicación no capturada.";

                photoStatus.textContent =
                    "No hay fotografía seleccionada.";

                phoneStatus.textContent =
                    "Puedes agregar hasta 5 teléfonos.";

            },
            0
        );

    }
);
