from flask import Flask

app = Flask(__name__)


@app.route("/")
def inicio():
    return """
    <h1>Diário da Notícia</h1>
    <p>Bem-vindo ao nosso portal de notícias!</p>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
