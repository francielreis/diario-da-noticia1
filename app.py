from flask import Flask, render_template, request, redirect, url_for, session, abort
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


# ============================================================
# APLICATIVO
# ============================================================

app = Flask(__name__)

secret_key = os.environ.get("SECRET_KEY")

if not secret_key:
    if os.environ.get("RENDER"):
        raise RuntimeError(
            "Configure a variável SECRET_KEY no Render."
        )

    secret_key = "somente-desenvolvimento-local"


app.secret_key = secret_key


app.config.update(

    SQLALCHEMY_TRACK_MODIFICATIONS=False,

    MAX_CONTENT_LENGTH=10 * 1024 * 1024,

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=bool(
        os.environ.get("RENDER")
    ),

    PERMANENT_SESSION_LIFETIME=timedelta(
        hours=8
    )

)


# ============================================================
# CLOUDINARY
# ============================================================

cloudinary.config(

    cloud_name=os.environ.get(
        "CLOUDINARY_CLOUD_NAME"
    ),

    api_key=os.environ.get(
        "CLOUDINARY_API_KEY"
    ),

    api_secret=os.environ.get(
        "CLOUDINARY_API_SECRET"
    ),

    secure=True

)


# ============================================================
# BANCO DE DADOS
# ============================================================

database_url = os.environ.get(
    "DATABASE_URL"
)


if (
    database_url
    and database_url.startswith(
        "postgres://"
    )
):

    database_url = database_url.replace(

        "postgres://",

        "postgresql://",

        1

    )


app.config[
    "SQLALCHEMY_DATABASE_URI"
] = (
    database_url
    or "sqlite:///diario.db"
)


db = SQLAlchemy(app)


# ============================================================
# CATEGORIAS
# ============================================================

CATEGORIAS = [

    "Piauí",

    "Política",

    "Brasil",

    "Economia",

    "Cidades",

    "Esportes",

    "Educação",

    "Saúde",

    "Polícia",

    "Tecnologia"

]


# ============================================================
# IMAGENS
# ============================================================

EXTENSOES_PERMITIDAS = {

    "png",

    "jpg",

    "jpeg",

    "webp"

}


def arquivo_permitido(
    nome_arquivo
):

    if not nome_arquivo:
        return False

    if "." not in nome_arquivo:
        return False

    extensao = (
        nome_arquivo
        .rsplit(".", 1)[1]
        .lower()
    )

    return (
        extensao
        in EXTENSOES_PERMITIDAS
    )


# ============================================================
# SALVAR IMAGEM
# ============================================================

def salvar_imagem(
    arquivo
):

    if not arquivo:
        return ""

    if not arquivo.filename:
        return ""

    if not arquivo_permitido(
        arquivo.filename
    ):

        raise ValueError(

            "Formato não permitido. "
            "Use JPG, JPEG, PNG ou WEBP."

        )


    configuracoes = {

        "CLOUDINARY_CLOUD_NAME":
            os.environ.get(
                "CLOUDINARY_CLOUD_NAME"
            ),

        "CLOUDINARY_API_KEY":
            os.environ.get(
                "CLOUDINARY_API_KEY"
            ),

        "CLOUDINARY_API_SECRET":
            os.environ.get(
                "CLOUDINARY_API_SECRET"
            )

    }


    faltando = [

        nome

        for nome, valor
        in configuracoes.items()

        if not valor

    ]


    if faltando:

        raise RuntimeError(

            "Cloudinary não configurado. "
            "Faltam: "
            + ", ".join(faltando)

        )


    resultado = (
        cloudinary.uploader.upload(

            arquivo,

            folder="diario-da-noticia",

            resource_type="image"

        )
    )


    url = resultado.get(
        "secure_url"
    )


    if not url:

        raise RuntimeError(

            "O Cloudinary não retornou "
            "o endereço da imagem."

        )


    return url


