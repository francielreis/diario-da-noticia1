from jinja2 import DictLoader
from flask import Response, Flask, render_template, request, redirect, url_for, session, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from urllib.parse import urlparse
import cloudinary
import cloudinary.uploader
import hmac
import os
import secrets

app = Flask(__name__)

secret_key = os.environ.get('SECRET_KEY')

if not secret_key:
    if os.environ.get('RENDER'):
        raise RuntimeError('Configure a variável SECRET_KEY no Render.')
    secret_key = 'somente-desenvolvimento-local'

app.secret_key = secret_key

app.config.update(
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8)
)

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

database_url = os.environ.get('DATABASE_URL')

if database_url:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace(
            'postgres://', 'postgresql+psycopg://', 1
        )
    elif database_url.startswith('postgresql://'):
        database_url = database_url.replace(
            'postgresql://', 'postgresql+psycopg://', 1
        )

app.config['SQLALCHEMY_DATABASE_URI'] = (
    database_url or 'sqlite:///diario.db'
)

db = SQLAlchemy(app)

CATEGORIAS = [
    'Piauí', 'Política', 'Brasil', 'Economia', 'Cidades',
    'Esportes', 'Educação', 'Saúde', 'Polícia', 'Tecnologia'
]

EXTENSOES_PERMITIDAS = {'png', 'jpg', 'jpeg', 'webp'}


def arquivo_permitido(nome_arquivo):
    if not nome_arquivo or '.' not in nome_arquivo:
        return False

    extensao = nome_arquivo.rsplit('.', 1)[1].lower()
    return extensao in EXTENSOES_PERMITIDAS


def salvar_imagem(arquivo):
    if not arquivo or not arquivo.filename:
        return ''

    if not arquivo_permitido(arquivo.filename):
        raise ValueError(
            'Formato não permitido. Use JPG, JPEG, PNG ou WEBP.'
        )

    configuracoes = {
        'CLOUDINARY_CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME'),
        'CLOUDINARY_API_KEY': os.environ.get('CLOUDINARY_API_KEY'),
        'CLOUDINARY_API_SECRET': os.environ.get('CLOUDINARY_API_SECRET')
    }

    faltando = [
        nome for nome, valor in configuracoes.items() if not valor
    ]

    if faltando:
        raise RuntimeError(
            'Cloudinary não configurado. Faltam: ' + ', '.join(faltando)
        )

    resultado = cloudinary.uploader.upload(
        arquivo,
        folder='diario-da-noticia',
        resource_type='image'
    )

    url = resultado.get('secure_url')

    if not url:
        raise RuntimeError(
            'O Cloudinary não retornou o endereço da imagem.'
        )

    return url


def obter_public_id(caminho_imagem):
    if not caminho_imagem:
        return None

    if 'res.cloudinary.com' not in caminho_imagem:
        return None

    try:
        partes = caminho_imagem.split('/upload/', 1)

        if len(partes) != 2:
            return None

        partes_caminho = partes[1].split('/')
        indice_versao = None

        for i, parte in enumerate(partes_caminho):
            if parte.startswith('v') and parte[1:].isdigit():
                indice_versao = i
                break

        if indice_versao is not None:
            partes_caminho = partes_caminho[indice_versao + 1:]

        caminho = '/'.join(partes_caminho)
        public_id = os.path.splitext(caminho)[0]

        return public_id or None

    except Exception:
        return None


def apagar_imagem(caminho_imagem):
    public_id = obter_public_id(caminho_imagem)

    if not public_id:
        return

    try:
        cloudinary.uploader.destroy(
            public_id,
            resource_type='image'
        )
    except Exception as erro:
        app.logger.warning(
            'Não foi possível apagar imagem do Cloudinary: %r',
            erro
        )


def link_http_valido(link):
    if not link:
        return True

    try:
        parsed = urlparse(link)
        return (
            parsed.scheme in {'http', 'https'}
            and bool(parsed.netloc)
        )
    except Exception:
        return False


def csrf_token():
    token = session.get('_csrf_token')

    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token

    return token


app.jinja_env.globals['csrf_token'] = csrf_token


def csrf_valido():
    esperado = session.get('_csrf_token', '')
    recebido = request.form.get('_csrf_token', '')

    return bool(
        esperado
        and recebido
        and hmac.compare_digest(esperado, recebido)
    )


def exigir_csrf():
    if request.method == 'POST' and not csrf_valido():
        abort(
            400,
            description=(
                'Formulário expirado ou inválido. '
                'Atualize a página e tente novamente.'
            )
        )


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin'))

        return func(*args, **kwargs)

    return wrapper


class Noticia(db.Model):
    __tablename__ = 'noticias'

    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(100), nullable=False)
    titulo = db.Column(db.String(250), nullable=False)
    resumo = db.Column(db.Text, nullable=True)
    conteudo = db.Column(db.Text, nullable=True)
    imagem = db.Column(db.Text, nullable=True)
    data_publicacao = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        index=True
    )


class Patrocinador(db.Model):
    __tablename__ = 'patrocinadores'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    imagem = db.Column(db.Text, nullable=True)
    link = db.Column(db.Text, nullable=True)
    ativo = db.Column(db.Boolean, default=True)


with app.app_context():
    db.create_all()


@app.template_filter('data_br')
def data_br(valor):
    if not valor:
        return ''

    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)

    local = valor.astimezone(ZoneInfo('America/Fortaleza'))
    return local.strftime('%d/%m/%Y às %H:%M')


@app.context_processor
def contexto_portal():
    if request.endpoint not in {'inicio', 'noticia'}:
        return {}

    agora = datetime.now(ZoneInfo('America/Fortaleza'))

    meses = (
        'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
        'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'
    )

    patrocinadores = db.session.scalars(
        db.select(Patrocinador)
        .where(Patrocinador.ativo.is_(True))
        .order_by(Patrocinador.id.desc())
    ).all()

    return {
        'categorias': CATEGORIAS,
        'patrocinadores': patrocinadores,
        'hoje_portal': (
            f'{agora.day} de {meses[agora.month - 1]} de {agora.year}'
        ),
        'ano_portal': agora.year,
        'instagram_url': 'https://www.instagram.com/diariodanoticia/'
    }


def noticias_recentes(limite=5, categoria=None, excluir=None):
    stmt = db.select(Noticia)

    if categoria:
        stmt = stmt.where(Noticia.categoria == categoria)

    if excluir is not None:
        stmt = stmt.where(Noticia.id != excluir)

    return db.session.scalars(
        stmt.order_by(
            Noticia.data_publicacao.desc(),
            Noticia.id.desc()
        ).limit(limite)
    ).all()


