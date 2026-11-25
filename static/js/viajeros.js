// Agrega o quita viajeros del formulario de compra/reserva y muestra el vuelo de regreso solo si se elige ida y vuelta.
(function () {
  var contenedor = document.getElementById("viajeros");
  if (!contenedor) return;
  var total = document.getElementById("id_viajero-TOTAL_FORMS");
  var plantilla = document.getElementById("plantilla-viajero").innerHTML;
  var maximo = parseInt(contenedor.dataset.maximo, 10);
  var agregar = document.getElementById("agregar-viajero");
  var quitar = document.getElementById("quitar-viajero");

  function actualizar() {
    var n = contenedor.querySelectorAll(".viajero").length;
    agregar.disabled = n >= maximo;
    quitar.disabled = n <= 1;
    contenedor.querySelectorAll(".viajero").forEach(function (el, i) {
      el.querySelector(".numero-viajero").textContent = i + 1;
    });
    document.getElementById("cantidad-viajeros").textContent = n;
  }

  agregar.addEventListener("click", function () {
    var n = contenedor.querySelectorAll(".viajero").length;
    if (n >= maximo) return;
    var div = document.createElement("div");
    div.innerHTML = plantilla.replace(/__prefix__/g, n);
    contenedor.appendChild(div.firstElementChild);
    total.value = n + 1;
    actualizar();
  });
  quitar.addEventListener("click", function () {
    var items = contenedor.querySelectorAll(".viajero");
    if (items.length <= 1) return;
    items[items.length - 1].remove();
    total.value = items.length - 1;
    actualizar();
  });

  var radios = document.querySelectorAll("input[name='trayecto']");
  var regreso = document.getElementById("bloque-regreso");
  function trayecto() {
    var completo = document.querySelector("input[name='trayecto']:checked");
    if (regreso) regreso.hidden = !(completo && completo.value === "completo");
  }
  radios.forEach(function (r) { r.addEventListener("change", trayecto); });
  trayecto();
  actualizar();
})();
