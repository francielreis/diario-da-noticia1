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

    def test_personalizacao_nao_afeta_outro_portal(self):
        a = self.criar_portal()
        b = self.criar_portal("portal-b", "Portal B", "editor-b")
        self.login_cliente("portal-a")
        r = self.cliente.post("/p/portal-a/admin/configuracoes", data={
            "_csrf_token": self.token(),
            "slogan": "O melhor de Picos",
            "cor": "#cc1133",
        })
        self.assertEqual(r.status_code, 302)
        with app.app_context():
            marca = app.extensions["saas_models"]["marca"]
            self.assertEqual(db.session.query(marca).count(), 1)
            self.assertEqual(db.session.query(marca).first().portal_id, a)
        site_a = self.cliente.get("/p/portal-a/").get_data(as_text=True)
        site_b = self.cliente.get("/p/portal-b/").get_data(as_text=True)
        self.assertIn("O melhor de Picos", site_a)
        self.assertIn("#cc1133", site_a)
        self.assertNotIn("O melhor de Picos", site_b)

    def test_anuncio_nao_pode_ser_alterado_por_outro_cliente(self):
        a = self.criar_portal()
        self.criar_portal("portal-b", "Portal B", "editor-b")
        with app.app_context():
            anuncio = app.extensions["saas_models"]["anuncio"](
                portal_id=a, titulo="Patrocinador A",
                imagem="https://res.cloudinary.com/exemplo/image/upload/a.webp",
                ativo=True
            )
            db.session.add(anuncio)
            db.session.commit()
            id_anuncio = anuncio.id
        self.login_cliente("portal-b", "editor-b")
        res = self.cliente.post(
            f"/p/portal-b/admin/anuncios/{id_anuncio}/alternar",
            data={"_csrf_token": self.token()},
        )
        self.assertEqual(res.status_code, 404)
        self.assertIn("Patrocinador A", self.cliente.get("/p/portal-a/").get_data(as_text=True))
        self.assertNotIn("Patrocinador A", self.cliente.get("/p/portal-b/").get_data(as_text=True))
        with app.app_context():
            anuncio = app.extensions["saas_models"]["anuncio"]
            self.assertTrue(db.session.query(anuncio).first().ativo)

    def test_mensalidade_manual_sem_duplicar_competencia(self):
        portal_id = self.criar_portal()
        self.login_master()
        data = {
            "_csrf_token": self.token(),
            "portal_id": str(portal_id),
            "competencia": "2026-10",
            "valor": "150,00",
            "pago": "1",
        }
        self.assertEqual(self.cliente.post("/master/mensalidades/salvar", data=data).status_code, 302)
        with app.app_context():
            Mensalidade = app.extensions["saas_models"]["mensalidade"]
            pago = db.session.query(Mensalidade).one()
            self.assertEqual(pago.valor_centavos, 15000)
            self.assertIsNotNone(pago.pago_em)
        data["pago"] = "0"
        self.assertEqual(self.cliente.post("/master/mensalidades/salvar", data=data).status_code, 302)
        with app.app_context():
            Mensalidade = app.extensions["saas_models"]["mensalidade"]
            self.assertEqual(db.session.query(Mensalidade).count(), 1)
            self.assertIsNone(db.session.query(Mensalidade).one().pago_em)

    def test_mensalidades_exclusivas_do_master(self):
        self.criar_portal()
        self.assertEqual(self.cliente.get("/master/mensalidades").status_code, 302)
        self.login_cliente("portal-a")
        self.assertEqual(self.cliente.post("/master/mensalidades/salvar", data={}).status_code, 302)
        self.assertEqual(self.cliente.get("/master/mensalidades").status_code, 302)

    def test_master_entrar_no_cliente_sem_senha(self):
        portal_id = self.criar_portal("portal-master", "Portal Master", "redator")
        self.login_master()
        resposta = self.cliente.post(
            f"/master/portal/{portal_id}/entrar",
            data={"_csrf_token": self.token()},
        )
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(
            resposta.headers["Location"],
            "/p/portal-master/admin/painel",
        )
        self.assertEqual(self.cliente.get(resposta.headers["Location"]).status_code, 200)
        self.assertEqual(self.cliente.get("/master/painel").status_code, 302)

    def test_convite_acesso_temporario_uso_unico(self):
        import hashlib
        from datetime import datetime, timedelta
        portal_id = self.criar_portal("picos-demo", "Portal Picos Demo", "editor-demo")
        token = "AbcdefGhijKlmnOP0123456789_AbcdefghijklMN"
        Convite = app.extensions["saas_models"]["convite_demo"]
        with app.app_context():
            db.session.add(Convite(
                portal_id=portal_id,
                token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
                expira_em=datetime.utcnow() + timedelta(hours=2),
            ))
            db.session.commit()
        resposta = self.cliente.get("/convite-demo/" + token)
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["Location"], "/p/picos-demo/admin/painel")
        self.assertEqual(resposta.headers["Cache-Control"], "no-store")
        self.assertEqual(self.cliente.get(resposta.headers["Location"]).status_code, 200)
        resposta_repetida = self.cliente.get("/convite-demo/" + token)
        self.assertEqual(resposta_repetida.status_code, 410)

    def test_convite_expirado_nao_autentica(self):
        import hashlib
        from datetime import datetime, timedelta
        portal_id = self.criar_portal("demo-expirado", "Expirado", "editor-demo")
        token = "AAAbbbCCCdddEEEfff000111222333444xyz12345"
        Convite = app.extensions["saas_models"]["convite_demo"]
        with app.app_context():
            db.session.add(Convite(
                portal_id=portal_id,
                token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
                expira_em=datetime.utcnow() - timedelta(minutes=1),
            ))
            db.session.commit()
        self.assertEqual(self.cliente.get("/convite-demo/" + token).status_code, 410)
        self.assertEqual(self.cliente.get("/p/demo-expirado/admin/painel").status_code, 302)

    def test_sem_csrf_nao_pode_criar(self):
        self.login_master()
        resposta = self.cliente.post("/master/criar", data={
            "nome": "X", "slug": "portal-x", "dono": "X",
            "usuario": "teste", "senha": "senha-forte-teste", "plano": "basico",
        })
        self.assertEqual(resposta.status_code, 400)


if __name__ == "__main__":
    unittest.main()