@app.route('/')
def inicio():
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    categoria = request.args.get('categoria', '').strip()

    if categoria not in CATEGORIAS:
        categoria = ''

    busca = request.args.get('q', '').strip()[:200]
    stmt = db.select(Noticia)

    if categoria:
        stmt = stmt.where(Noticia.categoria == categoria)

    if busca:
        termo = f'%{busca}%'
        stmt = stmt.where(
            or_(
                Noticia.titulo.ilike(termo),
                Noticia.resumo.ilike(termo),
                Noticia.conteudo.ilike(termo)
            )
        )

    paginacao = db.paginate(
        stmt.order_by(
            Noticia.data_publicacao.desc(),
            Noticia.id.desc()
        ),
        page=page,
        per_page=15,
        error_out=False
    )

    secoes = []

    if page == 1 and not categoria and not busca:
        for cat in CATEGORIAS:
            items = noticias_recentes(4, categoria=cat)

            if items:
                secoes.append({
                    'nome': cat,
                    'noticias': items
                })

    return render_template(
        'index.html',
        noticias=paginacao.items,
        paginacao=paginacao,
        categoria_atual=categoria,
        busca=busca,
        secoes=secoes,
        ultimas=noticias_recentes()
    )


@app.route('/noticia/<int:id>')
def noticia(id):
    item = db.get_or_404(Noticia, id)

    return render_template(
        'noticia.html',
        noticia=item,
        categoria_atual=item.categoria,
        relacionadas=noticias_recentes(3, item.categoria, id),
        ultimas=noticias_recentes(5, excluir=id)
    )


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    erro = None

    if request.method == 'POST':
        exigir_csrf()

        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '')

        admin_usuario = os.environ.get('ADMIN_USER', '').strip()
        admin_senha = os.environ.get('ADMIN_PASSWORD', '')

        if not admin_usuario or not admin_senha:
            erro = (
                'Painel ainda não configurado. '
                'Defina ADMIN_USER e ADMIN_PASSWORD no Render.'
            )

        elif (
            hmac.compare_digest(usuario, admin_usuario)
            and hmac.compare_digest(senha, admin_senha)
        ):
            session.clear()
            session['admin'] = True
            session.permanent = True
            csrf_token()

            return redirect(url_for('painel'))

        else:
            erro = 'Usuário ou senha incorretos.'

    return render_template('login.html', erro=erro)


@app.route('/admin/painel')
@admin_required
def painel():
    noticias = db.session.scalars(
        db.select(Noticia)
        .order_by(Noticia.data_publicacao.desc())
    ).all()

    patrocinadores = db.session.scalars(
        db.select(Patrocinador)
        .order_by(Patrocinador.id.desc())
    ).all()

    return render_template(
        'painel.html',
        noticias=noticias,
        patrocinadores=patrocinadores
    )


@app.route('/admin/nova-noticia', methods=['GET', 'POST'])
@admin_required
def nova_noticia():
    erro = None

    if request.method == 'POST':
        exigir_csrf()

        categoria = request.form.get('categoria', '').strip()
        titulo = request.form.get('titulo', '').strip()
        resumo = request.form.get('resumo', '').strip()
        conteudo = request.form.get('conteudo', '').strip()

        if categoria not in CATEGORIAS:
            erro = 'Selecione uma categoria válida.'
        elif not titulo:
            erro = 'Informe o título.'
        elif not resumo:
            erro = 'Informe o resumo.'
        elif not conteudo:
            erro = 'Informe o conteúdo da notícia.'

        if erro:
            return render_template(
                'nova_noticia.html',
                erro=erro,
                categorias=CATEGORIAS
            )

        arquivo = request.files.get('imagem')

        try:
            imagem = salvar_imagem(arquivo)
        except Exception as erro_upload:
            return render_template(
                'nova_noticia.html',
                erro='Erro ao enviar a imagem: ' + str(erro_upload),
                categorias=CATEGORIAS
            )

        nova = Noticia(
            categoria=categoria,
            titulo=titulo,
            resumo=resumo,
            conteudo=conteudo,
            imagem=imagem
        )

        try:
            db.session.add(nova)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Erro ao salvar notícia.')

            return render_template(
                'nova_noticia.html',
                erro='Não foi possível salvar a notícia. Tente novamente.',
                categorias=CATEGORIAS
            )

        return redirect(url_for('noticia', id=nova.id))

    return render_template(
        'nova_noticia.html',
        erro=erro,
        categorias=CATEGORIAS
    )