# ============================================================
# PEGAR PUBLIC ID CLOUDINARY
# ============================================================

def obter_public_id(
    caminho_imagem
):

    if not caminho_imagem:
        return None

    if (
        "res.cloudinary.com"
        not in caminho_imagem
    ):
        return None


    try:

        partes = caminho_imagem.split(
            "/upload/",
            1
        )


        if len(partes) != 2:
            return None


        partes_caminho = (
            partes[1]
            .split("/")
        )


        indice_versao = None


        for i, parte in enumerate(
            partes_caminho
        ):

            if (
                parte.startswith("v")
                and
                parte[1:].isdigit()
            ):

                indice_versao = i

                break


        if indice_versao is not None:

            partes_caminho = (
                partes_caminho[
                    indice_versao + 1:
                ]
            )


        caminho = "/".join(
            partes_caminho
        )


        public_id = os.path.splitext(
            caminho
        )[0]


        return (
            public_id
            or None
        )


    except Exception:

        return None


# ============================================================
# APAGAR IMAGEM CLOUDINARY
# ============================================================

def apagar_imagem(
    caminho_imagem
):

    public_id = obter_public_id(
        caminho_imagem
    )


    if not public_id:
        return


    try:

        cloudinary.uploader.destroy(

            public_id,

            resource_type="image"

        )


    except Exception as erro:

        app.logger.warning(

            "Não foi possível apagar "
            "imagem do Cloudinary: %r",

            erro

        )


# ============================================================
# VALIDAR LINK
# ============================================================

def link_http_valido(
    link
):

    if not link:
        return True


    try:

        parsed = urlparse(
            link
        )


        return (

            parsed.scheme
            in {
                "http",
                "https"
            }

            and

            bool(
                parsed.netloc
            )

        )


    except Exception:

        return False


# ============================================================
# SEGURANÇA CSRF
# ============================================================

def csrf_token():

    token = session.get(
        "_csrf_token"
    )


    if not token:

        token = (
            secrets
            .token_urlsafe(32)
        )

        session[
            "_csrf_token"
        ] = token


    return token


app.jinja_env.globals[
    "csrf_token"
] = csrf_token


def csrf_valido():

    esperado = session.get(
        "_csrf_token",
        ""
    )


    recebido = (
        request.form.get(
            "_csrf_token",
            ""
        )
    )


    return bool(

        esperado

        and recebido

        and hmac.compare_digest(
            esperado,
            recebido
        )

    )


def exigir_csrf():

    if (
        request.method == "POST"
        and not csrf_valido()
    ):

        abort(

            400,

            description=(
                "Formulário expirado ou inválido. "
                "Atualize a página e tente novamente."
            )

        )


# ============================================================
# PROTEGER PAINEL ADMIN
# ============================================================

def admin_required(
    func
):

    @wraps(func)

    def wrapper(
        *args,
        **kwargs
    ):

        if not session.get(
            "admin"
        ):

            return redirect(
                url_for(
                    "admin"
                )
            )


        return func(
            *args,
            **kwargs
        )


    return wrapper


# ============================================================
# MODELO NOTÍCIA
# ============================================================

class Noticia(
    db.Model
):

    __tablename__ = "noticias"


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    categoria = db.Column(

        db.String(100),

        nullable=False

    )


    titulo = db.Column(

        db.String(250),

        nullable=False

    )


    resumo = db.Column(

        db.Text,

        nullable=True

    )


    conteudo = db.Column(

        db.Text,

        nullable=True

    )


    imagem = db.Column(

        db.Text,

        nullable=True

    )


    data_publicacao = db.Column(

        db.DateTime,

        default=datetime.utcnow,

        index=True

    )


# ============================================================
# MODELO PATROCINADOR
# ============================================================

