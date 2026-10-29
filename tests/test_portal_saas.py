"""Testes de autorização e isolamento dos portais SaaS.

Rodar: python -m unittest discover -s tests -v
Banco SQLite em memória: não toca no PostgreSQL de produção.
"""
import os
import unittest

from werkzeug.security import generate_password_hash

# As variáveis precisam ser definidas ANTES do primeiro import de app.py.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "chave-de-teste-local-nao-usar-em-producao"
os.environ["MASTER_USER"] = "master_teste"
os.environ["MASTER_PASSWORD_HASH"] = generate_password_hash("senha_master_de_teste")

from app import app, db  # noqa: E402


class TestePortaisSaaS(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        with app.app_context():
            db.drop_all()
            db.create_all()
        self.cliente = app.test_client()
        self.Portal = app.extensions["saas_models"]["portal"]
        self.Noticia = app.extensions["saas_models"]["noticia"]

    def token(self):
        with self.cliente.session_transaction() as sessao:
            return sessao["_csrf_token"]

    def criar_portal(self, slug="portal-a", nome="Portal A", usuario="editor"):
        with app.app_context():
            novo = self.Portal(
                nome=nome, slug=slug, dono="Responsável de teste",
                usuario=usuario, senha_hash=generate_password_hash("senha-editor-123"),
                plano="basico", ativo=True,
            )
            db.session.add(novo)
            db.session.commit()
            return novo.id

    def login_cliente(self, slug, usuario="editor"):
        self.cliente.get("/p/" + slug + "/admin")
        resposta = self.cliente.post("/p/" + slug + "/admin", data={
            "_csrf_token": self.token(),
            "usuario": usuario,
            "senha": "senha-editor-123",
        })
        self.assertEqual(resposta.status_code, 302)

    def login_master(self):
        self.cliente.get("/master")
        resposta = self.cliente.post("/master", data={
            "_csrf_token": self.token(),
            "usuario": "master_teste",
            "senha": "senha_master_de_teste",
        })
        self.assertEqual(resposta.status_code, 302)

    def test_legacy_e_master_isolados(self):
        self.assertEqual(self.cliente.get("/").status_code, 200)
        self.assertEqual(self.cliente.get("/master/painel").status_code, 302)
        self.assertEqual(self.cliente.get("/p/portal-inexistente/").status_code, 404)

    def test_master_cria_portal_sem_duplicar_slug(self):
        self.login_master()
        dados = {
            "_csrf_token": self.token(),
            "nome": "Portal A",
            "slug": "portal-a",
            "dono": "Responsável",
            "usuario": "editor",
            "senha": "senha-inicial-forte",
            "plano": "profissional",
        }
        resposta = self.cliente.post("/master/criar", data=dados)
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(self.cliente.get("/p/portal-a/").status_code, 200)
        self.cliente.post("/master/criar", data=dados)
        with app.app_context():
            self.assertEqual(db.session.query(self.Portal).count(), 1)

    def test_cliente_publica_mas_nao_acessa_noticia_de_outro(self):
        a = self.criar_portal()
        b = self.criar_portal(slug="portal-b", nome="Portal B", usuario="editor-b")
        self.login_cliente("portal-a")
        resposta = self.cliente.post("/p/portal-a/admin/noticias/nova", data={
            "_csrf_token": self.token(),
            "categoria": "Cidades",
            "titulo": "Notícia de A",
            "resumo": "Resumo da matéria",
            "conteudo": "Texto exclusivo do portal A",
        })
        self.assertEqual(resposta.status_code, 302)
        with app.app_context():
            noticia = db.session.query(self.Noticia).first()
            noticia_id = noticia.id
            self.assertEqual(noticia.portal_id, a)

        self.assertEqual(self.cliente.get(f"/p/portal-b/noticia/{noticia_id}").status_code, 404)
        self.assertNotIn("Notícia de A", self.cliente.get("/p/portal-b/").get_data(as_text=True))

        self.cliente.get("/p/portal-b/admin")
        # Login como outro cliente invalida a sessão anterior.
        self.login_cliente("portal-b", usuario="editor-b")
        self.assertEqual(
            self.cliente.get(f"/p/portal-a/admin/noticias/{noticia_id}/editar").status_code, 302
        )
        self.assertEqual(
            self.cliente.post(
                f"/p/portal-b/admin/noticias/{noticia_id}/excluir",
                data={"_csrf_token": self.token()},
            ).status_code, 404
        )
        with app.app_context():
            self.assertEqual(db.session.query(self.Noticia).count(), 1)

    def test_suspensao_bloqueia_editor_sem_apagar_noticias(self):
        portal_id = self.criar_portal()
        self.login_cliente("portal-a")
        with app.app_context():
            db.session.add(self.Noticia(
                portal_id=portal_id, categoria="Cidades",
                titulo="Notícia preservada", resumo="Resumo", conteudo="Texto"
            ))
            db.session.commit()
            p = db.session.get(self.Portal, portal_id)
            p.ativo = False
            db.session.commit()
        self.assertEqual(self.cliente.get("/p/portal-a/admin/painel").status_code, 403)
        resposta = self.cliente.get("/p/portal-a/")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Notícia preservada", resposta.get_data(as_text=True))

    def test_sem_csrf_nao_pode_criar(self):
        self.login_master()
        resposta = self.cliente.post("/master/criar", data={
            "nome": "X", "slug": "portal-x", "dono": "X",
            "usuario": "teste", "senha": "senha-forte-teste", "plano": "basico",
        })
        self.assertEqual(resposta.status_code, 400)


if __name__ == "__main__":
    unittest.main()
