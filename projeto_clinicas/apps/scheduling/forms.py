"""Formularios da agenda."""
from __future__ import annotations

from datetime import datetime, timedelta

from django import forms
from django.utils import timezone

from apps.accounts.forms import BootstrapFormMixin
from apps.clinics.models import InsurancePlan, Room, Service
from apps.finance.models import PaymentMethod
from apps.patients.models import Patient
from apps.professionals.models import Professional
from apps.scheduling.models import Appointment, ScheduleBlock, ScheduleTemplate, WaitingListEntry

#: Campos financeiros do agendamento -- so aparecem no formulario para quem
#: tem a permissao ``appointment.payment`` numa clinica com o modulo
#: financeiro habilitado (ver ``AppointmentForm.__init__``).
PAYMENT_FIELD_NAMES = (
    "gross_amount", "discount", "addition", "payment_method", "pay_now",
    "amount_paid_now", "is_courtesy",
)


class AppointmentForm(BootstrapFormMixin, forms.ModelForm):
    """
    Criacao/edicao de agendamento.

    Todos os querysets sao restritos a clinica ativa: mesmo que alguem altere
    o HTML e envie o UUID de um paciente de outra clinica, o campo sera
    rejeitado ("Faca uma escolha valida").
    """

    date = forms.DateField(label="Data", widget=forms.DateInput(attrs={"type": "date"}))
    time = forms.TimeField(label="Horario", widget=forms.TimeInput(attrs={"type": "time"}))
    duration_minutes = forms.IntegerField(
        label="Duracao (min)", min_value=5, max_value=480, initial=30
    )

    # Financeiro (visivel apenas com a permissao ``appointment.payment``).
    gross_amount = forms.DecimalField(
        label="Valor da consulta", max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        help_text="Vazio = usa o valor de tabela do servico selecionado.",
    )
    discount = forms.DecimalField(
        label="Desconto", max_digits=10, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )
    addition = forms.DecimalField(
        label="Acrescimo", max_digits=10, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )
    payment_method = forms.ModelChoiceField(
        label="Forma de pagamento", queryset=PaymentMethod.objects.none(), required=False,
    )
    pay_now = forms.ChoiceField(
        label="Pagamento sera realizado agora?", choices=[("no", "Nao"), ("yes", "Sim")],
        required=False, initial="no", widget=forms.RadioSelect,
    )
    amount_paid_now = forms.DecimalField(
        label="Valor pago agora", max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        help_text="Vazio = considera o valor final (com desconto/acrescimo) como pago integralmente.",
    )
    is_courtesy = forms.BooleanField(label="Atendimento de cortesia (sem cobranca)", required=False)

    class Meta:
        model = Appointment
        fields = ["patient", "professional", "service", "room", "insurance", "notes",
                  "is_overbooking"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, clinic=None, user=None, **kwargs):
        self.clinic = clinic
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(status=Patient.Status.ACTIVE)
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["room"].queryset = Room.objects.filter(is_active=True)
        self.fields["insurance"].queryset = InsurancePlan.objects.filter(is_active=True)
        self.fields["service"].required = False
        self.fields["room"].required = False
        self.fields["insurance"].required = False

        # Sem a permissao (ou sem o modulo financeiro), os campos financeiros
        # sao removidos do formulario -- nao apenas ocultos no template --
        # para que nenhum valor injetado via POST manipulado seja processado.
        # Tambem so aparecem na criacao: apos o agendamento existir, o valor
        # e o pagamento sao geridos pela aba Financeiro do proprio agendamento.
        self.can_manage_payment = bool(
            not self.instance.is_saved and clinic and clinic.has_module_finance and user
            and user.has_clinic_perm("appointment.payment", clinic)
        )
        if self.can_manage_payment:
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(is_active=True)
        else:
            for name in PAYMENT_FIELD_NAMES:
                self.fields.pop(name, None)

        if self.instance.is_saved and self.instance.start_at:
            local = timezone.localtime(self.instance.start_at)
            self.fields["date"].initial = local.date()
            self.fields["time"].initial = local.time()
            self.fields["duration_minutes"].initial = self.instance.duration_minutes

    def clean(self):
        cleaned = super().clean()
        day = cleaned.get("date")
        moment = cleaned.get("time")
        if day and moment:
            start = timezone.make_aware(
                datetime.combine(day, moment), timezone.get_current_timezone()
            )
            cleaned["start_at"] = start
            duration = cleaned.get("duration_minutes") or 30
            cleaned["end_at"] = start + timedelta(minutes=duration)

        if "pay_now" in cleaned:
            cleaned["pay_now"] = cleaned.get("pay_now") == "yes"
            if cleaned["pay_now"] and cleaned.get("is_courtesy"):
                self.add_error(None, "Um atendimento de cortesia nao pode ter pagamento agora.")
            if cleaned["pay_now"] and not cleaned.get("payment_method"):
                self.add_error("payment_method", "Informe a forma de pagamento.")
        return cleaned


