from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import uuid

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "troque-esta-chave-depois"
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
# UPLOAD DE IMAGENS
# ============================================================

UPLOAD_FOLDER = os.path.join(
    app.root_path,
    "static",
    "uploads"
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Máximo de 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

EXTENSOES_PERMITIDAS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}


def arquivo_permitido(nome_arquivo):

    return (
        "." in nome_arquivo
        and nome_arquivo.rsplit(".", 1)[1].lower()
        in EXTENSOES_PERMITIDAS
    )


def salvar_imagem(arquivo):

    if not arquivo:
        return ""

    if not arquivo.filename:
        return ""

    if not arquivo_permitido(arquivo.filename):
        return None

    nome_seguro = secure_filename(
        arquivo.filename
    )

    extensao = (
        nome_seguro
        .rsplit(".", 1)[1]
        .lower()
    )

    nome_novo = (
        f"{uuid.uuid4().hex}.{extensao}"
    )

    caminho = os.path.join(
        app.config["UPLOAD_FOLDER"],
        nome_novo
    )

    arquivo.save(caminho)

    return url_for(
        "static",
        filename=f"uploads/{nome_novo}"
    )


def apagar_imagem(caminho_imagem):

    if not caminho_imagem:
        return

    if not caminho_imagem.startswith(
        "/static/uploads/"
    ):
        return

    nome = os.path.basename(
        caminho_imagem
    )

    caminho = os.path.join(
        app.config["UPLOAD_FOLDER"],
        nome
    )

    if os.path.exists(caminho):

        try:
            os.remove(caminho)
        except OSError:
            pass


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
            Noticia.data_publicacao.desc()
        )
        .all()
    )

    patrocinadores = (
        Patrocinador.query
        .filter_by(ativo=True)
        .order_by(
            Patrocinador.id.desc()
        )
        .all()
    )

    return render_template(
        "index.html",
        noticias=noticias,
        patrocinadores=patrocinadores
    )


# ============================================================
# PÁGINA DA NOTÍCIA
# ============================================================

@app.route("/noticia/<int:id>")
def noticia(id):

    noticia = Noticia.query.get_or_404(id)

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

        usuario = request.form.get(
            "usuario",
            ""
        )

        senha = request.form.get(
            "senha",
            ""
        )

        admin_usuario = os.environ.get(
            "ADMIN_USER",
            "admin"
        )

        admin_senha = os.environ.get(
            "ADMIN_PASSWORD",
            "admin123"
        )

        if (
            usuario == admin_usuario
            and senha == admin_senha
        ):

            session["admin"] = True

            return redirect(
                url_for("painel")
            )

        erro = "Usuário ou senha incorretos."

    return render_template(
        "login.html",
        erro=erro
    )


# ============================================================
# PAINEL ADMIN
# ============================================================

@app.route("/admin/painel")
def painel():

    if not session.get("admin"):

        return redirect(
            url_for("admin")
        )

    noticias = (
        Noticia.query
        .order_by(
            Noticia.data_publicacao.desc()
        )
        .all()
    )

    patrocinadores = (
        Patrocinador.query
        .order_by(
            Patrocinador.id.desc()
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

    if not session.get("admin"):

        return redirect(
            url_for("admin")
        )

    erro = None

    if request.method == "POST":

        categoria = (
            request.form
            .get("categoria", "")
            .strip()
        )

        titulo = (
            request.form
            .get("titulo", "")
            .strip()
        )

        resumo = (
            request.form
            .get("resumo", "")
            .strip()
        )

        conteudo = (
            request.form
            .get("conteudo", "")
            .strip()
        )

        if not categoria or not titulo:

            erro = (
                "Informe a categoria e o título."
            )

            return render_template(
                "nova_noticia.html",
                erro=erro
            )

        arquivo = request.files.get(
            "imagem"
        )

        imagem = salvar_imagem(
            arquivo
        )

        if imagem is None:

            erro = (
                "Formato de imagem não permitido. "
                "Use JPG, JPEG, PNG ou WEBP."
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

    if not session.get("admin"):

        return redirect(
            url_for("admin")
        )

    noticia = Noticia.query.get_or_404(id)

    erro = None

    if request.method == "POST":

        categoria = (
            request.form
            .get("categoria", "")
            .strip()
        )

        titulo = (
            request.form
            .get("titulo", "")
            .strip()
        )

        resumo = (
            request.form
            .get("resumo", "")
            .strip()
        )

        conteudo = (
            request.form
            .get("conteudo", "")
            .strip()
        )

        if not categoria or not titulo:

            erro = (
                "Informe a categoria e o título."
            )

            return render_template(
                "editar_noticia.html",
                noticia=noticia,
                erro=erro
            )

        # Atualizar os textos
        noticia.categoria = categoria
        noticia.titulo = titulo
        noticia.resumo = resumo
        noticia.conteudo = conteudo

        # Verificar se uma nova foto foi enviada
        arquivo = request.files.get(
            "imagem"
        )

        if arquivo and arquivo.filename:

            nova_imagem = salvar_imagem(
                arquivo
            )

            if nova_imagem is None:

                erro = (
                    "Formato de imagem não permitido. "
                    "Use JPG, JPEG, PNG ou WEBP."
                )

                return render_template(
                    "editar_noticia.html",
                    noticia=noticia,
                    erro=erro
                )

            # Apaga foto antiga se ela ainda existir
            apagar_imagem(
                noticia.imagem
            )

            # Salva endereço da nova foto
            noticia.imagem = nova_imagem

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

    if not session.get("admin"):

        return redirect(
            url_for("admin")
        )

    noticia = Noticia.query.get_or_404(id)

    apagar_imagem(
        noticia.imagem
    )

    db.session.delete(
        noticia
    )

    db.session.commit()

    return redirect(
        url_for("painel")
    )


# ============================================================
# NOVO PATROCINADOR
# ============================================================

@app.route(
    "/admin/novo-patrocinador",
    methods=["GET", "POST"]
)
def novo_patrocinador():

    if not session.get("admin"):

        return redirect(
            url_for("admin")
        )

    erro = None

    if request.method == "POST":

        nome = (
            request.form
            .get("nome", "")
            .strip()
        )

        link = (
            request.form
            .get("link", "")
            .strip()
        )

        if not nome:

            erro = (
                "Informe o nome do patrocinador."
            )

            return render_template(
                "novo_patrocinador.html",
                erro=erro
            )

        arquivo = request.files.get(
            "imagem"
        )

        imagem = salvar_imagem(
            arquivo
        )

        if imagem is None:

            erro = (
                "Formato de imagem não permitido. "
                "Use JPG, JPEG, PNG ou WEBP."
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
            url_for("painel")
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

    if not session.get("admin"):

        return redirect(
            url_for("admin")
        )

    patrocinador = (
        Patrocinador.query
        .get_or_404(id)
    )

    apagar_imagem(
        patrocinador.imagem
    )

    db.session.delete(
        patrocinador
    )

    db.session.commit()

    return redirect(
        url_for("painel")
    )


# ============================================================
# SAIR
# ============================================================

@app.route("/admin/sair")
def sair():

    session.pop(
        "admin",
        None
    )

    return redirect(
        url_for("admin")
    )


# ============================================================
# ERRO DE IMAGEM GRANDE
# ============================================================

@app.errorhandler(413)
def arquivo_grande(error):

    return (
        "A imagem é muito grande. "
        "Envie uma imagem com até 10 MB.",
        413
    )


# ============================================================
# INICIAR
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