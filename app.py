from flask import Flask, render_template, request, redirect, url_for, session
import os

app = Flask(__name__)

# Chave para manter o administrador logado
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-depois")


# Notícias iniciais do portal
noticias = [
    {
        "categoria": "Piauí",
        "titulo": "Confira as principais notícias do Piauí",
        "resumo": "Acompanhe as principais informações do estado.",
        "conteudo": "",
        "imagem": ""
    },
    {
        "categoria": "Política",
        "titulo": "Principais notícias da política",
        "resumo": "Veja os assuntos que estão movimentando a política.",
        "conteudo": "",
        "imagem": ""
    },
    {
        "categoria": "Cidades",
        "titulo": "Notícias e acontecimentos das cidades",
        "resumo": "Informação local e prestação de serviços.",
        "conteudo": "",
        "imagem": ""
    },
    {
        "categoria": "Esportes",
        "titulo": "Tudo sobre esportes",
        "resumo": "Confira as principais notícias esportivas.",
        "conteudo": "",
        "imagem": ""
    }
]


# Página inicial
@app.route("/")
def inicio():
    return render_template("index.html", noticias=noticias)


# Login do administrador
@app.route("/admin", methods=["GET", "POST"])
def admin():
    erro = None

    if request.method == "POST":
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")

        admin_usuario = os.environ.get("ADMIN_USER", "admin")
        admin_senha = os.environ.get("ADMIN_PASSWORD", "admin123")

        if usuario == admin_usuario and senha == admin_senha:
            session["admin"] = True
            return redirect(url_for("painel"))

        erro = "Usuário ou senha incorretos."

    return render_template("login.html", erro=erro)


# Painel administrativo
@app.route("/admin/painel")
def painel():
    if not session.get("admin"):
        return redirect(url_for("admin"))

    return render_template("painel.html")


# Cadastrar nova notícia
@app.route("/admin/nova-noticia", methods=["GET", "POST"])
def nova_noticia():
    if not session.get("admin"):
        return redirect(url_for("admin"))

    if request.method == "POST":
        categoria = request.form.get("categoria")
        titulo = request.form.get("titulo")
        resumo = request.form.get("resumo")
        conteudo = request.form.get("conteudo")
        imagem = request.form.get("imagem")

        nova = {
            "categoria": categoria,
            "titulo": titulo,
            "resumo": resumo,
            "conteudo": conteudo,
            "imagem": imagem
        }

        noticias.insert(0, nova)

        return redirect(url_for("inicio"))

    return render_template("nova_noticia.html")


# Sair do painel
@app.route("/admin/sair")
def sair():
    session.pop("admin", None)
    return redirect(url_for("admin"))


# Iniciar aplicação
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)