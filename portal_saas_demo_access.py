"""Acesso de demonstração de uso único e entrada do proprietário.

Os valores do convite vêm exclusivamente de variáveis de ambiente do serviço
de testes. Tokens nunca são gravados em texto puro no banco nem no repositório.
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timezone
from flask import abort, redirect, request, session, url_for


def register_demo_access(app, db, Portal, master_required, exigir_csrf, csrf_token):
    class ConviteDemo(db.Model):
        __tablename__ = "saas_convites_demo"
        id = db.Column(db.Integer, primary_key=True)
        portal_id = db.Column(db.Integer, db.ForeignKey("saas_portais.id"), nullable=False)
        token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
        expira_em = db.Column(db.DateTime, nullable=False)
        utilizado_em = db.Column(db.DateTime)

    with app.app_context():
        db.create_all()
        # Funciona somente quando habilitado explicitamente pelo Render de testes.
        if os.environ.get("SAAS_DEMO_BOOTSTRAP_ENABLED") == "1":
            slug = os.environ.get("SAAS_DEMO_SLUG", "")
            nome = os.environ.get("SAAS_DEMO_NAME", "")
            dono = os.environ.get("SAAS_DEMO_OWNER", "")
            usuario = os.environ.get("SAAS_DEMO_USER", "")
            senha_hash = os.environ.get("SAAS_DEMO_PASSWORD_HASH", "")
            convite_hash = os.environ.get("SAAS_DEMO_INVITE_SHA256", "")
            validade = os.environ.get("SAAS_DEMO_INVITE_EXPIRES_UTC", "")
            try:
                expira = datetime.strptime(validade, "%Y-%m-%dT%H:%M:%SZ")
            except (ValueError, TypeError):
                expira = None

            if (re.fullmatch(r"[a-z0-9-]{3,45}", slug)
                    and nome and dono and usuario and senha_hash
                    and re.fullmatch(r"[a-f0-9]{64}", convite_hash)
                    and expira and datetime.utcnow() < expira):
                portal = db.session.scalar(
                    db.select(Portal).where(Portal.slug == slug)
                )
                if portal is None:
                    portal = Portal(
                        nome=nome[:120], slug=slug, dono=dono[:120],
                        usuario=usuario[:80], senha_hash=senha_hash,
                        plano="basico", ativo=True,
                    )
                    db.session.add(portal)
                    db.session.flush()

                convite = db.session.scalar(
                    db.select(ConviteDemo).where(ConviteDemo.token_hash == convite_hash)
                )
                if convite is None:
                    db.session.add(ConviteDemo(
                        portal_id=portal.id,
                        token_hash=convite_hash,
                        expira_em=expira,
                    ))
                db.session.commit()

    @app.route("/convite-demo/<token>")
    def saas_entrar_convite(token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{30,100}", token):
            abort(404)
        hashed = hashlib.sha256(token.encode("ascii")).hexdigest()
        momento = datetime.utcnow()
        # UPDATE condicional para impedir consumo simultâneo do mesmo link.
        # Sem retorno ao banco, não há autenticação.
        result = db.session.execute(
            db.update(ConviteDemo)
            .where(ConviteDemo.token_hash == hashed,
                   ConviteDemo.utilizado_em.is_(None),
                   ConviteDemo.expira_em > momento)
            .values(utilizado_em=momento)
        )
        if result.rowcount != 1:
            db.session.rollback()
            abort(410, description="Este convite já foi usado ou expirou.")
        convite = db.session.scalar(
            db.select(ConviteDemo).where(ConviteDemo.token_hash == hashed)
        )
        portal = db.session.get(Portal, convite.portal_id)
        if portal is None or not portal.ativo:
            db.session.rollback()
            abort(403)
        db.session.commit()
        session.clear()
        session["saas_portal_id"] = portal.id
        session.permanent = True
        csrf_token()
        resposta = redirect(url_for("saas_cliente_painel", slug=portal.slug), code=303)
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        return resposta

    @app.route("/master/portal/<int:portal_id>/entrar", methods=["POST"])
    @master_required
    def saas_master_entrar_como_cliente(portal_id):
        exigir_csrf()
        portal = db.get_or_404(Portal, portal_id)
        if not portal.ativo:
            abort(403, description="Este portal está suspenso.")
        # Somente o master pode acessar o painel como cliente por este atalho.
        session.clear()
        session["saas_portal_id"] = portal.id
        session.permanent = True
        csrf_token()
        return redirect(url_for("saas_cliente_painel", slug=portal.slug), code=303)

    app.extensions["saas_models"]["convite_demo"] = ConviteDemo
