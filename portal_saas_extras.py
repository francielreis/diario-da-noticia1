"""Personalização e anúncios isolados por cliente do Painel Master SaaS."""
import re
from urllib.parse import urlparse
from flask import abort, flash, redirect, request, url_for


MARCA_TEMPLATE = r"""
<h1>Personalizar {{ portal.nome }}</h1>
<div class="card">
<p>Configure as cores, o slogan e o logotipo exclusivos do seu portal.</p>
<form method="post" enctype="multipart/form-data">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="slogan">Slogan do portal</label>
<input id="slogan" name="slogan" maxlength="180" required value="{{ marca.slogan if marca else 'Notícias com responsabilidade' }}">
<label for="cor">Cor principal</label>
<input id="cor" name="cor" type="color" style="width:100px;height:56px" value="{{ marca.cor if marca else '#1455a2' }}">
<label for="logo">Logotipo (PNG, JPG ou WEBP, até 10 MB)</label>
<input id="logo" name="logo" type="file" accept="image/png,image/jpeg,image/webp">
{% if marca and marca.logo %}<p><img style="max-width:200px;max-height:120px;object-fit:contain"
src="{{ marca.logo }}" alt="Logotipo atual"></p>{% endif %}
<p><button type="submit">Salvar personalização</button>
<a class="btn secondary" href="{{ url_for('saas_cliente_painel',slug=portal.slug) }}">Voltar</a></p>
</form></div>
"""

ANUNCIO_TEMPLATE = r"""
<h1>Patrocinadores — {{ portal.nome }}</h1>
<div class="card"><h2>Novo anúncio</h2>
<form method="post" enctype="multipart/form-data">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="titulo">Nome do anunciante</label>
<input id="titulo" name="titulo" maxlength="150" required>
<label for="link">Link do patrocinador (opcional)</label>
<input id="link" name="link" type="url" placeholder="https://example.com">
<label for="imagem">Banner (PNG, JPG ou WEBP, até 10 MB)</label>
<input id="imagem" name="imagem" type="file" accept="image/png,image/jpeg,image/webp" required>
<p><button type="submit">Cadastrar patrocinador</button></p></form></div>
<div class="card"><h2>Anúncios cadastrados ({{ anuncios|length }})</h2>
{% for anuncio in anuncios %}
<div class="card"><h3>{{ anuncio.titulo }}</h3><p class="muted">{{ 'Ativo' if anuncio.ativo else 'Pausado' }}</p>
<img src="{{ anuncio.imagem }}" alt="{{ anuncio.titulo }}" style="max-width:100%;max-height:150px;object-fit:contain">
<div class="row"><form method="post" action="{{ url_for('saas_cliente_alternar_anuncio',slug=portal.slug,anuncio_id=anuncio.id) }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button class="secondary" type="submit">{{ 'Pausar' if anuncio.ativo else 'Ativar' }}</button></form>
<form method="post" action="{{ url_for('saas_cliente_excluir_anuncio',slug=portal.slug,anuncio_id=anuncio.id) }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button class="danger" type="submit" onclick="return confirm('Excluir anunciante?')">Excluir</button></form>
</div></div>{% else %}<p>Nenhum patrocinador cadastrado.</p>{% endfor %}
<a class="btn secondary" href="{{ url_for('saas_cliente_painel',slug=portal.slug) }}">Voltar ao painel</a>
</div>
"""


