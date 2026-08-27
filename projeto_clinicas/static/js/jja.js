/*
 * JJA System - comportamentos gerais da interface.
 * Nenhuma regra de negocio vive aqui: o frontend e apenas conveniencia.
 */
window.JJA = window.JJA || {};

/**
 * Abre o link oficial de "click-to-chat" do WhatsApp com uma mensagem
 * pre-preenchida (editavel pelo usuario antes de enviar). Nao usa nenhuma
 * API/token do WhatsApp Business -- e apenas um link https://wa.me/, o
 * proprio usuario confirma o envio dentro do WhatsApp.
 */
window.JJA.shareOnWhatsApp = function (text) {
  const url = "https://wa.me/?text=" + encodeURIComponent(text || "");
  window.open(url, "_blank", "noopener,noreferrer");
};

(function () {
  "use strict";

  // --- menu lateral em telas pequenas -------------------------------------
  const toggle = document.getElementById("jjaSidebarToggle");
  const sidebar = document.getElementById("jjaSidebar");
  const backdrop = document.getElementById("jjaSidebarBackdrop");

  function closeSidebar() {
    sidebar && sidebar.classList.remove("show");
    backdrop && backdrop.classList.remove("show");
  }

  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("show");
      backdrop && backdrop.classList.toggle("show");
    });
  }
  backdrop && backdrop.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeSidebar();
  });

  // --- confirmacao em acoes destrutivas -----------------------------------
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // --- mascaras simples (CPF, CNPJ, telefone, CEP) -------------------------
  function onlyDigits(value) { return (value || "").replace(/\D/g, ""); }

  function applyMask(input, formatter) {
    input.addEventListener("input", function () {
      const caretAtEnd = input.selectionStart === input.value.length;
      input.value = formatter(onlyDigits(input.value));
      if (caretAtEnd) input.setSelectionRange(input.value.length, input.value.length);
    });
    if (input.value) input.value = formatter(onlyDigits(input.value));
  }

  const formatters = {
    cpf: function (v) {
      v = v.slice(0, 11);
      return v.replace(/(\d{3})(\d)/, "$1.$2")
              .replace(/(\d{3})(\d)/, "$1.$2")
              .replace(/(\d{3})(\d{1,2})$/, "$1-$2");
    },
    documento: function (v) {
      if (v.length <= 11) return formatters.cpf(v);
      v = v.slice(0, 14);
      return v.replace(/(\d{2})(\d)/, "$1.$2")
              .replace(/(\d{3})(\d)/, "$1.$2")
              .replace(/(\d{3})(\d)/, "$1/$2")
              .replace(/(\d{4})(\d{1,2})$/, "$1-$2");
    },
    telefone: function (v) {
      v = v.slice(0, 11);
      if (v.length <= 10) return v.replace(/(\d{2})(\d)/, "($1) $2").replace(/(\d{4})(\d)/, "$1-$2");
      return v.replace(/(\d{2})(\d)/, "($1) $2").replace(/(\d{5})(\d)/, "$1-$2");
    },
    cep: function (v) { return v.slice(0, 8).replace(/(\d{5})(\d)/, "$1-$2"); }
  };

  // Selecionar por sufixo do nome (`$=`), nao por igualdade: campos dentro
  // de um formset (ex.: enderecos/contatos do paciente) sao renderizados
  // com um prefixo por linha (ex.: "addresses-0-postal_code"), entao um
  // seletor de igualdade exata nunca casaria com eles.
  document.querySelectorAll("input[name$='cpf'], input[name$='guardian_document'], input[name$='responsible_document']")
    .forEach(function (input) { applyMask(input, formatters.cpf); });
  document.querySelectorAll("input[name='document']")
    .forEach(function (input) { applyMask(input, formatters.documento); });
  document.querySelectorAll("input[name$='phone'], input[name$='mobile'], input[name$='whatsapp']")
    .forEach(function (input) { applyMask(input, formatters.telefone); });
  document.querySelectorAll("input[name$='postal_code']")
    .forEach(function (input) { applyMask(input, formatters.cep); });

  // --- preenchimento automatico de endereco pelo CEP (ViaCEP) -------------
  // Os nomes dos campos de destino nao sao padronizados entre os
  // formularios (Clinic/Professional usam "address", PatientAddress usa
  // "street"), entao procura por qualquer um dos dois. Usa o mesmo prefixo
  // do campo de CEP (extraido do proprio "name") para achar os campos
  // irmaos corretos mesmo dentro de uma linha de formset repetida.
  document.querySelectorAll("input[name$='postal_code']").forEach(function (input) {
    const prefix = input.name.slice(0, input.name.length - "postal_code".length);
    function sibling(fieldName) {
      return document.querySelector("[name='" + prefix + fieldName + "']");
    }
    const streetField = sibling("street") || sibling("address");
    const districtField = sibling("district");
    const cityField = sibling("city");
    const stateField = sibling("state");
    if (!streetField && !districtField && !cityField && !stateField) return;

    const feedback = document.createElement("div");
    feedback.className = "form-text";
    input.insertAdjacentElement("afterend", feedback);

    input.addEventListener("blur", function () {
      const cep = onlyDigits(input.value);
      if (cep.length !== 8) { feedback.textContent = ""; return; }
      feedback.textContent = "Consultando CEP...";
      feedback.className = "form-text text-body-secondary";
      fetch("/app/cep/" + cep + "/", { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            feedback.textContent = result.data.detail || "Nao foi possivel consultar o CEP.";
            feedback.className = "form-text text-danger";
            return;
          }
          if (streetField && result.data.street) streetField.value = result.data.street;
          if (districtField && result.data.district) districtField.value = result.data.district;
          if (cityField && result.data.city) cityField.value = result.data.city;
          if (stateField && result.data.state) stateField.value = result.data.state;
          feedback.textContent = "Endereco preenchido automaticamente (edite se necessario).";
          feedback.className = "form-text text-success";
        })
        .catch(function () {
          feedback.textContent = "Nao foi possivel consultar o CEP. Preencha o endereco manualmente.";
          feedback.className = "form-text text-danger";
        });
    });
  });

  // --- carregamento de horarios livres na tela de agendamento -------------
  const slotsBox = document.getElementById("jjaSlots");
  if (slotsBox) {
    const professionalField = document.getElementById("id_professional");
    const dateField = document.getElementById("id_date");
    const serviceField = document.getElementById("id_service");
    const timeField = document.getElementById("id_time");

    function loadSlots() {
      if (!professionalField || !professionalField.value || !dateField || !dateField.value) {
        slotsBox.innerHTML = '<p class="text-body-secondary small mb-0">Selecione profissional e data para ver os horarios livres.</p>';
        return;
      }
      const params = new URLSearchParams({
        professional: professionalField.value,
        date: dateField.value
      });
      if (serviceField && serviceField.value) params.append("service", serviceField.value);

      slotsBox.innerHTML = '<div class="spinner-border spinner-border-sm"></div>';
      fetch(slotsBox.dataset.url + "?" + params.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (!data.slots || !data.slots.length) {
            slotsBox.innerHTML = '<p class="text-body-secondary small mb-0">Nenhuma disponibilidade cadastrada para este dia.</p>';
            return;
          }
          slotsBox.innerHTML = data.slots.map(function (slot) {
            const cls = slot.available ? "btn-outline-primary" : "btn-outline-secondary disabled";
            const title = slot.available ? "Horario livre" : slot.reason;
            return '<button type="button" class="btn btn-sm ' + cls + ' m-1 jja-slot-btn" ' +
                   'data-time="' + slot.start + '" title="' + title + '">' + slot.start + "</button>";
          }).join("");
          slotsBox.querySelectorAll(".jja-slot-btn:not(.disabled)").forEach(function (button) {
            button.addEventListener("click", function () {
              if (timeField) timeField.value = button.dataset.time;
              slotsBox.querySelectorAll(".jja-slot-btn").forEach(function (other) {
                other.classList.remove("active");
              });
              button.classList.add("active");
            });
          });
        })
        .catch(function () {
          slotsBox.innerHTML = '<p class="text-danger small mb-0">Nao foi possivel carregar os horarios.</p>';
        });
    }

    [professionalField, dateField, serviceField].forEach(function (field) {
      field && field.addEventListener("change", loadSlots);
    });
    loadSlots();
  }

  // --- atalho de busca (tecla /) ------------------------------------------
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && !/input|textarea|select/i.test(event.target.tagName)) {
      const search = document.querySelector(".jja-search input");
      if (search) { event.preventDefault(); search.focus(); }
    }
  });
})();
