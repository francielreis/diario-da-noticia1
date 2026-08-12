from flask import Flask, render_template

app = Flask(__name__)

noticias = [
    {
        "categoria": "Piauí",
        "titulo": "Confira as principais notícias do Piauí",
        "resumo": "Acompanhe as principais informações do estado."
    },
    {
        "categoria": "Política",
        "titulo": "Principais notícias da política",
        "resumo": "Veja os assuntos que estão movimentando a política."
    },
    {
        "categoria": "Cidades",
        "titulo": "Notícias e acontecimentos das cidades",
        "resumo": "Informação local e prestação de serviços."
    },
    {
        "categoria": "Esportes",
        "titulo": "Tudo sobre esportes",
        "resumo": "Confira as principais notícias esportivas."
    }
]

@app.route("/")
def inicio():
    return render_template("index.html", noticias=noticias)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
