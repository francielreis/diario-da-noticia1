from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import uuid

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-depois")


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

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///diario.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# UPLOAD DE IMAGENS
# ============================================================

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

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

    if not arquivo or not arquivo.filename:
        return ""

    if not arquivo_permitido(arquivo.filename):
        return None

    nome_seguro = secure_filename(arquivo.filename)

    extensao = nome_seguro.rsplit(".", 1)[1].lower()

    nome_novo = f"{uuid.uuid4().hex}.{extensao}"

    caminho = os.path.join(
        app.config["UPLOAD_FOLDER"],
        nome_novo
    )

    arquivo.save(caminho)

    return url_for(
        "static",
        filename=f"uploads/{nome_novo}"
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
        .order_by(Noticia.data_publicacao.desc())
        .all()
    )

    patrocinadores = (
        Patrocinador.query
        .filter_by(ativo=True)
        .order_by(Patrocinador.id.desc())
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
# LOGIN
# ============================================================

@app.route(
    "/admin",
    methods=["GET", "POST"]
)
def admin():

    erro = None

    if request.method == "POST":

        usuario = request.form.get("usuario")
        senha = request.form.get("senha")

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
# PAINEL
# ============================================================

@app.route("/admin/painel")
def painel():

    if not session.get("admin"):
        return redirect(
            url_for("admin")
        )

    noticias = (
        Noticia.query
        .order_by(Noticia.data_publicacao.desc())
        .all()
    )

    patrocinadores = (
        Patrocinador.query
        .order_by(Patrocinador.id.desc())
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

        categoria = request.form.get(
            "categoria"
        )

        titulo = request.form.get(
            "titulo"
        )

        resumo = request.form.get(
            "resumo"
        )

        conteudo = request.form.get(
            "conteudo"
        )

        arquivo = request.files.get(
            "imagem"
        )

        imagem = salvar_imagem(arquivo)

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

        db.session.add(nova)
        db.session.commit()

        return redirect(
            url_for("inicio")
        )

    return render_template(
        "nova_noticia.html",
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

    db.session.delete(noticia)
    db.session.commit()

    return redirect(
        url_for("painel")
    )


# ============================================================
# CADASTRAR PATROCINADOR
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

        nome = request.form.get(
            "nome"
        )

        link = request.form.get(
            "link"
        )

        arquivo = request.files.get(
            "imagem"
        )

        imagem = salvar_imagem(arquivo)

        if imagem is None:

            erro = (
                "Formato de imagem não permitido."
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

        db.session.add(patrocinador)
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
        Patrocinador.query.get_or_404(id)
    )

    db.session.delete(patrocinador)
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