class QuickAppointmentForm(BootstrapFormMixin, forms.Form):
    """Agendamento rapido a partir de um horario livre da agenda."""

    patient = forms.ModelChoiceField(label="Paciente", queryset=Patient.objects.none())
    service = forms.ModelChoiceField(label="Servico", queryset=Service.objects.none(),
                                     required=False)
    notes = forms.CharField(label="Observacoes", required=False,
                            widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(status=Patient.Status.ACTIVE)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)


class ScheduleTemplateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ScheduleTemplate
        fields = [
            "professional",
            "weekday",
            "start_time",
            "end_time",
            "slot_minutes",
            "break_start",
            "break_end",
            "room",
            "valid_from",
            "valid_to",
            "is_active",
        ]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "break_start": forms.TimeInput(attrs={"type": "time"}),
            "break_end": forms.TimeInput(attrs={"type": "time"}),
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_to": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, professional=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["room"].queryset = Room.objects.filter(is_active=True)
        if professional is not None:
            self.fields["professional"].initial = professional
            self.fields["professional"].disabled = True


class ScheduleBlockForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ScheduleBlock
        fields = ["professional", "room", "kind", "start_at", "end_at", "reason"]
        widgets = {
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["professional"].required = False
        self.fields["room"].queryset = Room.objects.filter(is_active=True)
        self.fields["room"].required = False
        for name in ("start_at", "end_at"):
            self.fields[name].input_formats = ["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"]


class CancelAppointmentForm(BootstrapFormMixin, forms.Form):
    #: As 4 opcoes pedidas pelo usuario mapeiam para 2 acoes reais do sistema
    #: -- "manter credito"/"manter conforme politica" nao geram nenhuma
    #: transacao nova; "estorno"/"devolucao" geram um lancamento de estorno.
    PAYMENT_DISPOSITION_CHOICES = [
        ("keep_credit", "Manter valor como credito para o paciente"),
        ("keep_policy", "Manter valor recebido (conforme politica da clinica)"),
        ("refund", "Registrar estorno no financeiro"),
        ("return", "Registrar devolucao ao paciente"),
    ]

    reason = forms.CharField(
        label="Motivo do cancelamento", max_length=200,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    payment_disposition = forms.ChoiceField(
        label="O que fazer com o valor ja recebido?",
        choices=PAYMENT_DISPOSITION_CHOICES, required=False, widget=forms.RadioSelect,
        initial="keep_policy",
    )

    #: Escolhas que resultam em estorno real no financeiro.
    REFUND_DISPOSITIONS = {"refund", "return"}


class WaitingListForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = WaitingListEntry
        fields = ["patient", "professional", "service", "preferred_period", "priority", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(status=Patient.Status.ACTIVE)
        self.fields["professional"].queryset = Professional.objects.filter(is_active=True)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
