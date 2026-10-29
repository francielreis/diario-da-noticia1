"""Registro manual de mensalidades para o Painel Master.

Não movimenta dinheiro, não processa PIX e não emite nota fiscal. Os
registros são lançados exclusivamente pelo proprietário da plataforma.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from flask import abort, flash, redirect, request, url_for


FINANCE_TEMPLATE = r"""
<h1>Mensalidades dos clientes</h1>
<p>Registre manualmente os pagamentos recebidos. Este painel não cobra, não
confirma PIX automaticamente e não emite nota fiscal.</p>
<div class="cols"><div class="card"><h2>R$ {{ '%.2f'|format(total_pago / 100) }}</h2>
<p>Valor total registrado como recebido</p></div>
<div class="card"><h2>{{ pagamentos|length }}</h2><p>Competências cadastradas</p></div></div>
<div class="card"><h2>Registrar ou atualizar competência</h2>
<form method="post" action="{{ url_for('saas_master_salvar_mensalidade') }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<div class="cols"><div>
<label for="portal_id">Cliente</label>
<select id="portal_id" name="portal_id" required>
{% for p in portais %}<option value="{{ p.id }}">{{ p.nome }} — {{ p.slug }}</option>{% endfor %}
</select></div><div>
<label for="competencia">Mês de referência</label><input id="competencia" name="competencia" type="month" required value="{{ mes_atual }}">
</div><div><label for="valor">Valor em R$</label>
<input id="valor" name="valor" inputmode="decimal" value="150,00" required>
</div><div><label for="pago">Status</label><select id="pago" name="pago">
<option value="0">Pendente</option><option value="1">Pago (conferido manualmente)</option>
</select></div></div><p><button>Salvar lançamento</button></p></form></div>
<div class="card"><h2>Histórico de pagamentos</h2>
<div class="table-scroll"><table><thead><tr><th>Portal</th><th>Referência</th><th>Valor</th><th>Situação</th></tr></thead><tbody>
{% for c in pagamentos %}<tr>
<td>{{ nomes.get(c.portal_id, 'Portal excluído') }}</td>
<td>{{ c.competencia }}</td><td>R$ {{ '%.2f'|format(c.valor_centavos / 100) }}</td>
<td><span class="tag {{ 'active' if c.pago_em else 'inactive' }}">
{{ ('Pago em ' + c.pago_em.strftime('%d/%m/%Y')) if c.pago_em else 'Pendente' }}</span></td>
</tr>{% else %}<tr><td colspan="4">Nenhuma mensalidade registrada.</td></tr>{% endfor %}
</tbody></table></div></div>
<p><a class="btn secondary" href="{{ url_for('saas_master_painel') }}">Voltar ao Painel Master</a></p>
"""


def register_finance(app, db, Portal, master_required, exigir_csrf, pagina):
    class MensalidadeCliente(db.Model):
        __tablename__ = "saas_mensalidades"
        id = db.Column(db.Integer, primary_key=True)
        portal_id = db.Column(db.Integer, db.ForeignKey("saas_portais.id"),
                              nullable=False, index=True)
        competencia = db.Column(db.String(7), nullable=False)
        valor_centavos = db.Column(db.Integer, nullable=False)
        pago_em = db.Column(db.DateTime)
        __table_args__ = (db.UniqueConstraint(
            "portal_id", "competencia", name="uq_saas_portal_competencia"
        ),)

    with app.app_context():
        db.create_all()

    app.extensions["saas_models"]["mensalidade"] = MensalidadeCliente

    @app.route("/master/mensalidades")
    @master_required
    def saas_master_mensalidades():
        portais = db.session.scalars(db.select(Portal).order_by(Portal.nome)).all()
        pagamentos = db.session.scalars(
            db.select(MensalidadeCliente).order_by(
                MensalidadeCliente.competencia.desc(),
                MensalidadeCliente.id.desc()
            ).limit(300)
        ).all()
        total_pago = db.session.scalar(
            db.select(db.func.coalesce(db.func.sum(MensalidadeCliente.valor_centavos), 0))
            .where(MensalidadeCliente.pago_em.is_not(None))
        ) or 0
        return pagina(FINANCE_TEMPLATE, titulo="Mensalidades", privado=True,
                      modo_master=True, portais=portais, pagamentos=pagamentos,
                      total_pago=total_pago, nomes={p.id: p.nome for p in portais},
                      mes_atual=datetime.utcnow().strftime("%Y-%m"))

    @app.route("/master/mensalidades/salvar", methods=["POST"])
    @master_required
    def saas_master_salvar_mensalidade():
        exigir_csrf()
        portal_id = request.form.get("portal_id", type=int)
        competencia = request.form.get("competencia", "").strip()
        valor = request.form.get("valor", "").strip().replace(" ", "")
        pago = request.form.get("pago", "")
        if not portal_id or db.session.get(Portal, portal_id) is None:
            abort(404)
        if not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", competencia):
            abort(400, description="Competência inválida.")
        if pago not in {"0", "1"}:
            abort(400, description="Status inválido.")
        # Formatos aceitos: 150,00 e 150.00, sem milhares.
        if not re.fullmatch(r"[0-9]{1,6}([,.][0-9]{1,2})?", valor):
            abort(400, description="Valor inválido.")
        try:
            quantia = Decimal(valor.replace(",", "."))
            centavos = int((quantia * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            abort(400, description="Valor inválido.")
        if centavos <= 0:
            abort(400, description="O valor deve ser positivo.")

        registro = db.session.scalar(db.select(MensalidadeCliente).where(
            MensalidadeCliente.portal_id == portal_id,
            MensalidadeCliente.competencia == competencia
        ))
        if registro is None:
            registro = MensalidadeCliente(portal_id=portal_id, competencia=competencia)
            db.session.add(registro)
        registro.valor_centavos = centavos
        registro.pago_em = datetime.utcnow() if pago == "1" else None
        db.session.commit()
        flash("Mensalidade registrada manualmente.")
        return redirect(url_for("saas_master_mensalidades"))
