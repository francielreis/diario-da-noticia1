from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

import cloudinary
import cloudinary.uploader


# ============================================================
# APLICATIVO
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "troque-esta-chave-depois"
)


# ============================================================
# CLOUDINARY
# ============================================================

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)


# ============================================================
# BANCO DE DADOS
# ============================================================

database_url = os.environ.get("DATABASE_URL")

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    database_url or "sqlite:///diario.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# CONFIGURAÇÃO DAS IMAGENS
# ============================================================

# Máximo de 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

EXTENSOES_PERMITIDAS = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "heic",
    "heif"
}


def arquivo_permitido(nome_arquivo):

    if not nome_arquivo:
        return False

    if "." not in nome_arquivo:
        return False

    extensao = (
        nome_arquivo
        .rsplit(".", 1)[1]
        .lower()
    )

    return extensao in EXTENSOES_PERMITIDAS


# ============================================================
# SALVAR IMAGEM NO CLOUDINARY
# ============================================================

def salvar_imagem(arquivo):

    if not arquivo:
        return ""

    if not arquivo.filename:
        return ""

    # Verifica extensão da imagem
    if not arquivo_permitido(
        arquivo.filename
    ):
        raise ValueError(
            "Formato de imagem não permitido. "
            "Use JPG, JPEG, PNG, WEBP, HEIC ou HEIF."
        )

    # Verifica as configurações do Cloudinary
    cloud_name = os.environ.get(
        "CLOUDINARY_CLOUD_NAME"
    )

    api_key = os.environ.get(
        "CLOUDINARY_API_KEY"
    )

    api_secret = os.environ.get(
        "CLOUDINARY_API_SECRET"
    )

    if not cloud_name:
        raise RuntimeError(
            "CLOUDINARY_CLOUD_NAME não configurado no Render."
        )

    if not api_key:
        raise RuntimeError(
            "CLOUDINARY_API_KEY não configurado no Render."
        )

    if not api_secret:
        raise RuntimeError(
            "CLOUDINARY_API_SECRET não configurado no Render."
        )

    try:

        resultado = cloudinary.uploader.upload(
            arquivo,
            folder="diario-da-noticia",
            resource_type="image"
        )

        url = resultado.get(
            "secure_url"
        )

        if not url:

            raise RuntimeError(
                "O Cloudinary não retornou o endereço da imagem."
            )

        return url

    except Exception as erro:

        print(
            "ERRO REAL DO CLOUDINARY:",
            repr(erro)
        )

        raise erro


# ============================================================
# PEGAR PUBLIC ID DO CLOUDINARY
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
            "/upload/"
        )

        if len(partes) != 2:
            return None

        caminho = partes[1]

        partes_caminho = (
            caminho.split("/")
        )

        # Exemplo:
        # v1720000000
        if (
            partes_caminho
            and partes_caminho[0]
            .startswith("v")
            and partes_caminho[0][1:]
            .isdigit()
        ):
            partes_caminho = (
                partes_caminho[1:]
            )

        caminho = "/".join(
            partes_caminho
        )

        public_id = os.path.splitext(
            caminho
        )[0]

        return public_id

    except Exception as erro:

        print(
            "Erro ao identificar imagem:",
            erro
        )

        return None


# ============================================================
# APAGAR IMAGEM DO CLOUDINARY
# ============================================================

def apagar_imagem(
    caminho_imagem
):

    if not caminho_imagem:
        return

    # Imagens antigas armazenadas localmente
    if caminho_imagem.startswith(
        "/static/uploads/"
    ):
        return

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

        print(
            "Erro ao apagar imagem:",
            erro
        )


# ============================================================
# MODELO DAS NOTÍCIAS
# ============================================================

class Noticia(db.Model):

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
        default=datetime.utcnow
    )


# ============================================================
# MODELO DOS PATROCINADORES
# ============================================================

class Patrocinador(db.Model):

    __tablename__ = "patrocinadores"

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
# PÁGINA INICIAL
# ============================================================

