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

  // --- busca inteligente (paciente/profissional no agendamento) -----------
  // Contrato via atributos data-*, sem depender de nenhuma biblioteca:
  //   data-autocomplete-url    endpoint JSON ({"results": [{id, text, detail}]})
  //   data-autocomplete-target id do <input type="hidden"> com o valor real
  document.querySelectorAll("input[data-autocomplete-url]").forEach(function (input) {
    const hidden = document.getElementById(input.dataset.autocompleteTarget);
    if (!hidden) return;

    const box = document.createElement("div");
    box.className = "jja-autocomplete-results";
    input.insertAdjacentElement("afterend", box);
    input.setAttribute("autocomplete", "off");

    let timer = null;

    function hide() { box.classList.remove("show"); box.innerHTML = ""; }

    function renderResults(items) {
      if (!items.length) {
        box.innerHTML = '<div class="jja-autocomplete-empty">Nenhum resultado encontrado.</div>';
      } else {
        box.innerHTML = items.map(function (item) {
          return '<button type="button" class="jja-autocomplete-item" data-id="' + item.id +
                 '" data-text="' + item.text.replace(/"/g, "&quot;") + '">' +
                 '<strong>' + item.text + '</strong>' +
                 (item.detail ? '<small>' + item.detail + '</small>' : "") +
                 "</button>";
        }).join("");
      }
      box.classList.add("show");
    }

    function search(term) {
      fetch(input.dataset.autocompleteUrl + "?q=" + encodeURIComponent(term), {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (response) { return response.json(); })
        .then(function (data) { renderResults(data.results || []); })
        .catch(function () {
          box.innerHTML = '<div class="jja-autocomplete-empty">Nao foi possivel buscar agora.</div>';
          box.classList.add("show");
        });
    }

    input.addEventListener("input", function () {
      if (hidden.value) {
        hidden.value = "";
        hidden.dispatchEvent(new Event("change"));
      }
      const term = input.value.trim();
      clearTimeout(timer);
      if (term.length < 2) { hide(); return; }
      timer = setTimeout(function () { search(term); }, 250);
    });

    input.addEventListener("focus", function () {
      const term = input.value.trim();
      if (term.length >= 2 && !hidden.value) search(term);
    });

    box.addEventListener("mousedown", function (event) {
      const item = event.target.closest(".jja-autocomplete-item");
      if (!item) return;
      hidden.value = item.dataset.id;
      input.value = item.dataset.text;
      hide();
      hidden.dispatchEvent(new Event("change"));
    });

    document.addEventListener("click", function (event) {
      if (event.target !== input && !box.contains(event.target)) hide();
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
            // O rotulo de disponibilidade fica sempre visivel (nao so no
            // title/tooltip) -- em celular/tablet nao ha hover.
            const label = slot.available ? "Disponivel" : (slot.reason || "Ocupado");
            return '<button type="button" class="btn btn-sm ' + cls + ' m-1 jja-slot-btn d-flex flex-column align-items-center lh-sm py-1" ' +
                   'data-time="' + slot.start + '" title="' + label + '">' +
                   '<span class="fw-semibold">' + slot.start + '</span>' +
                   '<span class="jja-slot-label" style="font-size:.7rem;">' + label + '</span>' +
                   '</button>';
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

  // --- confirmacao antes de salvar (tela de novo agendamento) -------------
  // Passo de revisao 100% no navegador: mostra um resumo do que foi
  // preenchido e so envia o formulario depois de um segundo clique.
  const confirmModalEl = document.getElementById("jjaConfirmModal");
  const reviewButton = document.getElementById("jjaReviewBtn");
  if (confirmModalEl && reviewButton && window.bootstrap) {
    const form = reviewButton.closest("form");
    const modal = new bootstrap.Modal(confirmModalEl);

    function textFor(id) {
      const el = document.getElementById(id);
      if (!el) return "-";
      if (el.tagName === "SELECT") {
        const option = el.options[el.selectedIndex];
        return option && option.value ? option.text : "-";
      }
      return el.value ? el.value : "-";
    }

    reviewButton.addEventListener("click", function () {
      // Campos type="hidden" ficam fora da validacao nativa do navegador
      // (mesmo com "required"), entao paciente/profissional -- que usam
      // busca + campo oculto -- precisam ser checados manualmente aqui.
      const patientId = document.getElementById("id_patient");
      const professionalId = document.getElementById("id_professional");
      const patientName = document.getElementById("jjaPatientSearch");
      const professionalName = document.getElementById("jjaProfessionalSearch");
      let missing = false;
      if (patientId && !patientId.value) {
        patientName.classList.add("is-invalid");
        missing = true;
      } else if (patientName) {
        patientName.classList.remove("is-invalid");
      }
      if (professionalId && !professionalId.value) {
        professionalName.classList.add("is-invalid");
        missing = true;
      } else if (professionalName) {
        professionalName.classList.remove("is-invalid");
      }
      if (missing) {
        (patientId && !patientId.value ? patientName : professionalName).focus();
        return;
      }
      if (!form.reportValidity()) return;

      confirmModalEl.querySelector("[data-review=patient]").textContent =
        (patientName && patientName.value) || "-";
      confirmModalEl.querySelector("[data-review=professional]").textContent =
        (professionalName && professionalName.value) || "-";
      confirmModalEl.querySelector("[data-review=service]").textContent = textFor("id_service");
      confirmModalEl.querySelector("[data-review=room]").textContent = textFor("id_room");
      const date = textFor("id_date");
      const time = textFor("id_time");
      confirmModalEl.querySelector("[data-review=datetime]").textContent =
        (date !== "-" ? date.split("-").reverse().join("/") : "-") + " as " + time;
      const valueField = document.getElementById("id_gross_amount");
      confirmModalEl.querySelector("[data-review=value]").textContent =
        valueField && valueField.value ? "R$ " + valueField.value : "Valor de tabela do servico";

      modal.show();
    });

    confirmModalEl.querySelector("[data-confirm-submit]").addEventListener("click", function () {
      modal.hide();
      form.submit();
    });
  }

  // --- atalho de busca (tecla /) ------------------------------------------
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && !/input|textarea|select/i.test(event.target.tagName)) {
      const search = document.querySelector(".jja-search input");
      if (search) { event.preventDefault(); search.focus(); }
    }
  });
})();
