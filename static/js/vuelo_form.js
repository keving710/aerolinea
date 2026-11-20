// Formularios de vuelo: calcula en vivo la duración y la llegada (con las reglas del servidor)
// y autocompleta la duración estimada de las rutas internacionales.
(function () {
  const form = document.querySelector("form[data-calculo-url]");
  if (!form) return;
  const tipo = form.dataset.tipo;
  const url = form.dataset.calculoUrl;
  const datos = document.getElementById("duraciones-estimadas");
  const estimadas = datos ? JSON.parse(datos.textContent) : {};
  const campo = (nombre) => document.getElementById("id_" + nombre);
  const sufijos = ["", "_r"].filter((s) => campo("fecha" + s));
  const temporizadores = {};

  function ruta(sufijo) {
    const origen = campo("origen") ? campo("origen").value : form.dataset.origen;
    const destino = campo("destino") ? campo("destino").value : form.dataset.destino;
    return sufijo === "_r" ? [destino, origen] : [origen, destino];
  }

  function mostrar(sufijo, duracion, llegada, error) {
    const caja = document.querySelector('[data-calculo="' + sufijo + '"]');
    if (!caja) return;
    caja.querySelector('[data-salida="duracion"]').textContent = duracion;
    caja.querySelector('[data-salida="llegada"]').textContent = llegada;
    caja.querySelector('[data-salida="error"]').textContent = error || "";
  }

  // Rellena horas/minutos con la duración estimada si el administrador no las ha escrito a mano.
  function estimar(sufijo) {
    if (tipo !== "internacional") return;
    const [origen, destino] = ruta(sufijo);
    const minutos = estimadas[origen + "|" + destino];
    const horas = campo("horas" + sufijo), mins = campo("minutos" + sufijo);
    if (!minutos || !horas || !mins) return;
    if ((horas.value === "" && mins.value === "") || horas.dataset.auto === "1") {
      horas.value = Math.floor(minutos / 60);
      mins.value = minutos % 60;
      horas.dataset.auto = "1";
    }
  }

  function calcular(sufijo) {
    clearTimeout(temporizadores[sufijo]);
    temporizadores[sufijo] = setTimeout(async function () {
      const fecha = campo("fecha" + sufijo), salida = campo("hora_salida" + sufijo);
      if (!fecha.value || !salida || !salida.value) return mostrar(sufijo, "—", "—", "");
      const p = new URLSearchParams({ tipo: tipo, fecha: fecha.value, hora_salida: salida.value });
      if (tipo === "nacional") {
        if (!campo("hora_llegada").value) return mostrar(sufijo, "—", "—", "");
        p.set("hora_llegada", campo("hora_llegada").value);
      } else {
        const [origen, destino] = ruta(sufijo);
        if (!origen || !destino) return mostrar(sufijo, "—", "—", "Elige el origen y el destino.");
        p.set("origen", origen);
        p.set("destino", destino);
        p.set("horas", campo("horas" + sufijo).value);
        p.set("minutos", campo("minutos" + sufijo).value);
      }
      try {
        const r = await fetch(url + "?" + p.toString(), { headers: { Accept: "application/json" } });
        const j = await r.json();
        if (r.ok) mostrar(sufijo, j.duracion, j.llegada, "");
        else mostrar(sufijo, "—", "—", j.error || "No se pudo calcular.");
      } catch (e) {
        mostrar(sufijo, "—", "—", "No se pudo calcular.");
      }
    }, 250);
  }

  sufijos.forEach(function (sufijo) {
    ["fecha", "hora_salida", "hora_llegada", "horas", "minutos"].forEach(function (nombre) {
      const el = campo(nombre + sufijo);
      if (!el) return;
      el.addEventListener("input", function () {
        if (nombre === "horas" || nombre === "minutos") campo("horas" + sufijo).dataset.auto = "0";
        calcular(sufijo);
      });
    });
    estimar(sufijo);
    calcular(sufijo);
  });

  ["origen", "destino"].forEach(function (nombre) {
    const el = campo(nombre);
    if (el) el.addEventListener("change", function () { sufijos.forEach(function (s) { estimar(s); calcular(s); }); });
  });

  // La caja del regreso solo se muestra si se programa el regreso.
  const conRegreso = campo("con_regreso");
  if (conRegreso) {
    const alternar = function () {
      const caja = document.querySelector('[data-calculo="_r"]');
      if (caja) caja.classList.toggle("d-none", !conRegreso.checked);
    };
    conRegreso.addEventListener("change", alternar);
    alternar();
  }
})();
