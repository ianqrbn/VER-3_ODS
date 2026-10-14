
import unittest

from s3.errors import ErroS3
from s3.routing import ConfiguracaoRoteamento, RoteadorAlertas, renderizar

from fabricas import evento, ler_json, rota, roteador


class TestConfiguracaoRoteamento(unittest.TestCase):

    def test_listas_viram_tuplas(self):
        configuracao = rota(destinatarios=["role:supervisor"], canais=["SOUND"])

        self.assertEqual(configuracao.destinatarios, ("role:supervisor",))
        self.assertEqual(configuracao.canais, ("SOUND",))

    def test_destinatario_sem_virgula(self):
        """("role:supervisor") é texto, não tupla: deve ser rejeitado."""

        with self.assertRaises(ErroS3):
            rota(destinatarios=("role:supervisor"))

    def test_canal_invalido(self):
        for canais in (("TELA",), "SCREEN", ()):
            with self.subTest(canais=canais):
                with self.assertRaises(ErroS3):
                    rota(canais=canais)

    def test_severidade_invalida(self):
        with self.assertRaises(ErroS3):
            rota(severidade="ALTA")

    def test_titulo_obrigatorio(self):
        with self.assertRaises(ValueError):
            rota(titulo="")

    def test_status_minimo_invalido(self):
        with self.assertRaises(ValueError):
            rota(status_minimo="ALL")


class TestRoteadorAlertas(unittest.TestCase):

    def test_resolver_roteamento(self):
        """Deve encontrar a rota do tipo de evento."""

        configuracao = roteador().resolver(evento())

        self.assertEqual(configuracao.severidade, "HIGH")
        self.assertEqual(configuracao.canais, ("SCREEN", "PUSH"))

    def test_evento_sem_rota(self):
        """Tipo sem rota não gera alerta, mas não é erro."""

        self.assertIsNone(roteador().resolver(evento(tipo="ZONE_ENTER")))

    def test_incerto_com_minimo_confirmado(self):
        """min_status CONFIRMED ignora eventos UNCERTAIN."""

        self.assertIsNone(roteador().resolver(evento(status="UNCERTAIN")))

    def test_incerto_com_minimo_incerto(self):
        """min_status UNCERTAIN roteia os dois."""

        configurado = roteador(status_minimo="UNCERTAIN")

        self.assertIsNotNone(configurado.resolver(evento(status="UNCERTAIN")))
        self.assertIsNotNone(configurado.resolver(evento(status="CONFIRMED")))

    def test_roteador_sem_regras(self):
        with self.assertRaises(ValueError):
            RoteadorAlertas({})

    def test_evento_invalido(self):
        with self.assertRaises(ValueError):
            roteador().resolver(evento(confianca=2))


class TestArtefatoRouting(unittest.TestCase):

    def test_carregar_exemplo(self):
        """jsons/routing_a5.json deve ser carregado."""

        carregado = RoteadorAlertas.de_artefato(
            ler_json("routing_a5.json"), "routing-a5-1"
        )

        configuracao = carregado.resolver(evento())

        self.assertEqual(carregado.versao, "routing-a5-1")
        self.assertEqual(configuracao.destinatarios, ("role:supervisor",))
        self.assertTrue(configuracao.captura)

    def test_rota_incompleta(self):
        conteudo = ler_json("routing_a5.json")
        del conteudo["routes"][0]["title"]

        with self.assertRaises(ValueError):
            RoteadorAlertas.de_artefato(conteudo, "v")

    def test_rota_repetida(self):
        conteudo = ler_json("routing_a5.json")
        conteudo["routes"].append(dict(conteudo["routes"][0]))

        with self.assertRaises(ValueError):
            RoteadorAlertas.de_artefato(conteudo, "v")

    def test_sem_rotas(self):
        for conteudo in ({}, {"routes": []}, []):
            with self.subTest(conteudo=conteudo):
                with self.assertRaises(ValueError):
                    RoteadorAlertas.de_artefato(conteudo, "v")


class TestRenderizar(unittest.TestCase):

    def test_substitui_campos(self):
        texto = renderizar(
            "Pessoa sem {equipment_item} em {zone_id} há {duration_s} s",
            evento(),
        )

        self.assertEqual(texto, "Pessoa sem luva em galpao-solda há 8 s")

    def test_campo_de_details(self):
        texto = renderizar(
            "{compliance}", evento(detalhes={"compliance": "ABSENT"})
        )

        self.assertEqual(texto, "ABSENT")

    def test_campo_ausente_mantem_marcador(self):
        texto = renderizar("Zona {zone_id}", evento(zona_id=None))

        self.assertEqual(texto, "Zona {zone_id}")

    def test_modelo_mal_formado(self):
        self.assertEqual(renderizar("Erro {", evento()), "Erro {")


if __name__ == "__main__":
    unittest.main()