class Patrocinador(
    db.Model
):

    __tablename__ = (
        "patrocinadores"
    )


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    nome = db.Column(

        db.String(200),

        nullable=False

    )


    imagem = db.Column(

        db.Text,

        nullable=True

    )


    link = db.Column(

        db.Text,

        nullable=True

    )


    ativo = db.Column(

        db.Boolean,

        default=True

    )


# ============================================================
# CRIAR TABELAS
# ============================================================

with app.app_context():

    db.create_all()


# ============================================================
# HORÁRIO DO PIAUÍ
# ============================================================

@app.template_filter(
    "data_br"
)

def data_br(
    valor
):

    if not valor:

        return ""


    if valor.tzinfo is None:

        valor = valor.replace(
            tzinfo=timezone.utc
        )


    local = valor.astimezone(

        ZoneInfo(
            "America/Fortaleza"
        )

    )


    return local.strftime(

        "%d/%m/%Y às %H:%M"

    )


# ============================================================
# PÁGINA INICIAL
# ============================================================

@app.route("/")
def inicio():

    page = max(

        request.args.get(
            "page",
            1,
            type=int
        ) or 1,

        1

    )


    categoria = (
        request.args.get(
            "categoria",
            ""
        )
        .strip()
    )


    busca = (
        request.args.get(
            "q",
            ""
        )
        .strip()
    )


    stmt = db.select(
        Noticia
    )


    if categoria in CATEGORIAS:

        stmt = stmt.where(

            Noticia.categoria
            == categoria

        )


    else:

        categoria = ""


    if busca:

        termo = (
            f"%{busca}%"
        )


        stmt = stmt.where(

            or_(

                Noticia.titulo.ilike(
                    termo
                ),

                Noticia.resumo.ilike(
                    termo
                ),

                Noticia.conteudo.ilike(
                    termo
                )

            )

        )


    stmt = stmt.order_by(

        Noticia
        .data_publicacao
        .desc()

    )


    paginacao = db.paginate(

        stmt,

        page=page,

        per_page=10,

        error_out=False

    )


    patrocinadores = (
        db.session.scalars(

            db.select(
                Patrocinador
            )

            .where(

                Patrocinador
                .ativo
                .is_(True)

            )

            .order_by(

                Patrocinador
                .id
                .desc()

            )

        )
        .all()
    )


    return render_template(

        "index.html",

        noticias=(
            paginacao.items
        ),

        paginacao=paginacao,

        patrocinadores=(
            patrocinadores
        ),

        categorias=CATEGORIAS,

        categoria_atual=(
            categoria
        ),

        busca=busca

    )


# ============================================================
# ABRIR NOTÍCIA
# ============================================================

@app.route(
    "/noticia/<int:id>"
)

def noticia(
    id
):

    noticia = (
        db.get_or_404(
            Noticia,
            id
        )
    )


    return render_template(

        "noticia.html",

        noticia=noticia

    )


# ============================================================
# LOGIN ADMIN
# ============================================================

@app.route(

    "/admin",

    methods=[
        "GET",
        "POST"
    ]

)

def admin():

    erro = None


    if request.method == "POST":

        exigir_csrf()


        usuario = (
            request.form.get(
                "usuario",
                ""
            )
            .strip()
        )


        senha = request.form.get(
            "senha",
            ""
        )


        admin_usuario = (
            os.environ.get(
                "ADMIN_USER",
                ""
            )
            .strip()
        )


        admin_senha = (
            os.environ.get(
                "ADMIN_PASSWORD",
                ""
            )
        )


        if (
            not admin_usuario
            or
            not admin_senha
        ):

            erro = (

                "Painel ainda não configurado. "
                "Defina ADMIN_USER e "
                "ADMIN_PASSWORD no Render."

            )


        elif (

            hmac.compare_digest(
                usuario,
                admin_usuario
            )

            and

            hmac.compare_digest(
                senha,
                admin_senha
            )

        ):

            session.clear()

            session[
                "admin"
            ] = True

            session.permanent = True

            csrf_token()


            return redirect(

                url_for(
                    "painel"
                )

            )


        else:

            erro = (
                "Usuário ou senha incorretos."
            )


    return render_template(

        "login.html",

        erro=erro

    )