@app.route("/")
def inicio():

    noticias = (
        Noticia.query
        .order_by(
            Noticia
            .data_publicacao
            .desc()
        )
        .all()
    )

    patrocinadores = (
        Patrocinador.query
        .filter_by(
            ativo=True
        )
        .order_by(
            Patrocinador
            .id
            .desc()
        )
        .all()
    )

    return render_template(
        "index.html",
        noticias=noticias,
        patrocinadores=patrocinadores
    )


# ============================================================
# PÁGINA INDIVIDUAL DA NOTÍCIA
# ============================================================

@app.route(
    "/noticia/<int:id>"
)
def noticia(id):

    noticia = (
        Noticia.query
        .get_or_404(id)
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
    methods=["GET", "POST"]
)
def admin():

    erro = None

    if request.method == "POST":

        usuario = (
            request.form
            .get(
                "usuario",
                ""
            )
            .strip()
        )

        senha = (
            request.form
            .get(
                "senha",
                ""
            )
            .strip()
        )

        admin_usuario = (
            os.environ.get(
                "ADMIN_USER",
                "admin"
            )
        )

        admin_senha = (
            os.environ.get(
                "ADMIN_PASSWORD",
                "admin123"
            )
        )

        if (
            usuario == admin_usuario
            and senha == admin_senha
        ):

            session[
                "admin"
            ] = True

            return redirect(
                url_for(
                    "painel"
                )
            )

        erro = (
            "Usuário ou senha incorretos."
        )

    return render_template(
        "login.html",
        erro=erro
    )


# ============================================================
# PAINEL ADMINISTRATIVO
# ============================================================

@app.route(
    "/admin/painel"
)
def painel():

    if not session.get(
        "admin"
    ):

        return redirect(
            url_for(
                "admin"
            )
        )

    noticias = (
        Noticia.query
        .order_by(
            Noticia
            .data_publicacao
            .desc()
        )
        .all()
    )

    patrocinadores = (
        Patrocinador.query
        .order_by(
            Patrocinador
            .id
            .desc()
        )
        .all()
    )

    return render_template(
        "painel.html",
        noticias=noticias,
        patrocinadores=patrocinadores
    )


# ============================================================
# NOVA NOTÍCIA
# ============================================================

@app.route(
    "/admin/nova-noticia",
    methods=["GET", "POST"]
)
def nova_noticia():

    if not session.get(
        "admin"
    ):

        return redirect(
            url_for(
                "admin"
            )
        )

    erro = None

    if request.method == "POST":

        categoria = (
            request.form
            .get(
                "categoria",
                ""
            )
            .strip()
        )

        titulo = (
            request.form
            .get(
                "titulo",
                ""
            )
            .strip()
        )

        resumo = (
            request.form
            .get(
                "resumo",
                ""
            )
            .strip()
        )

        conteudo = (
            request.form
            .get(
                "conteudo",
                ""
            )
            .strip()
        )

        if not categoria or not titulo:

            erro = (
                "Informe a categoria "
                "e o título."
            )

            return render_template(
                "nova_noticia.html",
                erro=erro
            )

        arquivo = request.files.get(
            "imagem"
        )

        try:

            imagem = salvar_imagem(
                arquivo
            )

        except Exception as erro_upload:

            erro = (
                "Erro ao enviar a imagem: "
                + str(
                    erro_upload
                )
            )

            return render_template(
                "nova_noticia.html",
                erro=erro
            )

        nova = Noticia(
            categoria=categoria,
            titulo=titulo,
            resumo=resumo,
            conteudo=conteudo,
            imagem=imagem
        )

        db.session.add(
            nova
        )

        db.session.commit()

        return redirect(
            url_for(
                "noticia",
                id=nova.id
            )
        )

    return render_template(
        "nova_noticia.html",
        erro=erro
    )


# ============================================================
# EDITAR NOTÍCIA
# ============================================================

