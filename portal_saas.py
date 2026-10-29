"""Painel de revenda de portais da Reis Tech e Software.

Módulo isolado do portal editorial legado. Os sites dos clientes funcionam
em /p/<slug>/ e podem ser migrados para domínios próprios em etapa posterior.
"""
import os
import re
import hmac
from datetime import datetime
from functools import wraps

from flask import (
    abort, flash, redirect, render_template_string, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash


PLANOS = {"basico": 99, "profissional": 150, "premium": 249}
CATEGORIAS_CLIENTE = (
    "Piauí", "Política", "Brasil", "Economia", "Cidades",
    "Esportes", "Educação", "Saúde", "Polícia", "Tecnologia"
)

BASE_INICIO = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="{{ 'noindex,nofollow' if privado else 'index,follow' }}">
<title>{{ titulo }} · Reis Tech e Software</title>
<style>
:root{--accent:{{ marca.cor if marca else '#1455a2' }};font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;color:#1b2230;background:#f5f7fa}
*{box-sizing:border-box}body{margin:0}a{color:var(--accent);text-decoration:none}
header{background:#111b2e;color:#fff;padding:16px 0}
header a{color:white}.wrap{width:min(1080px,calc(100% - 32px));margin:auto}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
main{padding:24px 0 50px}h1{font-size:clamp(25px,4vw,37px)}h2{font-size:21px}
p{line-height:1.55}small,.muted{color:#607083}
.card{background:#fff;border:1px solid #e4e9f0;border-radius:12px;padding:20px;margin:15px 0}
table{width:100%;border-collapse:collapse;background:white}
th,td{border-bottom:1px solid #e3e8f0;padding:13px 10px;text-align:left;vertical-align:top}
.table-scroll{overflow-x:auto}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:15px}
label{display:block;font-weight:600;margin:13px 0 5px}input,select,textarea{
font:inherit;width:100%;max-width:100%;padding:11px;border:1px solid #c7d0dc;border-radius:7px}
textarea{min-height:130px}button,.btn{display:inline-block;font:inherit;background:var(--accent);
color:white;border:none;border-radius:7px;padding:10px 15px;cursor:pointer}
.btn.secondary,button.secondary{background:#e4ebf4;color:#1c324d}
button.danger{background:#a32929}.inline{display:inline}
.inline button{margin:2px}.notice{padding:12px;border:1px solid #cfddf2;
background:#eff5ff;border-radius:8px;margin:14px 0}
.tag{display:inline-block;padding:3px 8px;border-radius:20px;background:#edf1f7;font-size:12px}
.tag.active{background:#d4f4e3;color:#145632}.tag.inactive{background:#ffe1e1;color:#7b2727}
.news-image{width:100%;max-height:310px;object-fit:cover;border-radius:8px}
.article-body{white-space:pre-wrap;line-height:1.75}
footer{border-top:1px solid #e3e8f0;padding:23px 0;color:#637080;font-size:13px}
@media(max-width:600px){th,td{padding:9px 6px;font-size:13px}.card{padding:16px}}
</style></head><body>
<header><div class="wrap top">
{% if portal and not privado %}<div class="row">{% if marca and marca.logo %}<img src="{{ marca.logo }}" alt="Logotipo de {{ portal.nome }}" style="height:50px;max-width:145px;object-fit:contain">{% endif %}<strong>{{ portal.nome }}</strong></div>{% else %}<strong>Reis Tech e Software</strong>{% endif %}
<nav><a href="{{ url_for('saas_master') if privado and modo_master else (url_for('saas_portal',slug=portal.slug) if portal else '/') }}">Início</a></nav>
</div></header><main class="wrap">
{% for msg in get_flashed_messages() %}<div class="notice" role="status">{{ msg }}</div>{% endfor %}
"""

BASE_FIM = r"""</main><footer><div class="wrap">Plataforma desenvolvida por Reis Tech e Software</div></footer>
</body></html>"""

MASTER_LOGIN = r"""
<div class="card" style="max-width:480px;margin:40px auto">
<h1>Acesso Master</h1><p class="muted">Administração exclusiva dos portais de clientes.</p>
<form method="post">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="usuario">Usuário master</label><input id="usuario" name="usuario" required autocomplete="username">
<label for="senha">Senha</label><input id="senha" name="senha" type="password" required autocomplete="current-password">
<p><button type="submit">Entrar</button></p></form></div>
"""

MASTER_PAINEL = r"""
<div class="row" style="justify-content:space-between"><h1>Painel Master</h1>
<div class="row"><a class="btn secondary" href="{{ url_for('saas_master_mensalidades') }}">Mensalidades</a><a class="btn secondary" href="{{ url_for('saas_master_sair') }}">Sair</a></div></div>
<p>Cadastre clientes e controle os acessos. Os portais ficam separados do Diário da Notícia original.</p>
<div class="cols">
<div class="card"><h2>{{ portais|length }}</h2><p>Portais cadastrados</p></div>
<div class="card"><h2>{{ ativos }}</h2><p>Portais ativos</p></div>
<div class="card"><h2>R$ {{ receita_prevista }}</h2><p>Mensalidades previstas, não recebimentos</p></div>
</div>
<div class="card"><h2>Cadastrar novo portal</h2>
<form method="post" action="{{ url_for('saas_master_criar') }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<div class="cols">
<div><label for="nome">Nome do portal</label><input id="nome" name="nome" maxlength="120" required placeholder="Portal Picos Agora"></div>
<div><label for="slug">Endereço (slug)</label><input id="slug" name="slug" maxlength="45" minlength="3" required placeholder="picos-agora" pattern="[a-z0-9-]{3,45}"></div>
<div><label for="dono">Nome do responsável</label><input id="dono" name="dono" maxlength="120" required></div>
<div><label for="usuario">Usuário do cliente</label><input id="usuario" name="usuario" maxlength="80" required></div>
<div><label for="senha">Senha inicial (mín. 10 caracteres)</label><input id="senha" name="senha" type="password" minlength="10" required></div>
<div><label for="plano">Plano</label><select id="plano" name="plano">
{% for p, valor in planos.items() %}<option value="{{ p }}">{{ p|capitalize }} — R$ {{ valor }}/mês</option>{% endfor %}
</select></div></div><p><button type="submit">+ Criar portal</button></p></form>
</div>
<div class="card"><h2>Portais dos clientes</h2>
<div class="table-scroll"><table>
<thead><tr><th>Portal</th><th>Responsável</th><th>Plano</th><th>Status / Gestão</th></tr></thead>
<tbody>{% for p in portais %}<tr>
<td><strong>{{ p.nome }}</strong><br><a href="{{ url_for('saas_portal',slug=p.slug) }}" target="_blank" rel="noopener">/p/{{ p.slug }}/</a><br><a href="{{ url_for('saas_cliente_login',slug=p.slug) }}" target="_blank" rel="noopener">Painel do cliente</a>
<form method="post" action="{{ url_for('saas_master_entrar_como_cliente',portal_id=p.id) }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button type="submit" class="secondary">Entrar sem senha como Master</button></form></td>
<td>{{ p.dono }}</td><td>R$ {{ planos[p.plano] }}/mês</td>
<td><span class="tag {{ 'active' if p.ativo else 'inactive' }}">{{ 'Ativo' if p.ativo else 'Suspenso' }}</span>
<form method="post" action="{{ url_for('saas_master_alterar',portal_id=p.id) }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="plano-{{ p.id }}">Plano</label><select id="plano-{{ p.id }}" name="plano">
{% for key, val in planos.items() %}<option value="{{ key }}" {{ 'selected' if key == p.plano else '' }}>{{ key|capitalize }} (R$ {{ val }})</option>{% endfor %}
</select>
<label for="senha-{{ p.id }}">Nova senha (opcional)</label><input id="senha-{{ p.id }}" name="senha" type="password" minlength="10" autocomplete="new-password">
<label for="ativo-{{ p.id }}">Situação</label><select id="ativo-{{ p.id }}" name="ativo">
<option value="1" {{ 'selected' if p.ativo else '' }}>Ativo</option>
<option value="0" {{ 'selected' if not p.ativo else '' }}>Suspenso</option>
</select><p><button class="secondary" type="submit">Salvar alterações</button></p>
</form></td></tr>
{% else %}<tr><td colspan="4">Nenhum cliente cadastrado.</td></tr>{% endfor %}</tbody>
</table></div></div>
"""

CLIENTE_LOGIN = r"""
<div class="card" style="max-width:480px;margin:30px auto">
<h1>Painel: {{ portal.nome }}</h1>
{% if not portal.ativo %}<p>Este portal está com o painel editorial suspenso. Contate o suporte.</p>
{% else %}<form method="post">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="usuario">Usuário</label><input id="usuario" name="usuario" required autocomplete="username">
<label for="senha">Senha</label><input id="senha" name="senha" type="password" required autocomplete="current-password">
<p><button>Entrar</button></p></form>{% endif %}</div>
"""

CLIENTE_PAINEL = r"""
<div class="row" style="justify-content:space-between"><h1>{{ portal.nome }} — Redação</h1>
<a href="{{ url_for('saas_cliente_sair',slug=portal.slug) }}" class="btn secondary">Sair</a></div>
<p class="muted">Seu conteúdo é independente dos outros clientes.</p>
<div class="row">
<a class="btn" href="{{ url_for('saas_cliente_nova',slug=portal.slug) }}">+ Publicar notícia</a>
<a class="btn secondary" href="{{ url_for('saas_portal',slug=portal.slug) }}" target="_blank" rel="noopener">Ver meu portal</a>
<a class="btn secondary" href="{{ url_for('saas_cliente_config',slug=portal.slug) }}">Personalizar</a>
<a class="btn secondary" href="{{ url_for('saas_cliente_anuncios',slug=portal.slug) }}">Patrocinadores</a>
</div><div class="card"><h2>Notícias ({{ noticias|length }})</h2>
<div class="table-scroll"><table><thead><tr><th>Título</th><th>Categoria</th><th>Ações</th></tr></thead><tbody>
{% for n in noticias %}<tr><td>{{ n.titulo }}</td><td>{{ n.categoria }}</td>
<td><a class="btn secondary" href="{{ url_for('saas_cliente_editar',slug=portal.slug,noticia_id=n.id) }}">Editar</a>
<form class="inline" method="post" action="{{ url_for('saas_cliente_excluir',slug=portal.slug,noticia_id=n.id) }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button class="danger" onclick="return confirm('Excluir a notícia?')" type="submit">Excluir</button></form></td></tr>
{% else %}<tr><td colspan="3">Nenhuma notícia cadastrada.</td></tr>{% endfor %}
</tbody></table></div></div>
"""

NOTICIA_EDITOR = r"""
<h1>{{ 'Editar notícia' if noticia else 'Publicar notícia' }} — {{ portal.nome }}</h1>
<div class="card"><form method="post" enctype="multipart/form-data">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="categoria">Categoria</label><select id="categoria" name="categoria">
{% for c in categorias %}<option value="{{ c }}" {{ 'selected' if noticia and noticia.categoria == c else '' }}>{{ c }}</option>{% endfor %}
</select>
<label for="titulo">Título</label><input id="titulo" name="titulo" maxlength="250" required value="{{ noticia.titulo if noticia else '' }}">
<label for="resumo">Resumo</label><textarea id="resumo" name="resumo" maxlength="2000" required>{{ noticia.resumo if noticia else '' }}</textarea>
<label for="conteudo">Texto da notícia</label><textarea id="conteudo" name="conteudo" required style="min-height:290px">{{ noticia.conteudo if noticia else '' }}</textarea>
<label for="imagem">Imagem (PNG, JPG ou WEBP, até 10 MB)</label><input id="imagem" name="imagem" type="file" accept="image/png,image/jpeg,image/webp">
{% if noticia and noticia.imagem %}<p><img src="{{ noticia.imagem }}" alt="" class="news-image"></p>{% endif %}
<p class="row"><button type="submit">Salvar notícia</button>
<a class="btn secondary" href="{{ url_for('saas_cliente_painel',slug=portal.slug) }}">Voltar</a></p>
</form></div>
"""

PORTAL_HOME = r"""
<div class="row" style="justify-content:space-between">
<div><h1>{{ portal.nome }}</h1><p class="muted">{{ marca.slogan if marca else 'Notícias e informação da região' }}</p></div></div>
<div class="cols">
{% for n in noticias %}
<article class="card">
{% if n.imagem %}<img class="news-image" src="{{ n.imagem }}" loading="lazy" alt="Imagem: {{ n.titulo }}">{% endif %}
<p><small>{{ n.categoria }} · {{ n.criado_em.strftime('%d/%m/%Y') }}</small></p>
<h2><a href="{{ url_for('saas_noticia',slug=portal.slug,noticia_id=n.id) }}">{{ n.titulo }}</a></h2>
<p>{{ n.resumo }}</p></article>
{% else %}<div class="card"><p>Este portal ainda não publicou notícias.</p></div>{% endfor %}
</div>
{% if anuncios %}<section class="card"><h2>Publicidade</h2><div class="cols">
{% for a in anuncios %}<div>{% if a.link %}<a href="{{ a.link }}" target="_blank" rel="noopener noreferrer sponsored nofollow">{% endif %}
<img class="news-image" src="{{ a.imagem }}" alt="Publicidade: {{ a.titulo }}" loading="lazy">
{% if a.link %}</a>{% endif %}<p><small>{{ a.titulo }}</small></p></div>{% endfor %}
</div></section>{% endif %}
"""

NOTICIA_PUBLICA = r"""
<article class="card">
<a href="{{ url_for('saas_portal',slug=portal.slug) }}">← Voltar ao {{ portal.nome }}</a>
<p><small>{{ noticia.categoria }} · {{ noticia.criado_em.strftime('%d/%m/%Y às %H:%M') }}</small></p>
<h1>{{ noticia.titulo }}</h1><p>{{ noticia.resumo }}</p>
{% if noticia.imagem %}<img class="news-image" src="{{ noticia.imagem }}" alt="Imagem: {{ noticia.titulo }}">{% endif %}
<div class="article-body">{{ noticia.conteudo }}</div></article>
"""


def register_portals(app, db, templates, csrf_token, exigir_csrf, salvar_imagem):
    """Registra o sistema novo sem modificar as tabelas do Diário existente."""

    class PortalCliente(db.Model):
        __tablename__ = "saas_portais"
        id = db.Column(db.Integer, primary_key=True)
        nome = db.Column(db.String(120), nullable=False)
        slug = db.Column(db.String(45), unique=True, nullable=False, index=True)
        dono = db.Column(db.String(120), nullable=False)
        usuario = db.Column(db.String(80), nullable=False)
        senha_hash = db.Column(db.String(256), nullable=False)
        plano = db.Column(db.String(25), nullable=False, default="basico")
        ativo = db.Column(db.Boolean, nullable=False, default=True)
        criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    class NoticiaCliente(db.Model):
        __tablename__ = "saas_noticias"
        id = db.Column(db.Integer, primary_key=True)
        portal_id = db.Column(
            db.Integer, db.ForeignKey("saas_portais.id"),
            nullable=False, index=True
        )
        categoria = db.Column(db.String(100), nullable=False)
        titulo = db.Column(db.String(250), nullable=False)
        resumo = db.Column(db.Text, nullable=False)
        conteudo = db.Column(db.Text, nullable=False)
        imagem = db.Column(db.Text)
        criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # A criação é aditiva: não altera ou migra as tabelas legadas.
    with app.app_context():
        db.create_all()

    app.extensions["saas_models"] = {
        "portal": PortalCliente,
        "noticia": NoticiaCliente,
    }

    def pagina(conteudo, *, titulo, portal=None, privado=False, modo_master=False, **kwargs):
        obter_marca = app.extensions.get("saas_obter_marca")
        marca = obter_marca(portal.id) if obter_marca and portal else None
        return render_template_string(
            BASE_INICIO + conteudo + BASE_FIM, titulo=titulo, portal=portal,
            marca=marca, privado=privado, modo_master=modo_master,
            csrf_token=csrf_token, **kwargs
        )

    def portal_por_slug(slug):
        portal = db.session.scalar(
            db.select(PortalCliente).where(PortalCliente.slug == slug)
        )
        if portal is None:
            abort(404)
        return portal

    def master_required(func):
        @wraps(func)
        def interno(*args, **kwargs):
            if not session.get("saas_master"):
                return redirect(url_for("saas_master"))
            return func(*args, **kwargs)
        return interno

    def cliente_required(func):
        @wraps(func)
        def interno(slug, *args, **kwargs):
            portal = portal_por_slug(slug)
            if not portal.ativo:
                abort(403, description="Publicação suspensa para este portal.")
            if session.get("saas_portal_id") != portal.id:
                return redirect(url_for("saas_cliente_login", slug=slug))
            return func(slug, *args, **kwargs)
        return interno

    @app.route("/master", methods=["GET", "POST"])
    def saas_master():
        if session.get("saas_master"):
            return redirect(url_for("saas_master_painel"))
        if request.method == "POST":
            exigir_csrf()
            usuario = os.environ.get("MASTER_USER", "")
            hash_senha = os.environ.get("MASTER_PASSWORD_HASH", "")
            entrada_usuario = request.form.get("usuario", "")
            entrada_senha = request.form.get("senha", "")
            if (usuario and hash_senha
                    and hmac.compare_digest(entrada_usuario, usuario)
                    and check_password_hash(hash_senha, entrada_senha)):
                session.clear()
                session["saas_master"] = True
                session.permanent = True
                csrf_token()
                return redirect(url_for("saas_master_painel"))
            flash("Credenciais inválidas ou conta Master não configurada.")
        return pagina(MASTER_LOGIN, titulo="Acesso Master", privado=True, modo_master=True)

    @app.route("/master/painel")
    @master_required
    def saas_master_painel():
        portais = db.session.scalars(db.select(PortalCliente).order_by(PortalCliente.id.desc())).all()
        ativos = sum(bool(p.ativo) for p in portais)
        receita_prevista = sum(PLANOS.get(p.plano, 0) for p in portais if p.ativo)
        return pagina(
            MASTER_PAINEL, titulo="Painel Master", privado=True, modo_master=True,
            portais=portais, ativos=ativos, receita_prevista=receita_prevista,
            planos=PLANOS
        )

    @app.route("/master/criar", methods=["POST"])
    @master_required
    def saas_master_criar():
        exigir_csrf()
        nome = request.form.get("nome", "").strip()[:120]
        slug = request.form.get("slug", "").strip().lower()
        dono = request.form.get("dono", "").strip()[:120]
        usuario = request.form.get("usuario", "").strip()[:80]
        senha = request.form.get("senha", "")
        plano = request.form.get("plano", "")
        if not nome or not dono or not usuario:
            flash("Preencha nome, responsável e usuário.")
        elif not re.fullmatch(r"[a-z0-9-]{3,45}", slug):
            flash("O endereço deve ter 3 a 45 caracteres, somente letras minúsculas, números e hífen.")
        elif len(senha) < 10:
            flash("A senha inicial precisa de pelo menos 10 caracteres.")
        elif plano not in PLANOS:
            flash("Selecione um plano válido.")
        elif db.session.scalar(db.select(PortalCliente).where(PortalCliente.slug == slug)):
            flash("Esse endereço já foi cadastrado.")
        else:
            portal = PortalCliente(
                nome=nome, slug=slug, dono=dono, usuario=usuario,
                senha_hash=generate_password_hash(senha), plano=plano, ativo=True
            )
            db.session.add(portal)
            try:
                db.session.commit()
                flash("Portal criado! O cliente já pode acessar seu painel.")
            except Exception:
                db.session.rollback()
                app.logger.exception("Falha ao criar portal.")
                flash("Não foi possível salvar o portal. Confira os dados.")
        return redirect(url_for("saas_master_painel"))

    @app.route("/master/portal/<int:portal_id>/alterar", methods=["POST"])
    @master_required
    def saas_master_alterar(portal_id):
        exigir_csrf()
        portal = db.get_or_404(PortalCliente, portal_id)
        plano = request.form.get("plano", "")
        ativo = request.form.get("ativo", "")
        senha = request.form.get("senha", "")
        if plano not in PLANOS or ativo not in {"0", "1"}:
            abort(400)
        if senha and len(senha) < 10:
            flash("A nova senha deve ter pelo menos 10 caracteres.")
            return redirect(url_for("saas_master_painel"))
        portal.plano = plano
        portal.ativo = ativo == "1"
        if senha:
            portal.senha_hash = generate_password_hash(senha)
        db.session.commit()
        flash("Dados do cliente atualizados.")
        return redirect(url_for("saas_master_painel"))

    @app.route("/master/sair")
    def saas_master_sair():
        session.clear()
        return redirect(url_for("saas_master"))

    @app.route("/p/<slug>/")
    def saas_portal(slug):
        portal = portal_por_slug(slug)
        noticias = db.session.scalars(
            db.select(NoticiaCliente)
            .where(NoticiaCliente.portal_id == portal.id)
            .order_by(NoticiaCliente.criado_em.desc(), NoticiaCliente.id.desc())
            .limit(50)
        ).all()
        obter_anuncios = app.extensions.get("saas_obter_anuncios")
        anuncios = obter_anuncios(portal.id) if obter_anuncios else []
        return pagina(PORTAL_HOME, titulo=portal.nome, portal=portal,
                      noticias=noticias, anuncios=anuncios)

    @app.route("/p/<slug>/noticia/<int:noticia_id>")
    def saas_noticia(slug, noticia_id):
        portal = portal_por_slug(slug)
        noticia = db.session.scalar(
            db.select(NoticiaCliente).where(
                NoticiaCliente.id == noticia_id,
                NoticiaCliente.portal_id == portal.id
            )
        )
        if noticia is None:
            abort(404)
        return pagina(NOTICIA_PUBLICA, titulo=noticia.titulo, portal=portal, noticia=noticia)

    @app.route("/p/<slug>/admin", methods=["GET", "POST"])
    def saas_cliente_login(slug):
        portal = portal_por_slug(slug)
        if session.get("saas_portal_id") == portal.id and portal.ativo:
            return redirect(url_for("saas_cliente_painel", slug=slug))
        if request.method == "POST":
            exigir_csrf()
            if not portal.ativo:
                abort(403, description="Painel suspenso.")
            login = request.form.get("usuario", "")
            senha = request.form.get("senha", "")
            if (hmac.compare_digest(login, portal.usuario)
                    and check_password_hash(portal.senha_hash, senha)):
                session.clear()
                session["saas_portal_id"] = portal.id
                session.permanent = True
                csrf_token()
                return redirect(url_for("saas_cliente_painel", slug=slug))
            flash("Usuário ou senha inválidos.")
        return pagina(CLIENTE_LOGIN, titulo="Acesso do Cliente", portal=portal, privado=True)

    @app.route("/p/<slug>/admin/painel")
    @cliente_required
    def saas_cliente_painel(slug):
        portal = portal_por_slug(slug)
        noticias = db.session.scalars(
            db.select(NoticiaCliente).where(NoticiaCliente.portal_id == portal.id)
            .order_by(NoticiaCliente.criado_em.desc(), NoticiaCliente.id.desc())
        ).all()
        return pagina(CLIENTE_PAINEL, titulo="Painel Editorial", portal=portal,
                      noticias=noticias, privado=True)

    def salvar_noticia_do_cliente(portal, noticia=None):
        exigir_csrf()
        categoria = request.form.get("categoria", "").strip()
        titulo = request.form.get("titulo", "").strip()[:250]
        resumo = request.form.get("resumo", "").strip()
        conteudo = request.form.get("conteudo", "").strip()
        if categoria not in CATEGORIAS_CLIENTE or not titulo or not resumo or not conteudo:
            flash("Preencha categoria, título, resumo e notícia.")
            return False
        imagem = None
        arquivo = request.files.get("imagem")
        if arquivo and arquivo.filename:
            try:
                imagem = salvar_imagem(arquivo)
            except (ValueError, RuntimeError) as erro:
                flash(str(erro))
                return False
        if noticia is None:
            noticia = NoticiaCliente(portal_id=portal.id)
            db.session.add(noticia)
        noticia.categoria = categoria
        noticia.titulo = titulo
        noticia.resumo = resumo
        noticia.conteudo = conteudo
        if imagem:
            noticia.imagem = imagem
        db.session.commit()
        flash("Notícia salva com sucesso.")
        return True

    @app.route("/p/<slug>/admin/noticias/nova", methods=["GET", "POST"])
    @cliente_required
    def saas_cliente_nova(slug):
        portal = portal_por_slug(slug)
        if request.method == "POST" and salvar_noticia_do_cliente(portal):
            return redirect(url_for("saas_cliente_painel", slug=slug))
        return pagina(NOTICIA_EDITOR, titulo="Nova notícia", portal=portal,
                      noticia=None, categorias=CATEGORIAS_CLIENTE, privado=True)

    @app.route("/p/<slug>/admin/noticias/<int:noticia_id>/editar", methods=["GET", "POST"])
    @cliente_required
    def saas_cliente_editar(slug, noticia_id):
        portal = portal_por_slug(slug)
        noticia = db.session.scalar(db.select(NoticiaCliente).where(
            NoticiaCliente.id == noticia_id, NoticiaCliente.portal_id == portal.id
        ))
        if noticia is None:
            abort(404)
        if request.method == "POST" and salvar_noticia_do_cliente(portal, noticia):
            return redirect(url_for("saas_cliente_painel", slug=slug))
        return pagina(NOTICIA_EDITOR, titulo="Editar notícia", portal=portal,
                      noticia=noticia, categorias=CATEGORIAS_CLIENTE, privado=True)

    @app.route("/p/<slug>/admin/noticias/<int:noticia_id>/excluir", methods=["POST"])
    @cliente_required
    def saas_cliente_excluir(slug, noticia_id):
        exigir_csrf()
        portal = portal_por_slug(slug)
        noticia = db.session.scalar(db.select(NoticiaCliente).where(
            NoticiaCliente.id == noticia_id, NoticiaCliente.portal_id == portal.id
        ))
        if noticia is None:
            abort(404)
        db.session.delete(noticia)
        db.session.commit()
        flash("Notícia excluída.")
        return redirect(url_for("saas_cliente_painel", slug=slug))

    @app.route("/p/<slug>/admin/sair")
    def saas_cliente_sair(slug):
        portal_por_slug(slug)
        session.clear()
        return redirect(url_for("saas_cliente_login", slug=slug))

    # Extensões isoladas: marca e publicidade por cliente.
    from portal_saas_extras import register_extras
    register_extras(app, db, PortalCliente, cliente_required,
                    portal_por_slug, exigir_csrf, salvar_imagem, pagina)

    from portal_saas_finance import register_finance
    register_finance(app, db, PortalCliente, master_required, exigir_csrf, pagina)

    from portal_saas_demo_access import register_demo_access
    register_demo_access(app, db, PortalCliente, master_required,
                         exigir_csrf, csrf_token)