@app.route('/admin/editar-noticia/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_noticia(id):
    noticia = db.get_or_404(Noticia, id)
    erro = None

    if request.method == 'POST':
        exigir_csrf()

        categoria = request.form.get('categoria', '').strip()
        titulo = request.form.get('titulo', '').strip()
        resumo = request.form.get('resumo', '').strip()
        conteudo = request.form.get('conteudo', '').strip()

        if categoria not in CATEGORIAS:
            erro = 'Selecione uma categoria válida.'
        elif not titulo:
            erro = 'Informe o título.'
        elif not resumo:
            erro = 'Informe o resumo.'
        elif not conteudo:
            erro = 'Informe o conteúdo da notícia.'

        if erro:
            return render_template(
                'editar_noticia.html',
                noticia=noticia,
                erro=erro,
                categorias=CATEGORIAS
            )

        imagem_antiga = noticia.imagem
        arquivo = request.files.get('imagem')
        nova_imagem = None

        if arquivo and arquivo.filename:
            try:
                nova_imagem = salvar_imagem(arquivo)
            except Exception as erro_upload:
                return render_template(
                    'editar_noticia.html',
                    noticia=noticia,
                    erro='Erro ao enviar a imagem: ' + str(erro_upload),
                    categorias=CATEGORIAS
                )

        noticia.categoria = categoria
        noticia.titulo = titulo
        noticia.resumo = resumo
        noticia.conteudo = conteudo

        if nova_imagem:
            noticia.imagem = nova_imagem

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Erro ao editar notícia.')

            return render_template(
                'editar_noticia.html',
                noticia=noticia,
                erro='Não foi possível salvar as alterações.',
                categorias=CATEGORIAS
            )

        if (
            nova_imagem
            and imagem_antiga
            and imagem_antiga != nova_imagem
        ):
            apagar_imagem(imagem_antiga)

        return redirect(url_for('noticia', id=noticia.id))

    return render_template(
        'editar_noticia.html',
        noticia=noticia,
        erro=erro,
        categorias=CATEGORIAS
    )


@app.route('/admin/excluir-noticia/<int:id>', methods=['POST'])
@admin_required
def excluir_noticia(id):
    exigir_csrf()

    noticia = db.get_or_404(Noticia, id)
    imagem = noticia.imagem

    try:
        db.session.delete(noticia)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Erro ao excluir notícia.')
        abort(500)

    apagar_imagem(imagem)
    return redirect(url_for('painel'))


@app.route('/admin/novo-patrocinador', methods=['GET', 'POST'])
@admin_required
def novo_patrocinador():
    erro = None

    if request.method == 'POST':
        exigir_csrf()

        nome = request.form.get('nome', '').strip()
        link = request.form.get('link', '').strip()
        arquivo = request.files.get('imagem')

        if not nome:
            erro = 'Informe o nome do patrocinador.'
        elif not link_http_valido(link):
            erro = 'O link deve começar com http:// ou https://.'
        elif not arquivo or not arquivo.filename:
            erro = 'Selecione uma imagem para o patrocinador.'

        if erro:
            return render_template(
                'novo_patrocinador.html',
                erro=erro
            )

        try:
            imagem = salvar_imagem(arquivo)
        except Exception as erro_upload:
            return render_template(
                'novo_patrocinador.html',
                erro='Erro ao enviar a imagem: ' + str(erro_upload)
            )

        patrocinador = Patrocinador(
            nome=nome,
            imagem=imagem,
            link=link,
            ativo=True
        )

        try:
            db.session.add(patrocinador)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Erro ao salvar patrocinador.')

            return render_template(
                'novo_patrocinador.html',
                erro='Não foi possível cadastrar o patrocinador.'
            )

        return redirect(url_for('painel'))

    return render_template('novo_patrocinador.html', erro=erro)


@app.route('/admin/patrocinador/<int:id>/alternar', methods=['POST'])
@admin_required
def alternar_patrocinador(id):
    exigir_csrf()

    patrocinador = db.get_or_404(Patrocinador, id)
    patrocinador.ativo = not patrocinador.ativo

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        abort(500)

    return redirect(url_for('painel'))


@app.route('/admin/excluir-patrocinador/<int:id>', methods=['POST'])
@admin_required
def excluir_patrocinador(id):
    exigir_csrf()

    patrocinador = db.get_or_404(Patrocinador, id)
    imagem = patrocinador.imagem

    try:
        db.session.delete(patrocinador)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Erro ao excluir patrocinador.')
        abort(500)

    apagar_imagem(imagem)
    return redirect(url_for('painel'))


@app.route('/admin/sair')
def sair():
    session.clear()
    return redirect(url_for('admin'))


@app.errorhandler(400)
def erro_400(error):
    return (
        '<h1>Solicitação inválida</h1><p>'
        + getattr(error, 'description', '')
        + "</p><p><a href='javascript:history.back()'>Voltar</a></p>",
        400
    )


@app.errorhandler(404)
def erro_404(error):
    return (
        "<h1>Página não encontrada</h1>"
        "<p><a href='/'>Voltar para o Diário da Notícia</a></p>",
        404
    )


@app.errorhandler(413)
def arquivo_grande(error):
    return (
        "<h1>Imagem muito grande</h1>"
        "<p>Envie uma imagem com até 10 MB.</p>"
        "<p><a href='javascript:history.back()'>Voltar</a></p>",
        413
    )


@app.errorhandler(500)
def erro_500(error):
    db.session.rollback()

    return (
        "<h1>Erro interno</h1>"
        "<p>Não foi possível concluir a operação. Tente novamente.</p>"
        "<p><a href='/'>Voltar para o portal</a></p>",
        500
    )


# Visual e páginas incluídos neste arquivo.

PORTAL_CSS = r"""
:root{--red:#ba1828;--ink:#17191c;--muted:#687078;--line:#e4e6e9;--paper:#fff;--soft:#f5f6f8}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}a{color:inherit;text-decoration:none}button,input{font:inherit}button{cursor:pointer}img{display:block;max-width:100%}[hidden]{display:none!important}h1,h2,h3,p{margin-top:0}a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid #de9b24;outline-offset:4px}.wrap{width:min(1180px,calc(100% - 48px));margin:auto}.sr-only,.skip:not(:focus){position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.skip:focus{display:block;padding:15px;background:white}.topline{border-bottom:1px solid var(--line);font-size:11px;color:#646970}.topline .wrap{display:flex;justify-content:space-between;gap:20px;padding:11px 0}.topline a{color:var(--ink)}.masthead{display:grid;grid-template-columns:320px 1fr 225px;align-items:center;gap:40px;padding:34px 0}.brand{display:inline-flex;flex-direction:column;line-height:.88;color:var(--ink)}.brand-over{font-weight:800;letter-spacing:4px;font-size:17px;line-height:1.5}.brand strong{font-weight:900;letter-spacing:-3px;font-size:53px}.brand-dot{color:var(--red)}.brand-tag{font-size:9px;letter-spacing:1.4px;margin-top:12px;color:var(--muted)}.search{display:flex;height:44px;border:1px solid var(--line);background:var(--soft);border-radius:3px;overflow:hidden}.search input{width:100%;min-width:0;padding:12px;border:0;background:transparent;font-size:13px}.search button{border:0;background:var(--red);color:white;padding:0 18px;font-size:12px;font-weight:bold}.redacao{font-size:10px;letter-spacing:1px;color:var(--muted)}.redacao strong{display:block;margin:8px 0;font-size:15px;letter-spacing:0;color:var(--ink)}.redacao a{font-size:11px;letter-spacing:0}.live-dot{display:inline-block;width:6px;height:6px;background:var(--red);border-radius:50%;margin-right:4px}.nav{background:var(--ink);border-top:3px solid var(--red)}.nav-inner{display:flex;overflow-x:auto;scrollbar-width:thin;gap:0}.nav a{flex-shrink:0;color:white;padding:17px 15px;font-size:12px;font-weight:700;border-bottom:3px solid transparent}.nav a:first-child{padding-left:0;padding-right:24px}.nav a.active,.nav a:hover{color:#ffb7be;border-bottom-color:var(--red)}.ad-top{max-width:1000px;margin:25px auto 30px}.ad-label{display:block;text-align:center;text-transform:uppercase;font-size:9px;letter-spacing:1.4px;color:#878c93;margin-bottom:8px}.ad img{width:100%;height:130px;object-fit:contain;background:var(--soft)}.ad-name{background:var(--soft);padding:30px;text-align:center;font-weight:bold}.ad-controls{display:flex;gap:10px;align-items:center;justify-content:center;margin-top:8px;color:var(--muted);font-size:10px}.ad-controls button{border:1px solid var(--line);background:white;padding:3px 10px}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:3px solid var(--ink);border-bottom:1px solid var(--line);padding:14px 0;margin:34px 0 22px}.section-heading h2{font-size:24px;letter-spacing:-.7px;margin:0}.section-heading a{font-size:11px;font-weight:bold;color:var(--red);white-space:nowrap}.editorial{font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:1.7px;color:var(--red);margin:27px 0 14px}.headline{text-align:center;max-width:990px;margin:25px auto 32px}.eyebrow{font-size:10px;font-weight:800;letter-spacing:1.3px;text-transform:uppercase;color:var(--red);display:block;margin-bottom:9px}.headline .eyebrow{display:flex;align-items:center;justify-content:center;gap:15px}.headline .eyebrow:before,.headline .eyebrow:after{content:'';width:90px;height:1px;background:var(--red)}.headline h1{font:700 clamp(30px,4.3vw,55px)/1.06 Georgia,'Times New Roman',serif;letter-spacing:-1.5px;margin:13px 0 15px}.headline h1 a:hover,.news-card h3:hover,.lead-story h2:hover{color:var(--red)}.headline p{font-size:15px;line-height:1.65;color:var(--muted);max-width:820px;margin:0 auto 12px}time{font-size:10px;line-height:1.6;color:var(--muted)}.hero-grid{display:grid;grid-template-columns:1.85fr 1fr 1fr;gap:24px;padding-bottom:26px;border-bottom:1px solid var(--line)}.hero-photo .news-photo{aspect-ratio:1.5}.hero-photo .news-photo img{width:100%;height:100%;object-fit:cover}.hero-photo-caption{padding:10px 0;font-size:10px;color:var(--muted)}.hero-list{border-left:1px solid var(--line);padding-left:22px;display:flex;flex-direction:column;gap:19px}.hero-list article{padding-bottom:16px;border-bottom:1px solid var(--line)}.hero-list h2{font-size:17px;line-height:1.3;margin:0 0 7px;letter-spacing:-.3px}.hero-secondary .news-photo{aspect-ratio:1.4}.hero-secondary h2{font:700 25px/1.15 Georgia,serif;margin:12px 0}.news-photo{background:var(--soft);overflow:hidden;aspect-ratio:1.6}.news-photo img{width:100%;height:100%;object-fit:cover}.photo-placeholder{height:100%;min-height:100px;display:flex;flex-direction:column;justify-content:center;align-items:center;background:linear-gradient(140deg,#24272d,#424750);color:#fff}.photo-placeholder span{font-size:10px;letter-spacing:3px}.photo-placeholder strong{font-size:26px;letter-spacing:-1px}.content-columns{display:grid;grid-template-columns:minmax(0,1fr) 285px;gap:35px}.news-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}.card-body{padding:13px 0}.news-card h3{font-size:18px;line-height:1.3;letter-spacing:-.35px;margin:0 0 10px}.news-card p{font-size:13px;color:var(--muted);line-height:1.6;margin:10px 0 0}.news-card.compact>a{display:grid;grid-template-columns:95px 1fr;gap:14px}.compact .news-photo{height:82px;aspect-ratio:auto}.compact .card-body{padding:0}.compact h3{font-size:14px}.compact .eyebrow{font-size:9px;margin-bottom:5px}.side-title{border-top:3px solid var(--red);font-size:17px;padding-top:14px;margin:34px 0 20px}.sidebar .ad{margin:24px 0}.ad-side img{height:auto;max-height:340px;object-fit:contain}.latest-list{display:grid;gap:18px}.latest-list article{border-bottom:1px solid var(--line);padding-bottom:17px}.newsletter{background:var(--soft);border-top:3px solid var(--red);padding:22px;margin-top:30px}.newsletter h3{font:700 25px/1.1 Georgia,serif}.newsletter p{font-size:13px;line-height:1.7;color:var(--muted)}.newsletter a{display:block;background:var(--ink);color:white;font-size:12px;font-weight:bold;text-align:center;padding:13px}.section-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:25px}.lead-story .news-photo{aspect-ratio:1.55}.lead-story h2{font:700 26px/1.12 Georgia,serif;margin:12px 0}.section-list{display:flex;flex-direction:column;gap:18px}.inline-ad{margin:30px 0}.filtered-title{font:700 36px/1.1 Georgia,serif;margin:30px 0 8px}.filter-summary{font-size:13px;color:var(--muted);margin-bottom:25px}.clear-filter{color:var(--red);font-weight:bold}.empty{padding:40px 25px;border:1px solid var(--line);background:var(--soft);line-height:1.7}.pagination{display:flex;justify-content:center;gap:6px;flex-wrap:wrap;margin:30px 0}.pagination a,.pagination span{display:block;padding:10px 14px;font-size:12px;border:1px solid var(--line)}.pagination .current{background:var(--ink);color:white}.pagination a:hover{border-color:var(--red);color:var(--red)}.footer{background:#17191c;color:white;margin-top:60px;padding:40px 0 20px}.footer-head{display:flex;justify-content:space-between;align-items:center;gap:30px;border-bottom:1px solid #36393e;padding-bottom:25px;margin-bottom:28px}.brand-footer{color:white}.brand-footer strong{font-size:40px}.brand-footer .brand-over{font-size:12px}.footer-head p{font-size:13px;color:#b8bdc5;line-height:1.7;margin:0}.footer h2{font-size:14px;margin-bottom:18px}.partner-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.partner{background:white;color:var(--ink);padding:14px;text-align:center;border-radius:3px}.partner img{width:100%;height:100px;object-fit:contain}.partner strong{display:block;font-size:11px;margin-top:8px}.footer-bottom{display:flex;justify-content:space-between;gap:20px;border-top:1px solid #36393e;margin-top:30px;padding-top:20px;font-size:10px;color:#b8bdc5}.breadcrumbs{font-size:11px;color:var(--muted);margin:25px 0}.breadcrumbs a{color:var(--red)}.article-head{max-width:920px;margin-bottom:26px}.article-head h1{font:700 clamp(32px,4.4vw,53px)/1.08 Georgia,serif;letter-spacing:-1px;margin:13px 0 18px}.article-head .summary{font-size:19px;line-height:1.65;color:var(--muted);margin-bottom:22px}.byline{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0;font-size:11px;display:flex;gap:20px;flex-wrap:wrap}.article-image{width:100%;height:auto;max-height:650px;object-fit:contain;background:var(--soft);margin:15px 0 25px}.article-text{font-size:18px;line-height:1.85;white-space:pre-line;overflow-wrap:anywhere;max-width:760px}.share{border-top:1px solid var(--line);margin:32px 0;padding-top:20px}.share h2{font-size:14px}.share-buttons{display:flex;flex-wrap:wrap;gap:9px}.share-buttons a,.share-buttons button{border:1px solid var(--line);background:white;font-size:12px;font-weight:bold;padding:12px 18px}.share-buttons .whatsapp{background:#167744;color:white;border-color:#167744}.share-status{font-size:12px;color:var(--muted);margin-top:10px}.related-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}h1,h2,h3,.brand{overflow-wrap:break-word}.news-card a:hover h3,.hero-list a:hover,.headline a:hover,.lead-story a:hover h2{color:var(--red)}
@media(min-width:1000px){.nav{position:sticky;top:0;z-index:10}}
@media(max-width:1000px){.masthead{grid-template-columns:280px 1fr;gap:25px}.redacao{display:none}.hero-grid{grid-template-columns:1.5fr 1fr}.hero-secondary{grid-column:1/-1}.content-columns{grid-template-columns:minmax(0,1fr) 240px;gap:25px}.news-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:740px){.wrap{width:calc(100% - 32px)}.topline .wrap>span{display:none}.topline{font-size:10px}.masthead{grid-template-columns:1fr;gap:24px;padding:25px 0}.brand{align-self:start}.brand strong{font-size:44px}.brand-over{font-size:14px}.search{height:42px}.nav a{padding:14px 13px;font-size:11px}.ad-top{margin:20px auto}.ad img{height:auto;max-height:170px;min-height:65px;object-fit:contain}.headline{margin:25px auto}.headline h1{letter-spacing:-.6px}.headline p{font-size:14px}.hero-grid{grid-template-columns:1fr;gap:20px}.hero-list{border-left:0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:14px}.hero-list h2{font-size:15px}.content-columns{display:block}.section-heading h2{font-size:22px}.news-grid{gap:18px}.news-card h3{font-size:16px}.news-card p{font-size:12px}.section-grid{grid-template-columns:1fr}.section-list{display:grid;grid-template-columns:1fr 1fr;gap:18px}.compact>a,.news-card.compact>a{grid-template-columns:1fr;gap:9px}.compact .news-photo{height:100px}.sidebar .latest-list{grid-template-columns:1fr 1fr}.sidebar .ad img{max-height:260px}.partner-grid{grid-template-columns:repeat(2,1fr)}.footer-head{align-items:start;flex-direction:column;gap:20px}.footer-bottom{flex-wrap:wrap}.article-head .summary{font-size:17px}.article-text{font-size:17px;line-height:1.85}.related-grid{grid-template-columns:1fr 1fr}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""

TEMPLATES = {
    'portal_base.html': r"""
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Diário da Notícia | Piauí e região{% endblock %}</title>
<meta name="description" content="{% block description %}Notícias do Piauí, das cidades e do Brasil. Informação e credibilidade no Diário da Notícia.{% endblock %}">
<meta name="theme-color" content="#ba1828">
<link rel="stylesheet" href="{{ url_for('portal_css') }}">
{% block meta %}{% endblock %}
</head>
<body>
<a class="skip" href="#conteudo">Ir para o conteúdo</a>
<div class="topline"><div class="wrap"><time>{{ hoje_portal }}</time><span>Piauí · Brasil · Informação e credibilidade</span><a href="{{ instagram_url }}" target="_blank" rel="noopener noreferrer" aria-label="Instagram do Diário da Notícia">Instagram ↗</a><a href="{{ url_for('admin') }}">Área da redação</a></div></div>
<header class="masthead wrap">
<a class="brand" href="{{ url_for('inicio') }}" aria-label="Diário da Notícia — início"><span class="brand-over">DIÁRIO DA</span><strong>NOTÍCIA<span class="brand-dot">.</span></strong><span class="brand-tag">INFORMAÇÃO EM PRIMEIRO LUGAR</span></a>
<form class="search" action="{{ url_for('inicio') }}" method="get" role="search"><label class="sr-only" for="busca-portal">Buscar notícias</label><input id="busca-portal" type="search" name="q" value="{{ busca|default('') }}" placeholder="O que você quer saber?" maxlength="200"><button type="submit">Buscar <span aria-hidden="true">↗</span></button></form>
<div class="redacao"><span class="live-dot"></span> NOTÍCIAS DO PIAUÍ<strong>Seu portal de informação</strong><a href="#patrocinadores">Conheça nossos parceiros ↗</a></div>
</header>
<nav class="nav" aria-label="Editorias"><div class="wrap nav-inner"><a href="{{ url_for('inicio') }}" {% if not categoria_atual|default('') %}class="active"{% endif %}>Início</a>{% for cat in categorias %}<a href="{{ url_for('inicio',categoria=cat) }}" {% if categoria_atual|default('') == cat %}class="active" aria-current="page"{% endif %}>{{ cat }}</a>{% endfor %}</div></nav>
<main id="conteudo" class="wrap">{% block content %}{% endblock %}</main>
<footer class="footer" id="patrocinadores"><div class="wrap">
<div class="footer-head"><a class="brand brand-footer" href="{{ url_for('inicio') }}"><span class="brand-over">DIÁRIO DA</span><strong>NOTÍCIA<span class="brand-dot">.</span></strong></a><p>O Piauí e a região em pauta.<br>Informação e credibilidade, todos os dias.</p></div>
{% if patrocinadores %}<h2>Nossos patrocinadores</h2><div class="partner-grid">{% for p in patrocinadores %}<div class="partner">{% if p.link %}<a href="{{ p.link }}" target="_blank" rel="noopener noreferrer sponsored">{% endif %}{% if p.imagem %}<img src="{{ p.imagem }}" alt="{{ p.nome }}" loading="lazy">{% endif %}<strong>{{ p.nome }}</strong>{% if p.link %}</a>{% endif %}</div>{% endfor %}</div>{% endif %}
<div class="footer-bottom"><span>© {{ ano_portal }} Diário da Notícia</span><a href="{{ instagram_url }}" target="_blank" rel="noopener noreferrer">Siga @diariodanoticia no Instagram ↗</a><a href="{{ url_for('admin') }}">Painel da redação</a><a href="#conteudo">Voltar ao topo ↑</a></div></div></footer>
<script>
document.querySelectorAll('[data-carousel]').forEach(function(area){
 const slides=Array.from(area.querySelectorAll('[data-slide]'));
 if(slides.length<2)return;
 let index=0;
 function show(n){
   index=(n+slides.length)%slides.length;
   slides.forEach((s,i)=>s.hidden=i!==index);
   const count=area.querySelector('[data-count]');
   if(count)count.textContent=(index+1)+' / '+slides.length;
 }
 area.querySelector('[data-prev]').addEventListener('click',()=>show(index-1));
 area.querySelector('[data-next]').addEventListener('click',()=>show(index+1));
});
</script>
{% block scripts %}{% endblock %}
</body></html>
""",

    'portal_macros.html': r"""
{% macro photo(n, eager=false) -%}
<div class="news-photo">{% if n.imagem %}<img src="{{ n.imagem }}" alt="{{ n.titulo }}" {% if eager %}fetchpriority="high" loading="eager"{% else %}loading="lazy"{% endif %}>{% else %}<div class="photo-placeholder" aria-label="Notícia sem foto"><span>DIÁRIO DA</span><strong>NOTÍCIA.</strong></div>{% endif %}</div>
{%- endmacro %}
{% macro card(n, compact=false) -%}
<article class="news-card {% if compact %}compact{% endif %}"><a href="{{ url_for('noticia',id=n.id) }}">{{ photo(n) }}<div class="card-body"><span class="eyebrow">{{ n.categoria }}</span><h3>{{ n.titulo }}</h3><time>{{ n.data_publicacao|data_br }}</time>{% if not compact and n.resumo %}<p>{{ n.resumo|truncate(160) }}</p>{% endif %}</div></a></article>
{%- endmacro %}
{% macro ad(p, lateral=false) -%}
<div class="ad {% if lateral %}ad-side{% endif %}"><span class="ad-label">Publicidade</span>{% if p.link %}<a href="{{ p.link }}" target="_blank" rel="noopener noreferrer sponsored">{% endif %}{% if p.imagem %}<img src="{{ p.imagem }}" alt="{{ p.nome }}" loading="lazy">{% else %}<div class="ad-name">{{ p.nome }}</div>{% endif %}{% if p.link %}</a>{% endif %}</div>
{%- endmacro %}
{% macro ads_top(items) -%}
{% if items %}<section class="ad-top" data-carousel aria-label="Anúncios dos patrocinadores">{% for p in items %}<div data-slide {% if not loop.first %}hidden{% endif %}>{{ ad(p) }}</div>{% endfor %}{% if items|length>1 %}<div class="ad-controls"><button type="button" data-prev aria-label="Anúncio anterior">←</button><span data-count>1 / {{ items|length }}</span><button type="button" data-next aria-label="Próximo anúncio">→</button></div>{% endif %}</section>{% endif %}
{%- endmacro %}
""",

    'index.html': r"""
{% extends 'portal_base.html' %}
{% from 'portal_macros.html' import photo, card, ad, ads_top %}
{% block title %}{% if busca %}Busca: {{ busca }}{% elif categoria_atual %}{{ categoria_atual }}{% else %}Diário da Notícia{% endif %} | Notícias do Piauí{% endblock %}
{% block content %}
{{ ads_top(patrocinadores) }}
{% set destaque = noticias and not busca and not categoria_atual and paginacao.page == 1 %}
{% if destaque %}
{% set principal = noticias[0] %}
<div class="headline"><span class="eyebrow">{{ principal.categoria }} · Em destaque</span><h1><a href="{{ url_for('noticia',id=principal.id) }}">{{ principal.titulo }}</a></h1>{% if principal.resumo %}<p>{{ principal.resumo }}</p>{% endif %}</div>
<section class="hero-grid" aria-label="Principais notícias">
<article class="hero-photo"><a href="{{ url_for('noticia',id=principal.id) }}">{{ photo(principal,true) }}</a><time>{{ principal.data_publicacao|data_br }}</time></article>
<div class="hero-list">{% for n in noticias[1:5] %}<article><span class="eyebrow">{{ n.categoria }}</span><h2><a href="{{ url_for('noticia',id=n.id) }}">{{ n.titulo }}</a></h2><time>{{ n.data_publicacao|data_br }}</time></article>{% endfor %}</div>
{% if noticias|length>5 %}{% set n=noticias[5] %}<article class="hero-secondary"><a href="{{ url_for('noticia',id=n.id) }}">{{ photo(n) }}<span class="eyebrow">{{ n.categoria }}</span><h2>{{ n.titulo }}</h2></a><time>{{ n.data_publicacao|data_br }}</time></article>{% endif %}
</section>
{% endif %}
<div class="content-columns"><div>
{% if busca or categoria_atual %}<h1 class="filtered-title">{% if busca %}Resultados para “{{ busca }}”{% else %}{{ categoria_atual }}{% endif %}</h1><p class="filter-summary">{{ paginacao.total }} notícia(s){% if categoria_atual and busca %} em {{ categoria_atual }}{% endif %}. <a class="clear-filter" href="{{ url_for('inicio') }}">Ver todas as notícias</a></p>{% else %}<div class="section-heading"><h2>Últimas notícias</h2><span class="eyebrow">Fique por dentro</span></div>{% endif %}
{% set recentes=noticias[6:] if destaque else noticias %}
{% if recentes %}<div class="news-grid">{% for n in recentes %}{{ card(n) }}{% endfor %}</div>{% elif not noticias %}<div class="empty">{% if busca or categoria_atual %}Nenhuma notícia encontrada. Tente outra palavra ou editoria.{% else %}As notícias publicadas pela redação aparecerão aqui.{% endif %}</div>{% elif destaque %}<p class="filter-summary">Confira os destaques acima e as notícias por editoria abaixo.</p>{% endif %}
{% if paginacao.pages>1 %}<nav class="pagination" aria-label="Páginas de notícias">{% if paginacao.has_prev %}<a href="{{ url_for('inicio',page=paginacao.prev_num,categoria=categoria_atual,q=busca) }}">← Anterior</a>{% endif %}{% for page in paginacao.iter_pages() %}{% if page %}{% if page==paginacao.page %}<span class="current" aria-current="page">{{ page }}</span>{% else %}<a href="{{ url_for('inicio',page=page,categoria=categoria_atual,q=busca) }}">{{ page }}</a>{% endif %}{% else %}<span>…</span>{% endif %}{% endfor %}{% if paginacao.has_next %}<a href="{{ url_for('inicio',page=paginacao.next_num,categoria=categoria_atual,q=busca) }}">Próxima →</a>{% endif %}</nav>{% endif %}
{% for secao in secoes %}<section><div class="section-heading"><h2>{{ secao.nome }}</h2><a href="{{ url_for('inicio',categoria=secao.nome) }}">Ver todas ↗</a></div><div class="section-grid">{% set n=secao.noticias[0] %}<article class="lead-story"><a href="{{ url_for('noticia',id=n.id) }}">{{ photo(n) }}<h2>{{ n.titulo }}</h2></a><time>{{ n.data_publicacao|data_br }}</time></article><div class="section-list">{% for n in secao.noticias[1:] %}{{ card(n,true) }}{% endfor %}</div></div></section>{% if patrocinadores and loop.index%2==0 %}<div class="inline-ad">{{ ad(patrocinadores[((loop.index//2)-1) % (patrocinadores|length)]) }}</div>{% endif %}{% endfor %}
</div><aside class="sidebar" aria-label="Mais notícias e patrocinadores">
{% if patrocinadores %}<h2 class="side-title">Patrocinadores</h2>{% for p in patrocinadores %}{{ ad(p,true) }}{% endfor %}{% endif %}
{% if ultimas %}<h2 class="side-title">Mais recentes</h2><div class="latest-list">{% for n in ultimas %}{{ card(n,true) }}{% endfor %}</div>{% endif %}
<div class="newsletter"><h3>Notícias da sua região</h3><p>Acompanhe as informações do Piauí e das cidades.</p><a href="{{ url_for('inicio',categoria='Cidades') }}">Acompanhar cidades ↗</a></div>
</aside></div>
{% endblock %}
""",

    'noticia.html': r"""
{% extends 'portal_base.html' %}
{% from 'portal_macros.html' import card, ad, ads_top %}
{% block title %}{{ noticia.titulo }} | Diário da Notícia{% endblock %}
{% block description %}{{ noticia.resumo or noticia.titulo }}{% endblock %}
{% block meta %}
<link rel="canonical" href="{{ url_for('noticia',id=noticia.id,_external=true) }}">
<meta property="og:title" content="{{ noticia.titulo }}">
<meta property="og:description" content="{{ noticia.resumo or noticia.titulo }}">
<meta property="og:type" content="article">
<meta property="og:url" content="{{ url_for('noticia',id=noticia.id,_external=true) }}">
<meta property="og:site_name" content="Diário da Notícia">
{% if noticia.imagem %}<meta property="og:image" content="{{ noticia.imagem }}">{% endif %}
{% endblock %}
{% block content %}
{{ ads_top(patrocinadores) }}
<div class="breadcrumbs"><a href="{{ url_for('inicio') }}">Início</a> / <a href="{{ url_for('inicio',categoria=noticia.categoria) }}">{{ noticia.categoria }}</a></div>
<header class="article-head"><span class="eyebrow">{{ noticia.categoria }}</span><h1>{{ noticia.titulo }}</h1>{% if noticia.resumo %}<p class="summary">{{ noticia.resumo }}</p>{% endif %}<div class="byline"><strong>Redação · Diário da Notícia</strong><time>{{ noticia.data_publicacao|data_br }}</time></div></header>
<div class="content-columns"><article>
{% if noticia.imagem %}<img class="article-image" src="{{ noticia.imagem }}" alt="{{ noticia.titulo }}" fetchpriority="high">{% endif %}
<div class="article-text">{{ noticia.conteudo or noticia.resumo or '' }}</div>
<section class="share" aria-label="Compartilhar notícia">
<h2>Compartilhe esta notícia</h2>
<div class="share-buttons">
<button type="button" id="compartilhar-noticia">Compartilhar notícia</button>
<a class="whatsapp" href="https://wa.me/?text={{ (noticia.titulo ~ ' ' ~ url_for('noticia',id=noticia.id,_external=true))|urlencode }}" target="_blank" rel="noopener noreferrer">WhatsApp</a>
<a href="https://www.facebook.com/sharer/sharer.php?u={{ url_for('noticia',id=noticia.id,_external=true)|urlencode }}" target="_blank" rel="noopener noreferrer">Facebook</a>
<button type="button" id="compartilhar-instagram">Compartilhar no Instagram</button>
<button type="button" id="copiar-link">Copiar link</button>
<a href="{{ instagram_url }}" target="_blank" rel="noopener noreferrer">Visitar nosso Instagram ↗</a>
</div>
<p class="share-status">No celular, escolha o Instagram no menu, se ele aparecer. Você também pode copiar o link e colar em uma mensagem ou no adesivo de link dos Stories.</p>
<p class="share-status" id="share-status" role="status" aria-live="polite"></p>
<div id="link-manual" hidden><label for="link-noticia">Link da notícia</label><input id="link-noticia" type="text" readonly value="{{ url_for('noticia',id=noticia.id,_external=true) }}" style="display:block;width:100%;padding:12px;margin-top:8px" onclick="this.select()"></div>
<noscript><p>Use WhatsApp, Facebook ou copie o endereço desta página para compartilhar.</p></noscript>
</section>
{% if patrocinadores %}<div class="inline-ad">{{ ad(patrocinadores[0]) }}</div>{% endif %}
{% if relacionadas %}<section><div class="section-heading"><h2>Leia também</h2><a href="{{ url_for('inicio',categoria=noticia.categoria) }}">{{ noticia.categoria }} ↗</a></div><div class="related-grid">{% for n in relacionadas %}{{ card(n) }}{% endfor %}</div></section>{% endif %}
</article><aside class="sidebar" aria-label="Mais notícias e patrocinadores">{% if patrocinadores %}<h2 class="side-title">Patrocinadores</h2>{% for p in patrocinadores %}{{ ad(p,true) }}{% endfor %}{% endif %}{% if ultimas %}<h2 class="side-title">Mais recentes</h2><div class="latest-list">{% for n in ultimas %}{{ card(n,true) }}{% endfor %}</div>{% endif %}</aside></div>
{% endblock %}
{% block scripts %}<script>
(function(){
 const link={{ url_for('noticia',id=noticia.id,_external=true)|tojson }};
 const titulo={{ noticia.titulo|tojson }};
 const status=document.getElementById('share-status');
 const manual=document.getElementById('link-manual');
 const campo=document.getElementById('link-noticia');
 const instrucaoInstagram='Abra o Instagram e cole em uma mensagem ou no adesivo de link dos Stories.';
 async function copiar(instagram){
   try{
     await navigator.clipboard.writeText(link);
     manual.hidden=true;
     status.textContent='Link copiado!'+(instagram?' '+instrucaoInstagram:'');
   }catch(e){
     manual.hidden=false;
     campo.focus();
     campo.select();
     status.textContent='Selecione e copie o link abaixo.'+(instagram?' '+instrucaoInstagram:'');
   }
 }
 async function compartilhar(instagram){
   status.textContent='';
   if(typeof navigator.share==='function'){
     try{
       await navigator.share({title:titulo,text:titulo,url:link});
       status.textContent='Notícia enviada ao aplicativo escolhido.';
       return;
     }catch(e){
       if(e.name==='AbortError')return;
     }
   }
   await copiar(instagram);
 }
 document.getElementById('copiar-link').addEventListener('click',()=>copiar(false));
 document.getElementById('compartilhar-noticia').addEventListener('click',()=>compartilhar(false));
 document.getElementById('compartilhar-instagram').addEventListener('click',()=>compartilhar(true));
})();
</script>{% endblock %}
""",

    'admin_base.html': r"""
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Redação | Diário da Notícia{% endblock %}</title>
<link rel="stylesheet" href="{{ url_for('portal_css') }}">
<style>
.admin-header{background:#17191c;color:white;padding:22px 0}.admin-header .wrap{display:flex;align-items:center;justify-content:space-between;gap:20px}.admin-header strong{font-size:20px}.admin-links{display:flex;gap:18px;font-size:13px}.admin-content{max-width:960px;padding:30px 0}.admin-content h1{font-size:28px}.admin-box{border:1px solid #e4e6e9;padding:24px;margin:20px 0;border-radius:6px}.admin-item{padding:18px 0;border-bottom:1px solid #e4e6e9}.admin-item h3{margin-bottom:8px}.admin-item img{max-width:220px;max-height:100px;object-fit:contain;margin:12px 0}.admin-actions{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}.admin-actions form{margin:0}.admin-button{display:inline-block;background:#17191c;color:white;padding:12px 16px;border:0;border-radius:4px;font-size:13px}.admin-button.red{background:#ba1828}.admin-form label{display:block;font-size:13px;font-weight:bold;margin:18px 0 8px}.admin-form input:not([type=hidden]),.admin-form select,.admin-form textarea{width:100%;padding:12px;border:1px solid #cfd3d9;border-radius:4px;font:15px Arial}.admin-form textarea{line-height:1.6}.admin-error{background:#fff0f0;border:1px solid #dba5a5;padding:14px;color:#8a101a}.admin-help{font-size:13px;color:#687078;line-height:1.6}.admin-login{max-width:440px;margin:30px auto}.admin-item .admin-help{overflow-wrap:anywhere}
@media(max-width:600px){.admin-header .wrap{align-items:start;flex-direction:column}.admin-box{padding:18px}.admin-content h1{font-size:24px}}
</style>
</head>
<body>
<header class="admin-header"><div class="wrap"><strong>Diário da Notícia · Redação</strong><nav class="admin-links"><a href="{{ url_for('inicio') }}">Ver portal</a>{% if session.get('admin') %}<a href="{{ url_for('painel') }}">Painel</a><a href="{{ url_for('sair') }}">Sair</a>{% endif %}</nav></div></header>
<main class="wrap admin-content">
{% if erro %}<p class="admin-error" role="alert">{{ erro }}</p>{% endif %}
{% block content %}{% endblock %}
</main>
</body>
</html>
""",

    'login.html': r"""
{% extends 'admin_base.html' %}
{% block content %}
<section class="admin-box admin-login">
<h1>Entrar na redação</h1>
<form class="admin-form" method="post">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="usuario">Usuário</label>
<input id="usuario" name="usuario" autocomplete="username" required>
<label for="senha">Senha</label>
<input id="senha" type="password" name="senha" autocomplete="current-password" required>
<div class="admin-actions"><button class="admin-button red" type="submit">Entrar</button></div>
</form>
</section>
{% endblock %}
""",

    'nova_noticia.html': r"""
{% extends 'admin_base.html' %}
{% block content %}
{% set editando=noticia is defined %}
<h1>{{ 'Editar notícia' if editando else 'Nova notícia' }}</h1>
<form class="admin-form admin-box" method="post" enctype="multipart/form-data">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="categoria">Editoria</label>
<select name="categoria" id="categoria" required>
{% set escolhida=request.form.get('categoria',noticia.categoria if editando else '') %}
<option value="">Selecione</option>
{% for cat in categorias %}<option value="{{ cat }}" {% if escolhida==cat %}selected{% endif %}>{{ cat }}</option>{% endfor %}
</select>
<label for="titulo">Título</label>
<input id="titulo" name="titulo" maxlength="250" value="{{ request.form.get('titulo',noticia.titulo if editando else '') }}" required>
<label for="resumo">Resumo</label>
<textarea id="resumo" name="resumo" rows="3" required>{{ request.form.get('resumo',(noticia.resumo or '') if editando else '') }}</textarea>
<label for="conteudo">Texto completo</label>
<textarea id="conteudo" name="conteudo" rows="14" required>{{ request.form.get('conteudo',(noticia.conteudo or '') if editando else '') }}</textarea>
{% if editando and noticia.imagem %}<p class="admin-help">Imagem atual</p><img src="{{ noticia.imagem }}" alt="Imagem atual" style="max-height:200px">{% endif %}
<label for="imagem">{{ 'Trocar imagem (opcional)' if editando else 'Imagem (opcional)' }}</label>
<input id="imagem" name="imagem" type="file" accept="image/jpeg,image/png,image/webp">
<p class="admin-help">JPG, PNG ou WEBP, até 10 MB. As fotos são salvas no Cloudinary.</p>
<div class="admin-actions"><button class="admin-button red" type="submit">Salvar notícia</button><a class="admin-button" href="{{ url_for('painel') }}">Voltar ao painel</a></div>
</form>
{% endblock %}
""",

    'editar_noticia.html': r"""
{% extends 'admin_base.html' %}
{% block content %}
{% set editando=noticia is defined %}
<h1>{{ 'Editar notícia' if editando else 'Nova notícia' }}</h1>
<form class="admin-form admin-box" method="post" enctype="multipart/form-data">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="categoria">Editoria</label>
<select name="categoria" id="categoria" required>
{% set escolhida=request.form.get('categoria',noticia.categoria if editando else '') %}
<option value="">Selecione</option>
{% for cat in categorias %}<option value="{{ cat }}" {% if escolhida==cat %}selected{% endif %}>{{ cat }}</option>{% endfor %}
</select>
<label for="titulo">Título</label>
<input id="titulo" name="titulo" maxlength="250" value="{{ request.form.get('titulo',noticia.titulo if editando else '') }}" required>
<label for="resumo">Resumo</label>
<textarea id="resumo" name="resumo" rows="3" required>{{ request.form.get('resumo',(noticia.resumo or '') if editando else '') }}</textarea>
<label for="conteudo">Texto completo</label>
<textarea id="conteudo" name="conteudo" rows="14" required>{{ request.form.get('conteudo',(noticia.conteudo or '') if editando else '') }}</textarea>
{% if editando and noticia.imagem %}<p class="admin-help">Imagem atual</p><img src="{{ noticia.imagem }}" alt="Imagem atual" style="max-height:200px">{% endif %}
<label for="imagem">{{ 'Trocar imagem (opcional)' if editando else 'Imagem (opcional)' }}</label>
<input id="imagem" name="imagem" type="file" accept="image/jpeg,image/png,image/webp">
<p class="admin-help">JPG, PNG ou WEBP, até 10 MB. As fotos são salvas no Cloudinary.</p>
<div class="admin-actions"><button class="admin-button red" type="submit">Salvar notícia</button><a class="admin-button" href="{{ url_for('painel') }}">Voltar ao painel</a></div>
</form>
{% endblock %}
""",

    'novo_patrocinador.html': r"""
{% extends 'admin_base.html' %}
{% block content %}
<h1>Novo patrocinador</h1>
<form class="admin-form admin-box" method="post" enctype="multipart/form-data">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<label for="nome">Nome da empresa</label>
<input id="nome" name="nome" maxlength="200" value="{{ request.form.get('nome','') }}" required>
<label for="imagem">Banner do patrocinador</label>
<input id="imagem" type="file" name="imagem" accept="image/jpeg,image/png,image/webp" required>
<p class="admin-help">Envie JPG, PNG ou WEBP com até 10 MB. O anúncio aparece no topo, na lateral e nos espaços de publicidade do portal.</p>
<label for="link">Link do anunciante (opcional)</label>
<input id="link" name="link" type="url" placeholder="https://..." value="{{ request.form.get('link','') }}">
<div class="admin-actions"><button class="admin-button red" type="submit">Cadastrar patrocinador</button><a class="admin-button" href="{{ url_for('painel') }}">Voltar ao painel</a></div>
</form>
{% endblock %}
""",

    'painel.html': r"""
{% extends 'admin_base.html' %}
{% block content %}
<h1>Painel da redação</h1>
<p class="admin-help">Gerencie notícias e patrocinadores do portal.</p>
<div class="admin-actions"><a class="admin-button red" href="{{ url_for('nova_noticia') }}">+ Nova notícia</a><a class="admin-button" href="{{ url_for('novo_patrocinador') }}">+ Novo patrocinador</a></div>
<section class="admin-box">
<h2>Notícias · {{ noticias|length }}</h2>
{% for n in noticias %}
<article class="admin-item">
<span class="eyebrow">{{ n.categoria }}</span>
<h3><a href="{{ url_for('noticia',id=n.id) }}">{{ n.titulo }}</a></h3>
<time>{{ n.data_publicacao|data_br }}</time>
<div class="admin-actions">
<a class="admin-button" href="{{ url_for('editar_noticia',id=n.id) }}">Editar</a>
<form method="post" action="{{ url_for('excluir_noticia',id=n.id) }}" onsubmit="return confirm('Excluir esta notícia?');">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button class="admin-button red" type="submit">Excluir</button>
</form>
</div>
</article>
{% else %}
<p>Nenhuma notícia cadastrada.</p>
{% endfor %}
</section>
<section class="admin-box">
<h2>Patrocinadores · {{ patrocinadores|length }}</h2>
<p class="admin-help">Pause um anúncio para ocultá-lo sem apagar o cadastro.</p>
{% for p in patrocinadores %}
<article class="admin-item">
<h3>{{ p.nome }}</h3>
<p class="admin-help">{{ 'Ativo — aparece no portal' if p.ativo else 'Pausado — não aparece no portal' }}</p>
{% if p.imagem %}<img src="{{ p.imagem }}" alt="{{ p.nome }}">{% endif %}
{% if p.link %}<p class="admin-help">{{ p.link }}</p>{% endif %}
<div class="admin-actions">
<form method="post" action="{{ url_for('alternar_patrocinador',id=p.id) }}">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button class="admin-button" type="submit">{{ 'Pausar anúncio' if p.ativo else 'Ativar anúncio' }}</button>
</form>
<form method="post" action="{{ url_for('excluir_patrocinador',id=p.id) }}" onsubmit="return confirm('Excluir este patrocinador? Para ocultar, use Pausar anúncio.');">
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
<button class="admin-button red" type="submit">Excluir</button>
</form>
</div>
</article>
{% else %}
<p>Nenhum patrocinador cadastrado.</p>
{% endfor %}
</section>
{% endblock %}
"""
}

app.jinja_loader = DictLoader(TEMPLATES)


@app.route('/portal.css')
def portal_css():
    return Response(PORTAL_CSS, mimetype='text/css')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