@app.route(
    "/admin/editar-noticia/<int:id>",
    methods=["GET", "POST"]
)
def editar_noticia(id):

    if not session.get(
        "admin"
    ):

        return redirect(
            url_for(
                "admin"
            )
        )

    noticia = (
        Noticia.query
        .get_or_404(id)
    )

    erro = None

    if request.method == "POST":

        categoria = (
            request.form
            .get(
                "categoria",
                ""
            )
            .strip()
        )

        titulo = (
            request.form
            .get(
                "titulo",
                ""
            )
            .strip()
        )

        resumo = (
            request.form
            .get(
                "resumo",
                ""
            )
            .strip()
        )

        conteudo = (
            request.form
            .get(
                "conteudo",
                ""
            )
            .strip()
        )

        if not categoria or not titulo:

            erro = (
                "Informe a categoria "
                "e o título."
            )

            return render_template(
                "editar_noticia.html",
                noticia=noticia,
                erro=erro
            )

        noticia.categoria = categoria
        noticia.titulo = titulo
        noticia.resumo = resumo
        noticia.conteudo = conteudo

        arquivo = request.files.get(
            "imagem"
        )

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

                erro = (
                    "Erro ao enviar a imagem: "
                    + str(
                        erro_upload
                    )
                )

                return render_template(
                    "editar_noticia.html",
                    noticia=noticia,
                    erro=erro
                )

            imagem_antiga = (
                noticia.imagem
            )

            noticia.imagem = (
                nova_imagem
            )

            db.session.commit()

            apagar_imagem(
                imagem_antiga
            )

        else:

            db.session.commit()

        return redirect(
            url_for(
                "noticia",
                id=noticia.id
            )
        )

    return render_template(
        "editar_noticia.html",
        noticia=noticia,
        erro=erro
    )


# ============================================================
# EXCLUIR NOTÍCIA
# ============================================================

@app.route(
    "/admin/excluir-noticia/<int:id>",
    methods=["POST"]
)
def excluir_noticia(id):

    if not session.get(
        "admin"
    ):

        return redirect(
            url_for(
                "admin"
            )
        )

    noticia = (
        Noticia.query
        .get_or_404(id)
    )

    imagem = (
        noticia.imagem
    )

    db.session.delete(
        noticia
    )

    db.session.commit()

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
    methods=["GET", "POST"]
)
def novo_patrocinador():

    if not session.get(
        "admin"
    ):

        return redirect(
            url_for(
                "admin"
            )
        )

    erro = None

    if request.method == "POST":

        nome = (
            request.form
            .get(
                "nome",
                ""
            )
            .strip()
        )

        link = (
            request.form
            .get(
                "link",
                ""
            )
            .strip()
        )

        if not nome:

            erro = (
                "Informe o nome "
                "do patrocinador."
            )

            return render_template(
                "novo_patrocinador.html",
                erro=erro
            )

        arquivo = request.files.get(
            "imagem"
        )

        try:

            imagem = salvar_imagem(
                arquivo
            )

        except Exception as erro_upload:

            erro = (
                "Erro ao enviar a imagem: "
                + str(
                    erro_upload
                )
            )

            return render_template(
                "novo_patrocinador.html",
                erro=erro
            )

        patrocinador = Patrocinador(
            nome=nome,
            imagem=imagem,
            link=link,
            ativo=True
        )

        db.session.add(
            patrocinador
        )

        db.session.commit()

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
# EXCLUIR PATROCINADOR
# ============================================================

@app.route(
    "/admin/excluir-patrocinador/<int:id>",
    methods=["POST"]
)
def excluir_patrocinador(id):

    if not session.get(
        "admin"
    ):

        return redirect(
            url_for(
                "admin"
            )
        )

    patrocinador = (
        Patrocinador.query
        .get_or_404(id)
    )

    imagem = (
        patrocinador.imagem
    )

    db.session.delete(
        patrocinador
    )

    db.session.commit()

    apagar_imagem(
        imagem
    )

    return redirect(
        url_for(
            "painel"
        )
    )


# ============================================================
# SAIR DO PAINEL
# ============================================================

@app.route(
    "/admin/sair"
)
def sair():

    session.pop(
        "admin",
        None
    )

    return redirect(
        url_for(
            "admin"
        )
    )


# ============================================================
# ERRO: IMAGEM MAIOR QUE 10 MB
# ============================================================

@app.errorhandler(413)
def arquivo_grande(error):

    return (
        "A imagem é muito grande. "
        "Envie uma imagem com até 10 MB.",
        413
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