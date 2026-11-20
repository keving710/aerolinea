// Muestra la franquicia mientras se escribe el número (solo ayuda visual; el servidor valida todo).
(function () {
  const numero = document.getElementById("id_numero");
  const salida = document.querySelector("[data-franquicia]");
  const vencimiento = document.getElementById("id_vencimiento");
  const cvv = document.getElementById("id_cvv");
  if (!numero || !salida) return;

  function franquicia(n) {
    const p2 = +n.slice(0, 2), p3 = +n.slice(0, 3), p4 = +n.slice(0, 4);
    if (n[0] === "4") return ["Visa", 3];
    if ((p2 >= 51 && p2 <= 55) || (p4 >= 2221 && p4 <= 2720)) return ["Mastercard", 3];
    if (p2 === 34 || p2 === 37) return ["American Express", 4];
    if ((p3 >= 300 && p3 <= 305) || [36, 38, 39].includes(p2)) return ["Diners Club", 3];
    if (n.startsWith("6011") || (p3 >= 644 && p3 <= 649) || p2 === 65) return ["Discover", 3];
    if (p4 >= 3528 && p4 <= 3589) return ["JCB", 3];
    return null;
  }

  numero.addEventListener("input", function () {
    const n = numero.value.replace(/[\s-]/g, "");
    if (n.length < 2) { salida.textContent = "escribe el número de la tarjeta"; return; }
    const f = franquicia(n);
    salida.textContent = f ? f[0] : "no reconocida (Visa, Mastercard, American Express, Diners Club, Discover o JCB)";
    if (cvv) cvv.maxLength = f ? f[1] : 4;
  });

  // Inserta la barra automáticamente: 0829 -> 08/29.
  if (vencimiento) {
    vencimiento.addEventListener("input", function (e) {
      if (e.inputType && e.inputType.startsWith("delete")) return;
      const d = vencimiento.value.replace(/\D/g, "").slice(0, 4);
      vencimiento.value = d.length > 2 ? d.slice(0, 2) + "/" + d.slice(2) : d;
    });
  }
})();