# ============================================================
# PAINEL
# ============================================================

@app.route(
    "/admin/painel"
)

@admin_required

def painel():

    noticias = (
        db.session.scalars(

            db.select(
                Noticia
            )

            .order_by(

                Noticia
                .data_publicacao
                .desc()

            )

        )
        .all()
    )


    patrocinadores = (
        db.session.scalars(

            db.select(
                Patrocinador
            )

            .order_by(

                Patrocinador
                .id
                .desc()

            )

        )
        .all()
    )


    return render_template(

        "painel.html",

        noticias=noticias,

        patrocinadores=(
            patrocinadores
        )

    )


# ============================================================
# NOVA NOTÍCIA
# ============================================================

@app.route(

    "/admin/nova-noticia",

    methods=[
        "GET",
        "POST"
    ]

)

@admin_required

def nova_noticia():

    erro = None


    if request.method == "POST":

        exigir_csrf()


        categoria = (
            request.form.get(
                "categoria",
                ""
            )
            .strip()
        )


        titulo = (
            request.form.get(
                "titulo",
                ""
            )
            .strip()
        )


        resumo = (
            request.form.get(
                "resumo",
                ""
            )
            .strip()
        )


        conteudo = (
            request.form.get(
                "conteudo",
                ""
            )
            .strip()
        )


        if categoria not in CATEGORIAS:

            erro = (
                "Selecione uma categoria válida."
            )


        elif not titulo:

            erro = (
                "Informe o título."
            )


        elif not resumo:

            erro = (
                "Informe o resumo."
            )


        elif not conteudo:

            erro = (
                "Informe o conteúdo da notícia."
            )


        if erro:

            return render_template(

                "nova_noticia.html",

                erro=erro,

                categorias=CATEGORIAS

            )


        arquivo = request.files.get(
            "imagem"
        )


        try:

            imagem = salvar_imagem(
                arquivo
            )


        except Exception as erro_upload:

            return render_template(

                "nova_noticia.html",

                erro=(
                    "Erro ao enviar a imagem: "
                    + str(
                        erro_upload
                    )
                ),

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

            db.session.add(
                nova
            )

            db.session.commit()


        except Exception:

            db.session.rollback()

            app.logger.exception(

                "Erro ao salvar notícia."

            )


            return render_template(

                "nova_noticia.html",

                erro=(
                    "Não foi possível salvar "
                    "a notícia. Tente novamente."
                ),

                categorias=CATEGORIAS

            )


        return redirect(

            url_for(

                "noticia",

                id=nova.id

            )

        )


    return render_template(

        "nova_noticia.html",

        erro=erro,

        categorias=CATEGORIAS

    )


# ============================================================
# EDITAR NOTÍCIA
# ============================================================

@app.route(

    "/admin/editar-noticia/<int:id>",

    methods=[
        "GET",
        "POST"
    ]

)

@admin_required

def editar_noticia(
    id
):

    noticia = (
        db.get_or_404(
            Noticia,
            id
        )
    )


    erro = None


    if request.method == "POST":

        exigir_csrf()


        categoria = (
            request.form.get(
                "categoria",
                ""
            )
            .strip()
        )


        titulo = (
            request.form.get(
                "titulo",
                ""
            )
            .strip()
        )


        resumo = (
            request.form.get(
                "resumo",
                ""
            )
            .strip()
        )


        conteudo = (
            request.form.get(
                "conteudo",
                ""
            )
            .strip()
        )


        if categoria not in CATEGORIAS:

            erro = (
                "Selecione uma categoria válida."
            )


        elif not titulo:

            erro = (
                "Informe o título."
            )


        elif not resumo:

            erro = (
                "Informe o resumo."
            )


        elif not conteudo:

            erro = (
                "Informe o conteúdo da notícia."
            )


        if erro:

            return render_template(

                "editar_noticia.html",

                noticia=noticia,

                erro=erro,

                categorias=CATEGORIAS

            )


        imagem_antiga = (
            noticia.imagem
        )


        arquivo = request.files.get(
            "imagem"
        )


        nova_imagem = None


        if (
            arquivo
            and arquivo.filename
        ):

            try:

                nova_imagem = (
                    salvar_imagem(
                        arquivo
                    )
                )


            except Exception as erro_upload:

                return render_template(

                    "editar_noticia.html",

                    noticia=noticia,

                    erro=(
                        "Erro ao enviar a imagem: "
                        + str(
                            erro_upload
                        )
                    ),

                    categorias=CATEGORIAS

                )


        noticia.categoria = categoria

        noticia.titulo = titulo

        noticia.resumo = resumo

        noticia.conteudo = conteudo


        if nova_imagem:

            noticia.imagem = (
                nova_imagem
            )


        try:

            db.session.commit()


        except Exception:

            db.session.rollback()

            app.logger.exception(

                "Erro ao editar notícia."

            )


            return render_template(

                "editar_noticia.html",

                noticia=noticia,

                erro=(
                    "Não foi possível salvar "
                    "as alterações."
                ),

                categorias=CATEGORIAS

            )


        if (
            nova_imagem
            and imagem_antiga
            and imagem_antiga
            != nova_imagem
        ):

            apagar_imagem(
                imagem_antiga
            )


        return redirect(

            url_for(

                "noticia",

                id=noticia.id

            )

        )


    return render_template(

        "editar_noticia.html",

        noticia=noticia,

        erro=erro,

        categorias=CATEGORIAS

    )


# ============================================================
# EXCLUIR NOTÍCIA
# ============================================================

@app.route(

    "/admin/excluir-noticia/<int:id>",

    methods=[
        "POST"
    ]

)

@admin_required

def excluir_noticia(
    id
):

    exigir_csrf()


    noticia = (
        db.get_or_404(
            Noticia,
            id
        )
    )


    imagem = noticia.imagem


    try:

        db.session.delete(
            noticia
        )

        db.session.commit()


    except Exception:

        db.session.rollback()

        app.logger.exception(

            "Erro ao excluir notícia."

        )

        abort(500)


    apagar_imagem(
        imagem
    )


    return redirect(

        url_for(
            "painel"
        )

    )


# ============================================================
# NOVO PATROCINADOR
# ============================================================

@app.route(

    "/admin/novo-patrocinador",

    methods=[
        "GET",
        "POST"
    ]

)

@admin_required

def novo_patrocinador():

    erro = None


    if request.method == "POST":

        exigir_csrf()


        nome = (
            request.form.get(
                "nome",
                ""
            )
            .strip()
        )


        link = (
            request.form.get(
                "link",
                ""
            )
            .strip()
        )


        arquivo = request.files.get(
            "imagem"
        )


        if not nome:

            erro = (
                "Informe o nome do patrocinador."
            )


        elif not link_http_valido(
            link
        ):

            erro = (
                "O link deve começar "
                "com http:// ou https://."
            )


        elif (
            not arquivo
            or
            not arquivo.filename
        ):

            erro = (
                "Selecione uma imagem "
                "para o patrocinador."
            )


        if erro:

            return render_template(

                "novo_patrocinador.html",

                erro=erro

            )


        try:

            imagem = salvar_imagem(
                arquivo
            )


        except Exception as erro_upload:

            return render_template(

                "novo_patrocinador.html",

                erro=(
                    "Erro ao enviar a imagem: "
                    + str(
                        erro_upload
                    )
                )

            )


        patrocinador = Patrocinador(

            nome=nome,

            imagem=imagem,

            link=link,

            ativo=True

        )


        try:

            db.session.add(
                patrocinador
            )

            db.session.commit()


        except Exception:

            db.session.rollback()

            app.logger.exception(

                "Erro ao salvar patrocinador."

            )


            return render_template(

                "novo_patrocinador.html",

                erro=(
                    "Não foi possível cadastrar "
                    "o patrocinador."
                )

            )


        return redirect(

            url_for(
                "painel"
            )

        )


    return render_template(

        "novo_patrocinador.html",

        erro=erro

    )


# ============================================================
# ATIVAR / DESATIVAR PATROCINADOR
# ============================================================

@app.route(

    "/admin/patrocinador/<int:id>/alternar",

    methods=[
        "POST"
    ]

)

@admin_required

def alternar_patrocinador(
    id
):

    exigir_csrf()


    patrocinador = (
        db.get_or_404(
            Patrocinador,
            id
        )
    )


    patrocinador.ativo = (
        not patrocinador.ativo
    )


    try:

        db.session.commit()


    except Exception:

        db.session.rollback()

        abort(500)


    return redirect(

        url_for(
            "painel"
        )

    )


# ============================================================
# EXCLUIR PATROCINADOR
# ============================================================

@app.route(

    "/admin/excluir-patrocinador/<int:id>",

    methods=[
        "POST"
    ]

)

@admin_required

def excluir_patrocinador(
    id
):

    exigir_csrf()


    patrocinador = (
        db.get_or_404(
            Patrocinador,
            id
        )
    )


    imagem = patrocinador.imagem


    try:

        db.session.delete(
            patrocinador
        )

        db.session.commit()


    except Exception:

        db.session.rollback()

        app.logger.exception(

            "Erro ao excluir patrocinador."

        )

        abort(500)


    apagar_imagem(
        imagem
    )


    return redirect(

        url_for(
            "painel"
        )

    )


# ============================================================
# SAIR
# ============================================================

@app.route(
    "/admin/sair"
)

def sair():

    session.clear()


    return redirect(

        url_for(
            "admin"
        )

    )


# ============================================================
# ERRO 400
# ============================================================

@app.errorhandler(400)

def erro_400(
    error
):

    return (

        (
            "<h1>Solicitação inválida</h1>"
            "<p>"
            + getattr(
                error,
                "description",
                ""
            )
            + "</p>"
            "<p>"
            "<a href='javascript:history.back()'>"
            "Voltar"
            "</a>"
            "</p>"
        ),

        400

    )


# ============================================================
# ERRO 404
# ============================================================

@app.errorhandler(404)

def erro_404(
    error
):

    return (

        (
            "<h1>Página não encontrada</h1>"
            "<p>"
            "<a href='/'>"
            "Voltar para o Diário da Notícia"
            "</a>"
            "</p>"
        ),

        404

    )


# ============================================================
# ERRO IMAGEM MAIOR QUE 10 MB
# ============================================================

@app.errorhandler(413)

def arquivo_grande(
    error
):

    return (

        (
            "<h1>Imagem muito grande</h1>"
            "<p>"
            "Envie uma imagem com até 10 MB."
            "</p>"
            "<p>"
            "<a href='javascript:history.back()'>"
            "Voltar"
            "</a>"
            "</p>"
        ),

        413

    )


# ============================================================
# ERRO 500
# ============================================================

@app.errorhandler(500)

def erro_500(
    error
):

    db.session.rollback()


    return (

        (
            "<h1>Erro interno</h1>"
            "<p>"
            "Não foi possível concluir "
            "a operação. Tente novamente."
            "</p>"
            "<p>"
            "<a href='/'>"
            "Voltar para o portal"
            "</a>"
            "</p>"
        ),

        500

    )


# ============================================================
# INICIAR APLICAÇÃO
# ============================================================

if __name__ == "__main__":

    port = int(

        os.environ.get(
            "PORT",
            5000
        )

    )


    app.run(

        host="0.0.0.0",

        port=port

    )