def register_extras(app, db, Portal, cliente_required, portal_por_slug,
                    exigir_csrf, salvar_imagem, pagina):
    class MarcaCliente(db.Model):
        __tablename__ = "saas_marcas"
        id = db.Column(db.Integer, primary_key=True)
        portal_id = db.Column(db.Integer, db.ForeignKey("saas_portais.id"),
                              nullable=False, unique=True, index=True)
        slogan = db.Column(db.String(180), nullable=False,
                           default="Notícias com responsabilidade")
        cor = db.Column(db.String(7), nullable=False, default="#1455a2")
        logo = db.Column(db.Text)

    class AnuncioCliente(db.Model):
        __tablename__ = "saas_anuncios"
        id = db.Column(db.Integer, primary_key=True)
        portal_id = db.Column(db.Integer, db.ForeignKey("saas_portais.id"),
                              nullable=False, index=True)
        titulo = db.Column(db.String(150), nullable=False)
        imagem = db.Column(db.Text, nullable=False)
        link = db.Column(db.Text)
        ativo = db.Column(db.Boolean, nullable=False, default=True)

    with app.app_context():
        db.create_all()

    app.extensions["saas_models"].update({
        "marca": MarcaCliente,
        "anuncio": AnuncioCliente,
    })

    def obter_marca(portal_id):
        return db.session.scalar(
            db.select(MarcaCliente).where(MarcaCliente.portal_id == portal_id)
        )

    def obter_anuncios(portal_id):
        return db.session.scalars(
            db.select(AnuncioCliente)
            .where(AnuncioCliente.portal_id == portal_id, AnuncioCliente.ativo.is_(True))
            .order_by(AnuncioCliente.id.desc()).limit(12)
        ).all()

    app.extensions["saas_obter_marca"] = obter_marca
    app.extensions["saas_obter_anuncios"] = obter_anuncios

    def anuncio_do_portal(portal_id, anuncio_id):
        anuncio = db.session.scalar(db.select(AnuncioCliente).where(
            AnuncioCliente.id == anuncio_id,
            AnuncioCliente.portal_id == portal_id
        ))
        if anuncio is None:
            abort(404)
        return anuncio

    @app.route("/p/<slug>/admin/configuracoes", methods=["GET", "POST"])
    @cliente_required
    def saas_cliente_config(slug):
        portal = portal_por_slug(slug)
        marca = obter_marca(portal.id)
        if request.method == "POST":
            exigir_csrf()
            slogan = request.form.get("slogan", "").strip()[:180]
            cor = request.form.get("cor", "").strip().lower()
            if not slogan or not re.fullmatch(r"#[0-9a-f]{6}", cor):
                flash("Slogan ou cor inválidos.")
            else:
                arquivo = request.files.get("logo")
                novo_logo = None
                if arquivo and arquivo.filename:
                    try:
                        novo_logo = salvar_imagem(arquivo)
                    except (RuntimeError, ValueError) as erro:
                        flash(str(erro))
                        return redirect(url_for("saas_cliente_config", slug=slug))
                if marca is None:
                    marca = MarcaCliente(portal_id=portal.id)
                    db.session.add(marca)
                marca.slogan = slogan
                marca.cor = cor
                if novo_logo:
                    marca.logo = novo_logo
                db.session.commit()
                flash("Identidade visual atualizada.")
                return redirect(url_for("saas_cliente_config", slug=slug))
        return pagina(MARCA_TEMPLATE, titulo="Identidade visual",
                      portal=portal, privado=True)

    @app.route("/p/<slug>/admin/anuncios", methods=["GET", "POST"])
    @cliente_required
    def saas_cliente_anuncios(slug):
        portal = portal_por_slug(slug)
        if request.method == "POST":
            exigir_csrf()
            nome = request.form.get("titulo", "").strip()[:150]
            link = request.form.get("link", "").strip()
            arquivo = request.files.get("imagem")
            parsed = urlparse(link) if link else None
            if not nome or not arquivo or not arquivo.filename:
                flash("Informe o anunciante e envie uma imagem.")
            elif link and (parsed.scheme not in {"http", "https"} or not parsed.netloc
                           or parsed.username or parsed.password):
                flash("Link inválido: use https:// ou http://.")
            else:
                try:
                    imagem = salvar_imagem(arquivo)
                except (RuntimeError, ValueError) as erro:
                    flash(str(erro))
                else:
                    db.session.add(AnuncioCliente(
                        portal_id=portal.id, titulo=nome, imagem=imagem, link=link or None
                    ))
                    db.session.commit()
                    flash("Anunciante cadastrado.")
                    return redirect(url_for("saas_cliente_anuncios", slug=slug))
        anuncios = db.session.scalars(
            db.select(AnuncioCliente)
            .where(AnuncioCliente.portal_id == portal.id)
            .order_by(AnuncioCliente.id.desc())
        ).all()
        return pagina(ANUNCIO_TEMPLATE, titulo="Patrocinadores",
                      portal=portal, anuncios=anuncios, privado=True)

    @app.route("/p/<slug>/admin/anuncios/<int:anuncio_id>/alternar", methods=["POST"])
    @cliente_required
    def saas_cliente_alternar_anuncio(slug, anuncio_id):
        exigir_csrf()
        portal = portal_por_slug(slug)
        anuncio = anuncio_do_portal(portal.id, anuncio_id)
        anuncio.ativo = not anuncio.ativo
        db.session.commit()
        flash("Situação do patrocinador atualizada.")
        return redirect(url_for("saas_cliente_anuncios", slug=slug))

    @app.route("/p/<slug>/admin/anuncios/<int:anuncio_id>/excluir", methods=["POST"])
    @cliente_required
    def saas_cliente_excluir_anuncio(slug, anuncio_id):
        exigir_csrf()
        portal = portal_por_slug(slug)
        anuncio = anuncio_do_portal(portal.id, anuncio_id)
        db.session.delete(anuncio)
        db.session.commit()
        flash("Patrocinador excluído.")
        return redirect(url_for("saas_cliente_anuncios", slug=slug))
