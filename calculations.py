"""
Hydrological calculations for IDF Curve Generator.
Includes Gumbel analysis, rainfall disaggregation, Sherman equation fitting,
and ANA HidroWebService API integration.
"""
import logging
import io
import time
import requests
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import os
import calendar
import colorsys
from collections import Counter
from datetime import datetime
from PIL import Image, ImageDraw
from scipy.optimize import curve_fit
from scipy.stats import pearsonr, kendalltau, t as student_t
from i18n import t

logger = logging.getLogger("idf")


class UserError(Exception):
    """Erro de validação destinado à mensagem exibida ao usuário na interface."""


# ── Gumbel constants table (Yn, sn) indexed by sample size N ──────────────────
GUMBEL_CONSTANTS = {
    10:  (0.4952, 0.9496),
    15:  (0.5128, 1.0206),
    20:  (0.5236, 1.0628),
    25:  (0.5309, 1.0915),
    30:  (0.5362, 1.1124),
    35:  (0.5403, 1.1285),
    40:  (0.5436, 1.1413),
    45:  (0.5463, 1.1518),
    50:  (0.5485, 1.1607),
    55:  (0.5504, 1.1681),
    60:  (0.5521, 1.1747),
    65:  (0.5535, 1.1803),
    70:  (0.5548, 1.1854),
    75:  (0.5561, 1.1898),
    80:  (0.5569, 1.1938),
    85:  (0.5578, 1.1974),
    90:  (0.5586, 1.2007),
    95:  (0.5593, 1.2037),
    100: (0.5600, 1.2065),
}

# Return periods for analysis
RETURN_PERIODS = [2, 5, 10, 15, 20, 25, 50, 100]

# Durations in minutes
DURATIONS = [6, 10, 15, 20, 25, 30, 60, 120, 180, 240, 300, 360,
             420, 480, 540, 600, 660, 720, 780, 840, 900, 1440]

# ── Isozone constants (Taborga method) ────────────────────────────────────────
ISOZONA_CONSTANTS = {
    'A': {'rel1h': {5: 36.2, 10: 35.8, 15: 35.6, 20: 35.5, 25: 35.4, 50: 35.0, 100: 34.7},
          'rel6min': {'05/50': 7.0, '100': 6.3}},
    'B': {'rel1h': {5: 38.1, 10: 37.8, 15: 37.5, 20: 37.4, 25: 37.3, 50: 36.9, 100: 36.6},
          'rel6min': {'05/50': 8.4, '100': 7.5}},
    'C': {'rel1h': {5: 40.1, 10: 39.7, 15: 39.5, 20: 39.3, 25: 39.2, 50: 38.8, 100: 38.4},
          'rel6min': {'05/50': 9.8, '100': 8.8}},
    'D': {'rel1h': {5: 42.0, 10: 41.6, 15: 41.4, 20: 41.2, 25: 41.1, 50: 40.7, 100: 40.3},
          'rel6min': {'05/50': 11.2, '100': 10.0}},
    'E': {'rel1h': {5: 44.0, 10: 43.6, 15: 43.3, 20: 43.2, 25: 43.0, 50: 42.6, 100: 42.2},
          'rel6min': {'05/50': 12.6, '100': 11.2}},
    'F': {'rel1h': {5: 46.0, 10: 45.5, 15: 45.3, 20: 45.1, 25: 44.9, 50: 44.5, 100: 44.1},
          'rel6min': {'05/50': 13.9, '100': 12.4}},
    'G': {'rel1h': {5: 47.9, 10: 47.4, 15: 47.2, 20: 47.0, 25: 46.8, 50: 46.4, 100: 45.9},
          'rel6min': {'05/50': 15.4, '100': 13.7}},
    'H': {'rel1h': {5: 49.9, 10: 49.4, 15: 49.1, 20: 48.9, 25: 48.8, 50: 48.3, 100: 47.8},
          'rel6min': {'05/50': 16.7, '100': 14.9}},
}

ISOZONAS = list(ISOZONA_CONSTANTS.keys())
ISOZONA_MAP_PATH = os.path.join(os.path.dirname(__file__), "assets", "isozonas_brasil.png")

# ── Bounds e Faixas da Equação de Sherman ─────────────────────────────────────
# Bounds do otimizador (espaço de busca admissível para convergência numérica da regressão)
SHERMAN_OPTIMIZER_BOUNDS = {
    'A': (10.0, 20000.0),
    'B': (0.08, 0.45),
    'C': (3.0, 70.0),
    'D': (0.50, 0.98),
}

# Faixas de plausibilidade hidrológica típica da literatura (para alertas ao projetista)
SHERMAN_TYPICAL_RANGES = {
    'A': (50.0, 10000.0),
    'B': (0.12, 0.35),
    'C': (8.0, 45.0),
    'D': (0.60, 0.90),
}


def coord_para_pixel_isozona(lat: float, lon: float) -> tuple[int, int]:
    """
    Converte coordenadas geográficas (lat, lon) em pixels (x, y) sobre o
    Mapa de Isozonas do Brasil (Simões 2006 / Carneiro et al. 2002).
    Grade calibrada entre -70° a -40° de longitude e 0° a -30° de latitude.
    """
    y = 115.0 - 11.0 * float(lat)
    x = -0.0290476 * (float(lon) ** 2) + 6.96905 * float(lon) + 682.786
    return int(round(x)), int(round(y))


def classificar_cor_isozona(r: int, g: int, b: int) -> str:
    """Classifica um pixel RGB na respectiva Isozona de Taborga pelo espaço HSV."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
    deg = h * 360.0

    # Fundo bege ou branco (fora do território brasileiro) ou linhas/tons de cinza
    if s < 0.20:
        if v > 0.80:
            return 'BACKGROUND'
        return 'GRID'
    # Linhas de grade, contornos, textos ou preto (nunca classificar como C!)
    if v < 0.28:
        return 'GRID'

    if deg < 15 or deg >= 340:
        return 'B'  # Vermelho = Isozona B
    elif 15 <= deg < 40:
        return 'H'  # Laranja = Isozona H
    elif 40 <= deg < 80:
        return 'E'  # Amarelo = Isozona E
    elif 80 <= deg < 165:
        return 'D'  # Verde = Isozona D
    elif 165 <= deg < 195:
        return 'A'  # Ciano = Isozona A
    elif 195 <= deg < 265:
        return 'F'  # Azul (J no mapa) = Isozona F
    elif 265 <= deg < 340:
        return 'G'  # Magenta = Isozona G

    return 'UNKNOWN'


def detectar_isozona_coordenadas(
    lat: float,
    lon: float,
    img_path: str = None,
    retornar_coords: bool = False,
) -> str | tuple[str, int, int, float]:
    """
    Identifica a Isozona de Taborga por amostragem de cor sob o ponto (lat, lon)
    no mapa de isozonas com votação por maioria em janela vizinha.
    Retorna a sigla da Isozona ('A'-'H') ou 'FALLBACK' se não identificada.
    """
    path = img_path or ISOZONA_MAP_PATH
    x, y = coord_para_pixel_isozona(lat, lon)

    def _ret(c, conf=0.0):
        return (c, x, y, conf) if retornar_coords else c

    if not os.path.exists(path):
        return _ret('FALLBACK', 0.0)

    try:
        img = Image.open(path).convert('RGB')
        arr = np.array(img)
        w, h = img.size

        # Amostragem em janela com votação por maioria ignorando GRID e BACKGROUND
        votos = []
        for r in range(0, 16):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    px, py = x + dx, y + dy
                    if 0 <= px < w and 0 <= py < h:
                        c_iso = classificar_cor_isozona(*arr[py, px])
                        if c_iso in ISOZONA_CONSTANTS:
                            votos.append(c_iso)
            if len(votos) >= 9:
                break

        if votos:
            contagem = Counter(votos)
            melhor_iso, num_votos = contagem.most_common(1)[0]
            confianca = num_votos / len(votos)
            if confianca >= 0.40 and num_votos >= 2:
                return _ret(melhor_iso, round(confianca, 2))

    except Exception as exc:
        logger.warning(f"Erro ao ler imagem de isozonas: {exc}")

    return _ret('FALLBACK', 0.0)


def desenhar_pin_mapa_isozonas(lat: float, lon: float, img_path: str = None) -> Image.Image:
    """
    Desenha um marcador de alta visibilidade (alvo circular e mira) sobre
    o mapa oficial de isozonas na posição exata da obra.
    """
    path = img_path or ISOZONA_MAP_PATH
    if not os.path.exists(path):
        # Cria imagem de placeholder caso falte o asset
        img_placeholder = Image.new('RGB', (450, 480), color=(240, 240, 240))
        return img_placeholder

    base_img = Image.open(path).convert('RGBA')
    w, h = base_img.size
    x, y = coord_para_pixel_isozona(lat, lon)

    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if 0 <= x < w and 0 <= y < h:
        # Anel externo vermelho com transparência
        draw.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(220, 20, 60, 150), outline=(255, 255, 255, 255), width=2)
        # Centro branco sólido
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 255, 255, 255), outline=(180, 0, 0, 255), width=1)
        # Linhas de mira (crosshair)
        draw.line([x - 18, y, x - 13, y], fill=(220, 20, 60, 240), width=2)
        draw.line([x + 13, y, x + 18, y], fill=(220, 20, 60, 240), width=2)
        draw.line([x, y - 18, x, y - 13], fill=(220, 20, 60, 240), width=2)
        draw.line([x, y + 13, x, y + 18], fill=(220, 20, 60, 240), width=2)

    return Image.alpha_composite(base_img, overlay).convert('RGB')

# ── API Integration (ANA HidroWebService) ─────────────────────────────────────

# Cache de token compartilhado entre instâncias. A ANA monitora requisições de
# autenticação em alta frequência e bloqueia o IP automaticamente, por isso o
# token (validade de 60 min) é reaproveitado enquanto estiver válido.
_TOKEN_CACHE: dict = {}


class AnaHidroWebService:
    """
    Cliente para consumir a API HidroWebService da ANA.

    Os nomes dos parâmetros de query são literais em português, com espaços e
    acentos, exatamente como publicados em
    https://www.ana.gov.br/hidrowebservice/api-docs — não são CamelCase.
    """
    BASE_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas"

    # HidroUF inclui países vizinhos (AR, BO, VE...), mas o inventário só aceita
    # as 27 unidades federativas brasileiras.
    UFS_BRASIL = {
        'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA',
        'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
    }

    # Margem de segurança para renovar o token antes dos 60 min de validade.
    TOKEN_TTL_SEGUNDOS = 50 * 60

    def __init__(self, identificador: str, senha: str):
        self.identificador = identificador
        self.senha = senha
        self.session = requests.Session()

    # ── Autenticação ─────────────────────────────────────────────────────────
    @property
    def token(self):
        entrada = _TOKEN_CACHE.get(self.identificador)
        if entrada and time.time() < entrada["expira_em"]:
            return entrada["token"]
        return None

    def _autenticar(self) -> str:
        """
        Obtém o token de autenticação, reaproveitando o cache quando válido.

        A ANA responde HTTP 417 de forma intermitente quando há autenticações em
        sequência (o serviço monitora essa frequência e pode bloquear o IP), por
        isso o token é cacheado e o 417 é tratado com espera progressiva.
        """
        if self.token:
            return self.token

        headers = {
            "Identificador": self.identificador,
            "Senha": self.senha,
            "Accept": "application/json",
            "User-Agent": "AUTOIDF/1.0 (Viktor)",
        }

        response = None
        for tentativa in range(4):
            response = self.session.get(f"{self.BASE_URL}/OAUth/v1", headers=headers, timeout=60)

            if response.status_code == 200:
                break
            if response.status_code in (401, 403):
                raise ValueError(
                    f"Credenciais recusadas pela ANA (HTTP {response.status_code}). Verifique "
                    "ANA_USER (CPF/CNPJ somente dígitos) e ANA_PASS."
                )
            if response.status_code in (417, 429) or response.status_code >= 500:
                espera = 2 ** tentativa
                logger.warning(
                    f"ANA respondeu HTTP {response.status_code} na autenticação; "
                    f"nova tentativa em {espera}s."
                )
                time.sleep(espera)
                continue
            break

        response.raise_for_status()
        items = response.json().get("items") or {}
        if isinstance(items, list):
            items = items[0] if items else {}
        token = items.get("tokenautenticacao")
        if not token:
            raise ValueError(f"Token não encontrado na resposta da ANA: {response.text[:300]}")

        _TOKEN_CACHE[self.identificador] = {
            "token": token,
            "expira_em": time.time() + self.TOKEN_TTL_SEGUNDOS,
        }
        logger.info("🔑 Autenticação na API da ANA realizada com sucesso.")
        return token

    # Status transitórios: a ANA devolve 503/502/504 sob rajada de requisições
    # (o corpo costuma ser uma página HTML de indisponibilidade) e 429 quando
    # limita a taxa. Todos são reprocessáveis com espera progressiva.
    _STATUS_TRANSITORIOS = (429, 502, 503, 504)

    def _get(self, rota: str, params: dict = None, timeout: int = 120, tentativas: int = 4):
        """
        GET autenticado com retry. Renova o token em 401/403 e repete com espera
        progressiva em erros transitórios (503/502/504/429) ou falhas de conexão.
        """
        url = f"{self.BASE_URL}{rota}"
        res = None

        for tentativa in range(tentativas):
            headers = {"Authorization": f"Bearer {self._autenticar()}", "Accept": "application/json"}
            try:
                res = self.session.get(url, headers=headers, params=params, timeout=timeout)
            except requests.RequestException as e:
                if tentativa == tentativas - 1:
                    raise
                espera = 2 ** tentativa
                logger.warning(f"Falha de conexão com a ANA ({e}); nova tentativa em {espera}s.")
                time.sleep(espera)
                continue

            if res.status_code in (401, 403):
                _TOKEN_CACHE.pop(self.identificador, None)
                continue  # renova o token e refaz a requisição

            if res.status_code in self._STATUS_TRANSITORIOS and tentativa < tentativas - 1:
                espera = 2 ** tentativa
                logger.warning(
                    f"ANA respondeu HTTP {res.status_code} em {rota}; nova tentativa em {espera}s."
                )
                time.sleep(espera)
                continue

            return res

        return res

    @staticmethod
    def _mensagem_erro(res) -> str:
        """Extrai uma mensagem curta, evitando despejar páginas HTML de erro."""
        try:
            msg = res.json().get("message")
            if msg:
                return str(msg)
        except Exception:
            pass
        texto = (res.text or "").strip()
        if texto[:1] in ("<", "{") or "<html" in texto[:200].lower():
            return f"resposta não-JSON do servidor (HTTP {res.status_code})"
        return texto[:200] or f"HTTP {res.status_code}"

    # ── Catálogos ────────────────────────────────────────────────────────────
    def listar_ufs_disponiveis(self) -> list:
        """Retorna as siglas das UFs a partir do catálogo oficial da ANA."""
        try:
            res = self._get("/HidroUF/v1", timeout=60)
            if res.status_code != 200:
                logger.error(f"Erro ao obter UFs (HTTP {res.status_code}): {self._mensagem_erro(res)}")
                return []
            items = res.json().get("items") or []
            siglas = {str(d.get("Estado_Sigla") or "").strip().upper() for d in items}
            return sorted(siglas & self.UFS_BRASIL)
        except Exception as e:
            logger.error(f"Erro ao obter catálogo de UFs: {e}")
            return []

    def listar_estacoes_por_uf(self, uf: str, apenas_pluviometricas: bool = True) -> list:
        """
        Lista as estações de uma UF. O inventário exige pelo menos um filtro
        (estação, UF ou bacia); sem filtro a API responde HTTP 406.
        """
        try:
            res = self._get(
                "/HidroInventarioEstacoes/v1",
                params={"Unidade Federativa": uf.strip().upper()},
                timeout=180,
            )
            if res.status_code != 200:
                logger.error(
                    f"Erro ao listar estações de {uf} (HTTP {res.status_code}): {self._mensagem_erro(res)}"
                )
                return []

            items = res.json().get("items") or []
            lista = []
            for d in items:
                cod = d.get("codigoestacao")
                if not cod:
                    continue
                tipo = str(d.get("Tipo_Estacao") or "")
                if apenas_pluviometricas and not tipo.lower().startswith("pluvi"):
                    continue
                lat = _num_ptbr(d.get("Estacao_Latitude"))
                lon = _num_ptbr(d.get("Estacao_Longitude"))
                alt = _num_ptbr(d.get("Estacao_Altitude"))
                lista.append({
                    "codigo": str(cod).strip(),
                    "nome": str(d.get("Estacao_Nome") or "Desconhecida").strip(),
                    "latitude": lat if np.isfinite(lat) else None,
                    "longitude": lon if np.isfinite(lon) else None,
                    "altitude": alt if np.isfinite(alt) else None,
                    "municipio": str(d.get("Estacao_Municipio_Nome") or "").strip(),
                    "rio": str(d.get("Estacao_Rio_Nome") or "").strip(),
                })

            logger.info(f"✅ Encontradas {len(lista)} estações para a UF {uf}")
            return sorted(lista, key=lambda x: x["nome"])
        except Exception as e:
            logger.error(f"Erro ao listar estações de {uf}: {e}")
            return []

    # ── Série de chuvas ──────────────────────────────────────────────────────
    def obter_serie_chuva(self, codigo_estacao: str, ano_inicio: int, ano_fim: int,
                          progresso=None, pausa_seg: float = 0.25) -> pd.DataFrame:
        """
        Retorna a máxima anual de chuva diária (mm) por ano.

        A rota HidroSerieChuva devolve um registro por MÊS, com as chuvas diárias
        em colunas Chuva_01..Chuva_31 e a máxima diária do mês no campo 'Maxima'.
        A máxima anual é o maior valor de 'Maxima' entre os meses do ano.

        'progresso' (opcional) é chamado a cada ano como progresso(feito, total, ano),
        permitindo à interface exibir uma barra de andamento.
        """
        codigo_estacao = str(codigo_estacao).strip()
        todos_os_dados = []
        anos_ok = 0
        falhas = []
        total_anos = ano_fim - ano_inicio + 1

        # Uma requisição por ano civil: sempre abaixo do limite de 366 dias.
        # A pausa entre anos é adaptativa: começa curta e só recua quando a ANA
        # sinaliza limitação (erro transitório ou falha de conexão), evitando
        # esperas desnecessárias quando o serviço está respondendo bem.
        pausa = pausa_seg
        for indice, ano in enumerate(range(ano_inicio, ano_fim + 1)):
            params = {
                "Código da Estação": codigo_estacao,
                "Tipo Filtro Data": "DATA_LEITURA",
                "Data Inicial (yyyy-MM-dd)": f"{ano}-01-01",
                "Data Final (yyyy-MM-dd)": f"{ano}-12-31",
            }
            try:
                res = self._get("/HidroSerieChuva/v1", params=params, timeout=180)
                if res.status_code in (200, 404):
                    anos_ok += 1
                    pausa = pausa_seg  # resposta limpa → volta à pausa mínima
                    if res.status_code == 200:
                        todos_os_dados.extend(res.json().get("items") or [])
                else:
                    falhas.append(f"{ano}: HTTP {res.status_code} — {self._mensagem_erro(res)}")
                    pausa = min(pausa * 2, 3.0)  # sob limitação → recua
            except Exception as e:
                falhas.append(f"{ano}: {type(e).__name__}")
                pausa = min(pausa * 2, 3.0)

            if progresso is not None:
                try:
                    progresso(indice + 1, total_anos, ano)
                except Exception:
                    pass

            # Nenhuma pausa após o último ano — não há próxima requisição.
            if indice < total_anos - 1:
                time.sleep(pausa)

        if falhas:
            logger.warning("Períodos com falha na ANA: " + "; ".join(falhas[:5]))

        df = pd.DataFrame(todos_os_dados)
        if df.empty:
            # Se a maioria dos anos falhou por indisponibilidade, o problema foi de
            # comunicação (não ausência de dados) — a mensagem precisa refletir isso.
            if falhas and anos_ok < total_anos / 2:
                raise ValueError(
                    f"A ANA está indisponível ou limitando as requisições: {len(falhas)} de "
                    f"{total_anos} períodos falharam (ex.: {falhas[0]}). Aguarde alguns minutos "
                    f"e tente novamente, de preferência com um intervalo de anos menor."
                )
            raise ValueError(
                f"A estação {codigo_estacao} não possui dados de chuva na base telemétrica da "
                f"ANA entre {ano_inicio} e {ano_fim}. Verifique o código ou tente outro período."
            )

        df["Data_Calc"] = pd.to_datetime(df["Data_Hora_Dado"], errors="coerce")
        df["Ano"] = df["Data_Calc"].dt.year
        df["Maxima_mm"] = pd.to_numeric(df["Maxima"], errors="coerce")
        df["Consistencia"] = pd.to_numeric(df.get("Nivel_Consistencia"), errors="coerce").fillna(0)

        # O mesmo mês pode vir em bruto (1) e consistido (2). Descartar os meses sem
        # máxima ANTES de deduplicar é essencial: quando a ANA consiste o total do mês
        # mas não a máxima diária (Maxima nula, MaximaStatus=0), o registro consistido
        # não pode eliminar o bruto — senão a máxima do ano seria perdida.
        df = (df.dropna(subset=["Data_Calc", "Maxima_mm"])
                .sort_values("Consistencia")
                .drop_duplicates(subset=["Data_Calc"], keep="last"))

        df_max_anual = (df.groupby("Ano")["Maxima_mm"].max()
                          .reset_index()
                          .rename(columns={"Maxima_mm": "Precipitacao"}))

        if df_max_anual.empty:
            raise ValueError(
                f"A estação {codigo_estacao} retornou registros, mas sem valores de máxima "
                f"diária utilizáveis entre {ano_inicio} e {ano_fim}."
            )

        logger.info(f"✅ Série obtida: {len(df_max_anual)} anos para a estação {codigo_estacao}")
        return df_max_anual.sort_values("Ano").reset_index(drop=True)


# ── Série histórica (webservice legado, estações convencionais) ───────────────
#
# O serviço ServiceANA.asmx/HidroSerieHistorica é público (sem autenticação) e
# devolve toda a série da estação numa ÚNICA requisição — é a mesma fonte usada
# pelos downloads do site HidroWeb. Serve estações convencionais, cujas séries
# longas são as adequadas para curvas IDF. Não tem o limite de 366 dias da API
# telemétrica, portanto dispensa o laço ano-a-ano (muito mais rápido).
SERIE_HISTORICA_URL = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroSerieHistorica"


def _localname(tag: str) -> str:
    """Nome da tag sem o namespace XML (ex.: '{http://x}Chuva01' → 'Chuva01')."""
    return tag.rsplit("}", 1)[-1]


def _num_ptbr(valor) -> float:
    """Converte texto numérico da ANA para float, aceitando vírgula decimal."""
    if valor is None:
        return float("nan")
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return float("nan")


def obter_serie_chuva_historica(codigo_estacao: str, ano_inicio: int = None,
                                ano_fim: int = None, progresso=None,
                                timeout: int = 180) -> pd.DataFrame:
    """
    Retorna a máxima anual de chuva diária (mm) via webservice histórico da ANA.

    Diferente da API telemétrica (uma requisição por ano, com token), esta rota
    devolve toda a série da estação de uma vez e sem autenticação. Cada registro
    do XML é um MÊS, com as chuvas diárias em Chuva01..Chuva31; a máxima do mês é
    o maior valor diário, e a máxima anual é o maior valor mensal do ano.

    'progresso' (opcional) é chamado uma vez ao concluir, para compatibilidade
    com a interface (aqui só há uma requisição, então não há andamento por ano).
    """
    codigo_estacao = str(codigo_estacao).strip()
    params = {
        "codEstacao": codigo_estacao,
        "dataInicio": f"01/01/{ano_inicio}" if ano_inicio else "",
        "dataFim": f"31/12/{ano_fim}" if ano_fim else "",
        "tipoDados": "2",          # 2 = chuva
        "nivelConsistencia": "",   # vazio = bruto e consistido
    }

    # Retry simples para erros de conexão/indisponibilidade transitória.
    res = None
    for tentativa in range(4):
        try:
            res = requests.get(SERIE_HISTORICA_URL, params=params, timeout=timeout)
        except requests.RequestException as e:
            if tentativa == 3:
                raise ValueError(f"Falha de conexão com o webservice histórico da ANA: {e}")
            time.sleep(2 ** tentativa)
            continue
        if res.status_code == 200:
            break
        if res.status_code >= 500 and tentativa < 3:
            time.sleep(2 ** tentativa)
            continue
        res.raise_for_status()

    try:
        root = ET.fromstring(res.content)
    except ET.ParseError as e:
        raise ValueError(f"Resposta inválida do webservice histórico da ANA: {e}")

    # A ANA sinaliza ausência de dados numa tabela <Error>…</Error>.
    for el in root.iter():
        if _localname(el.tag) == "Error" and (el.text or "").strip():
            return pd.DataFrame(columns=["Ano", "Precipitacao"])

    registros = [el for el in root.iter() if _localname(el.tag) == "SerieHistorica"]
    if not registros:
        return pd.DataFrame(columns=["Ano", "Precipitacao"])

    # Um registro por mês: extrai (mês, nível de consistência, máxima diária do mês).
    linhas = []
    for reg in registros:
        campos = {_localname(f.tag): (f.text or "") for f in reg}
        data_mes = pd.to_datetime(campos.get("DataHora"), errors="coerce")
        if pd.isna(data_mes):
            continue
        nivel = _num_ptbr(campos.get("NivelConsistencia"))
        nivel = 0 if np.isnan(nivel) else nivel

        # Máxima do mês: maior das chuvas diárias; se ausentes, usa o campo 'Maxima'.
        diarias = [_num_ptbr(campos.get(f"Chuva{d:02d}")) for d in range(1, 32)]
        diarias_validas = [v for v in diarias if np.isfinite(v) and v >= 0]
        n_dias_mes = len(diarias_validas)
        if diarias_validas:
            max_mes = max(diarias_validas)
        else:
            max_mes = _num_ptbr(campos.get("Maxima"))
            n_dias_mes = 30 if np.isfinite(max_mes) else 0
        if not np.isfinite(max_mes):
            continue

        linhas.append({
            "DataHora": data_mes,
            "Consistencia": nivel,
            "Maxima_mm": max_mes,
            "DiasValidos": n_dias_mes,
        })

    df = pd.DataFrame(linhas)
    if df.empty:
        raise ValueError(
            f"A estação {codigo_estacao} retornou registros, mas sem máximas diárias "
            f"utilizáveis na base histórica da ANA."
        )

    # O mesmo mês pode vir em bruto (1) e consistido (2): mantém o de maior nível.
    df = (df.sort_values("Consistencia")
            .drop_duplicates(subset=["DataHora"], keep="last"))
    df["Ano"] = df["DataHora"].dt.year

    if ano_inicio is not None:
        df = df[df["Ano"] >= ano_inicio]
    if ano_fim is not None:
        df = df[df["Ano"] <= ano_fim]

    df_max_anual = (df.groupby("Ano").agg(
        Precipitacao=("Maxima_mm", "max"),
        DiasValidos=("DiasValidos", "sum"),
        MesesValidos=("DataHora", "count"),
    ).reset_index())

    if df_max_anual.empty:
        raise ValueError(
            f"A estação {codigo_estacao} não possui máximas de chuva no período "
            f"{ano_inicio or '—'}–{ano_fim or '—'} na base histórica da ANA."
        )

    if progresso is not None:
        try:
            progresso(1, 1, int(df_max_anual["Ano"].max()))
        except Exception:
            pass

    logger.info(
        f"✅ Série histórica obtida: {len(df_max_anual)} anos para a estação {codigo_estacao} "
        f"(webservice legado, sem autenticação)."
    )
    return df_max_anual.sort_values("Ano").reset_index(drop=True)


# Sigla da UF → nome do estado em maiúsculas, como o inventário legado espera.
UF_PARA_NOME = {
    'AC': 'ACRE', 'AL': 'ALAGOAS', 'AP': 'AMAPÁ', 'AM': 'AMAZONAS', 'BA': 'BAHIA',
    'CE': 'CEARÁ', 'DF': 'DISTRITO FEDERAL', 'ES': 'ESPÍRITO SANTO', 'GO': 'GOIÁS',
    'MA': 'MARANHÃO', 'MT': 'MATO GROSSO', 'MS': 'MATO GROSSO DO SUL', 'MG': 'MINAS GERAIS',
    'PA': 'PARÁ', 'PB': 'PARAÍBA', 'PR': 'PARANÁ', 'PE': 'PERNAMBUCO', 'PI': 'PIAUÍ',
    'RJ': 'RIO DE JANEIRO', 'RN': 'RIO GRANDE DO NORTE', 'RS': 'RIO GRANDE DO SUL',
    'RO': 'RONDÔNIA', 'RR': 'RORAIMA', 'SC': 'SANTA CATARINA', 'SP': 'SÃO PAULO',
    'SE': 'SERGIPE', 'TO': 'TOCANTINS',
}

HIDRO_INVENTARIO_URL = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroInventario"


def listar_estacoes_historicas(uf: str, timeout: int = 120) -> list:
    """
    Lista estações pluviométricas de uma UF pelo inventário legado da ANA
    (ServiceANA.asmx/HidroInventario), sem autenticação.

    Retorna [{'codigo': str, 'nome': str}, ...] ordenado por nome — mesmo formato
    de AnaHidroWebService.listar_estacoes_por_uf, para uso intercambiável na UI.
    """
    nome_estado = UF_PARA_NOME.get(str(uf).strip().upper())
    if not nome_estado:
        logger.error(f"UF sem mapeamento para nome de estado: {uf!r}")
        return []

    params = {
        "codEstDE": "", "codEstATE": "", "tpEst": "2",   # 2 = pluviométrica
        "nmEst": "", "nmRio": "", "codSubBacia": "", "codBacia": "",
        "nmMunicipio": "", "nmEstado": nome_estado, "sgResp": "", "sgOper": "",
        "telemetrica": "",
    }
    try:
        res = requests.get(HIDRO_INVENTARIO_URL, params=params, timeout=timeout)
        res.raise_for_status()
        root = ET.fromstring(res.content)
    except (requests.RequestException, ET.ParseError) as e:
        logger.error(f"Erro ao listar estações históricas de {uf}: {e}")
        return []

    lista = []
    for tab in root.iter():
        if _localname(tab.tag) != "Table":
            continue
        campos = {_localname(f.tag): (f.text or "") for f in tab}
        cod = (campos.get("Codigo") or "").strip()
        if not cod:
            continue
        lat = _num_ptbr(campos.get("Latitude"))
        lon = _num_ptbr(campos.get("Longitude"))
        alt = _num_ptbr(campos.get("Altitude"))
        p_ini = (campos.get("PeriodoPluviometroInicio") or campos.get("PeriodoRegistradorChuvaInicio") or "")[:10]
        p_fim = (campos.get("PeriodoPluviometroFim") or campos.get("PeriodoRegistradorChuvaFim") or "")[:10]
        ano_ini = p_ini[:4] if len(p_ini) >= 4 else ""
        ano_fim = p_fim[:4] if len(p_fim) >= 4 else ""
        if ano_ini and ano_fim:
            periodo_op = f"{ano_ini}–{ano_fim}"
            try:
                n_anos_op = int(ano_fim) - int(ano_ini) + 1
            except Exception:
                n_anos_op = None
        else:
            periodo_op = "—"
            n_anos_op = None

        operadora = (campos.get("OperadoraSigla") or campos.get("ResponsavelSigla") or "").strip()
        operando = (campos.get("Operando") or "").strip()
        status_op = "Ativa" if operando in ("1", "true", "True") else "Inativa"

        lista.append({
            "codigo": cod,
            "nome": (campos.get("Nome") or "Desconhecida").strip(),
            "latitude": lat if np.isfinite(lat) else None,
            "longitude": lon if np.isfinite(lon) else None,
            "altitude": alt if np.isfinite(alt) else None,
            "municipio": (campos.get("nmMunicipio") or "").strip(),
            "rio": (campos.get("nmRio") or "").strip(),
            "operando": operando,
            "status_operando": status_op,
            "periodo_inicio": p_ini,
            "periodo_fim": p_fim,
            "periodo_operacao": periodo_op,
            "anos_operacao": n_anos_op,
            "operadora": operadora,
        })

    logger.info(f"✅ Inventário legado: {len(lista)} estações pluviométricas em {uf}")
    return sorted(lista, key=lambda x: x["nome"])


# ── Funções Geoespaciais e Interpolação IDW ───────────────────────────────────

def calcular_distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância geodésica em km entre dois pares de coordenadas (Haversine)."""
    R = 6371.0  # Raio médio da Terra em km
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0)**2
    return float(R * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a)))


def filtrar_estacoes_por_raio(
    lat_ref: float,
    lon_ref: float,
    estacoes: list[dict],
    raio_km: float = 50.0,
) -> list[dict]:
    """
    Calcula a distância de cada estação ao ponto (lat_ref, lon_ref) e retorna
    aquelas situadas até raio_km, ordenadas da mais próxima à mais distante.
    Adiciona o campo 'distancia_km' em cada estação retornada.
    """
    resultado = []
    for e in estacoes:
        lat = e.get("latitude")
        lon = e.get("longitude")
        if lat is None or lon is None or not (np.isfinite(lat) and np.isfinite(lon)):
            continue
        # Filtro de sanidade geográfica no território brasileiro e fronteiras
        if not (-35.0 <= lat <= 6.0 and -75.0 <= lon <= -30.0):
            continue
        dist = calcular_distancia_km(lat_ref, lon_ref, lat, lon)
        if dist <= raio_km:
            item = dict(e)
            item["distancia_km"] = round(dist, 2)
            resultado.append(item)

    return sorted(resultado, key=lambda x: x["distancia_km"])


def interpolar_series_idw(
    series_dict: dict[str, pd.DataFrame],
    distancias_km: dict[str, float],
    p: float = 2.0,
    lang: str = 'PT',
) -> tuple[pd.DataFrame, dict[str, float], float, list[str]]:
    """
    Interpola séries históricas de precipitação máxima diária anual de múltiplas estações
    utilizando Inverse Distance Weighting (IDW):
      w_i = (1 / d_i^p) / sum(1 / d_k^p)

    Parâmetros:
    - series_dict: dict mapeando {cod_estacao: DataFrame com ['Ano', 'Precipitacao', ...]}
    - distancias_km: dict {cod_estacao: distancia_km}
    - p: expoente de distância (padrão 2.0)
    - lang: idioma para rótulos ('PT' ou 'EN')

    Retorna:
    - df_ponderado: DataFrame ['Ano', 'Data', 'Precipitacao', 'Origem', 'DiasValidos', 'MesesValidos']
    - pesos_globais: dict {cod_estacao: peso_percentual_global}
    - n_eff: número efetivo de estações (1 / sum(w_i^2))
    - avisos_idw: lista de alertas hidrológicos (ex: pesos residuais < 2%, co-localização)
    """
    if not series_dict:
        raise UserError("Nenhuma série de chuva disponível para interpolação.")

    estacoes = [cod for cod, df in series_dict.items() if df is not None and not df.empty]
    if not estacoes:
        raise UserError("As estações selecionadas não retornaram dados de chuva para interpolação.")

    avisos_idw = []

    # Se apenas 1 estação válida
    if len(estacoes) == 1:
        cod = estacoes[0]
        df_single = series_dict[cod].copy()
        if 'Precipitacao' not in df_single.columns and t('col_precip', lang) in df_single.columns:
            df_single['Precipitacao'] = df_single[t('col_precip', lang)]
        if 'Ano' not in df_single.columns and t('col_ano', lang) in df_single.columns:
            df_single['Ano'] = df_single[t('col_ano', lang)]
        df_single[t('col_data', lang)] = df_single.get('Data', df_single.get(t('col_data', lang), "—"))
        df_single[t('col_origem', lang)] = f"Estação {cod}"
        return df_single, {cod: 1.0}, 1.0, avisos_idw

    # Se alguma estação estiver no ponto exato (distância < 100m), usa 100% dela
    for cod in estacoes:
        if distancias_km.get(cod, 10.0) < 0.1:
            df_single = series_dict[cod].copy()
            df_single[t('col_data', lang)] = df_single.get('Data', df_single.get(t('col_data', lang), "—"))
            df_single[t('col_origem', lang)] = f"Estação {cod} (Co-localizada)"
            return df_single, {cod: 1.0}, 1.0, avisos_idw

    # Pesos globais nominais
    inv_dists = {cod: (1.0 / max(distancias_km.get(cod, 1.0), 0.1)) ** p for cod in estacoes}
    soma_inv = sum(inv_dists.values())
    pesos_globais = {cod: round(inv_dists[cod] / soma_inv, 4) for cod in estacoes}

    # Número efetivo de estações N_eff = 1 / sum(w_i^2)
    sum_sq_w = sum(w ** 2 for w in pesos_globais.values())
    n_eff = round(float(1.0 / sum_sq_w), 2) if sum_sq_w > 0 else 1.0

    # Alertas diagnósticos de IDW
    for cod, w in pesos_globais.items():
        if w < 0.02:
            avisos_idw.append(t('idw_weight_alert', lang).format(cod, w * 100.0))

    # Checagem de co-localização / arranjo degenerado
    colocadas = False
    if len(estacoes) >= 3 and n_eff < 2.0:
        colocadas = True
    elif len(estacoes) >= 2:
        relevantes = [c for c in estacoes if pesos_globais.get(c, 0) >= 0.02]
        dists_rel = [distancias_km.get(c, 999.0) for c in relevantes]
        for i in range(len(dists_rel)):
            for j in range(i + 1, len(dists_rel)):
                if abs(dists_rel[i] - dists_rel[j]) < 2.0 and min(dists_rel[i], dists_rel[j]) < 3.0:
                    colocadas = True
                    break
            if colocadas:
                break

    if colocadas:
        avisos_idw.append(t('idw_colocated_alert', lang).format(n_eff))

    # Interpola ano a ano considerando as estações que possuem dado em cada ano
    anos_por_estacao = {}
    for cod in estacoes:
        df_cod = series_dict[cod]
        ano_col = 'Ano' if 'Ano' in df_cod.columns else t('col_ano', lang)
        anos_por_estacao[cod] = set(df_cod[ano_col].dropna().astype(int))

    todos_anos = sorted(set.union(*anos_por_estacao.values()))

    linhas = []
    for ano in todos_anos:
        estacoes_no_ano = [cod for cod in estacoes if ano in anos_por_estacao[cod]]
        if not estacoes_no_ano:
            continue

        # Re-normaliza pesos para o subconjunto de estações disponíveis no ano
        inv_sub = {cod: inv_dists[cod] for cod in estacoes_no_ano}
        soma_sub = sum(inv_sub.values())

        p_ponderada = 0.0
        dias_ponderados = 0.0
        meses_ponderados = 0.0
        tem_dias = False

        for cod in estacoes_no_ano:
            w = inv_sub[cod] / soma_sub
            df_cod = series_dict[cod]
            p_col = 'Precipitacao' if 'Precipitacao' in df_cod.columns else t('col_precip', lang)
            ano_col = 'Ano' if 'Ano' in df_cod.columns else t('col_ano', lang)

            val = float(df_cod.loc[df_cod[ano_col] == ano, p_col].values[0])
            p_ponderada += w * val

            if 'DiasValidos' in df_cod.columns:
                dv_row = df_cod.loc[df_cod[ano_col] == ano, 'DiasValidos'].values
                if len(dv_row) > 0 and np.isfinite(dv_row[0]):
                    dias_ponderados += w * float(dv_row[0])
                    tem_dias = True
            if 'MesesValidos' in df_cod.columns:
                mv_row = df_cod.loc[df_cod[ano_col] == ano, 'MesesValidos'].values
                if len(mv_row) > 0 and np.isfinite(mv_row[0]):
                    meses_ponderados += w * float(mv_row[0])

        linha = {
            "Ano": int(ano),
            t('col_ano', lang): int(ano),
            "Precipitacao": round(p_ponderada, 2),
            t('col_precip', lang): round(p_ponderada, 2),
            "Data": t('val_idw_origin', lang),
            t('col_data', lang): t('val_idw_origin', lang),
            t('col_origem', lang): t('val_idw_origin', lang),
        }
        if tem_dias:
            linha["DiasValidos"] = int(round(dias_ponderados))
        if meses_ponderados > 0:
            linha["MesesValidos"] = int(round(meses_ponderados))

        linhas.append(linha)

    df_ponderado = pd.DataFrame(linhas).sort_values("Ano").reset_index(drop=True)
    if df_ponderado.empty:
        raise UserError("Não foi possível gerar a série interpolada (sem registros coincidentes).")

    return df_ponderado, pesos_globais, n_eff, avisos_idw


# ── Core Calculations ─────────────────────────────────────────────────────────

def get_gumbel_constants(n: int) -> tuple[float, float]:
    """
    Interpolate Gumbel constants (Yn, sn) for a given sample size N.
    Uses linear interpolation between known table values.
    """
    sizes = sorted(GUMBEL_CONSTANTS.keys())

    # Clamp to table range
    if n <= sizes[0]:
        return GUMBEL_CONSTANTS[sizes[0]]
    if n >= sizes[-1]:
        return GUMBEL_CONSTANTS[sizes[-1]]

    # Linear interpolation
    for i in range(len(sizes) - 1):
        n1, n2 = sizes[i], sizes[i + 1]
        if n1 <= n <= n2:
            yn1, sn1 = GUMBEL_CONSTANTS[n1]
            yn2, sn2 = GUMBEL_CONSTANTS[n2]
            frac = (n - n1) / (n2 - n1)
            yn = yn1 + frac * (yn2 - yn1)
            sn = sn1 + frac * (sn2 - sn1)
            return yn, sn

    return GUMBEL_CONSTANTS[sizes[-1]]


def parse_station_code(file_bytes: bytes) -> str | None:
    """
    Extract the station code (EstacaoCodigo) from the first data row of an ANA/HidroWeb CSV.
    Returns the station code as a string, or None if not found.
    """
    for enc in ('latin-1', 'utf-8', 'cp1252'):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    lines = text.splitlines()
    header_idx = None
    detected_sep = ';'

    # Find the real header line (same logic as parse_ana_file)
    REAL_HEADER_MARKERS = {'estacaocodigo', 'estacao', 'data', 'maxima', 'total'}
    for i, line in enumerate(lines):
        parts_lower = [p.strip().lower().strip('"') for p in line.split(';')]
        if len(parts_lower) >= 4:
            matched = sum(1 for p in parts_lower if p in REAL_HEADER_MARKERS)
            if matched >= 2:
                header_idx = i
                break
    if header_idx is None:
        for i, line in enumerate(lines):
            if len(line.split(';')) >= 5:
                header_idx = i
                break
    if header_idx is None:
        return None

    header_parts = [p.strip().strip('"') for p in lines[header_idx].split(detected_sep)]
    # Find the EstacaoCodigo column index
    station_col_idx = None
    for idx, col in enumerate(header_parts):
        if col.lower().strip() in ('estacaocodigo', 'estacao', 'codigo', 'cod_estacao'):
            station_col_idx = idx
            break

    if station_col_idx is None:
        return None

    # Read the first data row after the header
    for line in lines[header_idx + 1:]:
        parts = [p.strip().strip('"') for p in line.split(detected_sep)]
        if len(parts) > station_col_idx and parts[station_col_idx].strip():
            code = parts[station_col_idx].strip()
            logger.info(f"🏷️ Código de estação extraído do CSV: {code}")
            return code

    return None


def parse_ana_file(file_bytes: bytes, lang: str = 'PT') -> pd.DataFrame:
    """
    Parse ANA/HidroWeb CSV or TXT file.
    Identifies columns containing 'data' and 'chuva'/'maxima'/'valor'.
    Returns DataFrame with columns: [Year, Date, MaxPrecip].
    """
    # Try different encodings
    for enc in ('latin-1', 'utf-8', 'cp1252'):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Não foi possível decodificar o arquivo. Verifique a codificação.")

    logger.info(f"📄 Arquivo ANA decodificado com sucesso. Primeiros 300 chars: {text[:300]}")

    REAL_HEADER_MARKERS = {'estacaocodigo', 'estacao', 'data', 'maxima', 'total'}

    lines = text.splitlines()
    skiprows = 0
    detected_sep = ';'
    found = False

    # Pass 1: find a line whose semicolon-split fields contain ≥2 known markers
    for i, line in enumerate(lines):
        parts_lower = [p.strip().lower().strip('"') for p in line.split(';')]
        if len(parts_lower) >= 4:
            matched = sum(1 for p in parts_lower if p in REAL_HEADER_MARKERS)
            if matched >= 2:
                skiprows = i
                detected_sep = ';'
                logger.info(f"📌 Cabeçalho real encontrado na linha {i}: '{line[:120]}'")
                found = True
                break

    # Pass 2 fallback: first line with ≥5 semicolon-separated fields
    if not found:
        for i, line in enumerate(lines):
            if len(line.split(';')) >= 5:
                skiprows = i
                detected_sep = ';'
                logger.info(f"📌 Cabeçalho (fallback ≥5 cols) na linha {i}: '{line[:120]}'")
                found = True
                break

    # Re-parse from the detected header row; quotechar handles "55,0" style values
    df_raw = pd.read_csv(
        io.StringIO(text),
        sep=detected_sep,
        skiprows=skiprows,
        encoding='utf-8',
        on_bad_lines='skip',
        quotechar='"',
    )

    logger.info(f"📊 Colunas encontradas: {df_raw.columns.tolist()}")
    logger.info(f"📐 Shape: {df_raw.shape}")

    # Normalize column names for matching
    cols_lower = {col: col.lower().strip() for col in df_raw.columns}

    # Find date column — prefer exact 'data' match first, then partial
    date_col = None
    for col, col_l in cols_lower.items():
        if col_l in ('data', 'date', 'ano'):
            date_col = col
            break
    if date_col is None:
        for col, col_l in cols_lower.items():
            if 'data' in col_l or 'date' in col_l:
                date_col = col
                break

    # Find precipitation column — priority order: Maxima > Chuva > Precip > Valor
    precip_col = None
    priority_exact = ('maxima', 'máxima', 'chuvamax', 'precipmax')
    priority_partial = ('maxima', 'máxima', 'precip', 'mm')
    exclude_kw = ('status', 'tipo', 'nivel', 'codigo', 'codigo', 'numdia', 'diamax', 'total', 'anual')

    for col, col_l in cols_lower.items():
        if col_l in priority_exact:
            precip_col = col
            break
    if precip_col is None:
        for col, col_l in cols_lower.items():
            if any(kw in col_l for kw in priority_partial) and not any(ex in col_l for ex in exclude_kw):
                precip_col = col
                break
    # Last resort: 'chuva' anywhere but not a daily column (Chuva01..Chuva31)
    if precip_col is None:
        for col, col_l in cols_lower.items():
            if 'chuva' in col_l and not any(col_l.endswith(str(d).zfill(2)) for d in range(1, 32)):
                precip_col = col
                break

    # Fallback: use first two columns
    if date_col is None:
        date_col = df_raw.columns[0]
        logger.warning(f"⚠️ Coluna de data não encontrada, usando: {date_col}")
    if precip_col is None:
        precip_col = df_raw.columns[1] if df_raw.shape[1] > 1 else df_raw.columns[0]
        logger.warning(f"⚠️ Coluna de precipitação não encontrada, usando: {precip_col}")

    logger.info(f"✅ Coluna data: '{date_col}', Coluna precipitação: '{precip_col}'")

    df = df_raw[[date_col, precip_col]].copy()
    df.columns = ['Date', 'Precip']

    # Convert precipitation to numeric.
    df['Precip'] = (
        df['Precip']
        .astype(str)
        .str.strip()
        .str.strip('"')
        .str.replace(',', '.', regex=False)
    )
    df['Precip'] = pd.to_numeric(df['Precip'], errors='coerce')
    df = df.dropna(subset=['Precip'])
    df = df[df['Precip'] > 0]  # exclude zero/missing months

    # Parse dates
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['Date'])
    df['Year'] = df['Date'].dt.year

    # Group by year: take the row of the maximum daily precipitation per year.
    # idxmax mantém a data do evento e independe da versão do pandas (a partir do
    # pandas 3.0 o groupby.apply não devolve mais a coluna de agrupamento).
    idx_max = df.groupby('Year')['Precip'].idxmax()
    annual = df.loc[idx_max, ['Year', 'Date', 'Precip']].copy()
    annual.columns = [t('col_ano', lang), t('col_data', lang), t('col_precip', lang)]
    annual = annual.sort_values(t('col_ano', lang)).reset_index(drop=True)

    logger.info(f"📅 Série histórica: {len(annual)} anos, de {annual[t('col_ano', lang)].min()} a {annual[t('col_ano', lang)].max()}")
    return annual


def parse_manual_data(text: str, lang: str = 'PT') -> pd.DataFrame:
    """
    Parse manually entered rainfall data (one value per line).
    Returns DataFrame with columns: [Ano, Data, Precipitação Máxima (mm)].
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    values = []
    for line in lines:
        # Replace comma decimal separator
        line = line.replace(',', '.')
        try:
            val = float(line.split()[0])  # Take first token
            if val >= 0:
                values.append(val)
        except (ValueError, IndexError):
            continue

    if not values:
        raise ValueError("Nenhum valor numérico válido encontrado nos dados manuais.")

    logger.info(f"📝 Dados manuais: {len(values)} valores lidos")

    # Assign sequential years starting from current year minus N
    import datetime
    current_year = datetime.date.today().year
    start_year = current_year - len(values)
    years = list(range(start_year, start_year + len(values)))

    df = pd.DataFrame({
        t('col_ano', lang): years,
        t('col_data', lang): ["—" for _ in years],  # Sem data falsa AAAA-01-01
        t('col_precip', lang): values,
        t('col_origem', lang): ["Manual" for _ in years],
        "Ano": years,
        "Precipitacao": values,
        "Data": ["—" for _ in years],
    })
    return df


def gumbel_analysis(series: pd.DataFrame, lang: str = 'PT') -> tuple[pd.DataFrame, float, float, int]:
    """
    Perform Gumbel probabilistic analysis.
    Returns (result_df, mu, sigma, n).
    """
    precip_col = t('col_precip', lang)
    if precip_col not in series.columns:
        for c in ('Precipitacao', 'precipitacao', 'Precip', 'precip', 'Chuva', 'chuva'):
            if c in series.columns:
                precip_col = c
                break
    data = series[precip_col].dropna().values
    n = len(data)
    mu = float(np.mean(data))
    sigma = float(np.std(data, ddof=1)) if n > 1 else 0.0

    logger.info(f"📊 Gumbel: N={n}, μ={mu:.3f}, σ={sigma:.3f}")

    if n < 10:
        logger.warning("⚠️ Tamanho amostral N < 10: resultados estatísticos podem ser pouco confiáveis.")

    yn, sn = get_gumbel_constants(n)
    logger.info(f"📐 Constantes Gumbel: Yn={yn:.4f}, Sn={sn:.4f}")

    rows = []
    for tr in RETURN_PERIODS:
        prob_exceedance = 1.0 - (1.0 / tr)   # non-exceedance probability F = 1 - 1/TR
        y = -np.log(-np.log(prob_exceedance))
        kt = (y - yn) / sn
        pt = mu + sigma * kt
        rows.append({
            t('col_tr', lang): tr,
            t('col_y', lang): round(float(y), 4),
            t('col_kt', lang): round(float(kt), 4),
            t('col_pt', lang): round(float(pt), 3),
        })

    result = pd.DataFrame(rows)
    logger.info(f"✅ Análise de Gumbel concluída: {result.to_dict('records')}")
    return result, mu, sigma, n


def analisar_qualidade_serie(
    series_df: pd.DataFrame,
    limiar_cobertura_pct: float = 90.0,
    excluir_incompletos: bool = True,
    lang: str = 'PT',
) -> dict:
    """
    Painel de diagnóstico hidrológico e qualidade da série histórica pré-Gumbel.
    Avalia:
      1. Cobertura de dias válidos por ano civil (com opção de descarte e registro).
      2. Coeficiente de Variação (CV = σ/μ) com alertas de plausibilidade regional.
      3. Teste de tendência e estacionariedade de Mann-Kendall.
      4. Testes de detecção de outliers (Grubbs e Chauvenet).
    """
    col_p = t('col_precip', lang)
    if col_p not in series_df.columns:
        for c in ('Precipitacao', 'precipitacao', 'Precip', 'precip'):
            if c in series_df.columns:
                col_p = c
                break

    col_a = t('col_ano', lang)
    if col_a not in series_df.columns:
        for c in ('Ano', 'ano', 'Year', 'year'):
            if c in series_df.columns:
                col_a = c
                break

    anos_descartados = []
    tem_dias_validos = 'DiasValidos' in series_df.columns

    if tem_dias_validos and limiar_cobertura_pct > 0:
        for _, row in series_df.iterrows():
            ano = int(row[col_a])
            val = float(row[col_p])
            dv = float(row['DiasValidos'])
            dias_ano = 366.0 if calendar.isleap(ano) else 365.0
            cob = min(100.0, (dv / dias_ano) * 100.0)
            if cob < limiar_cobertura_pct:
                anos_descartados.append({
                    'ano': ano,
                    'valor': val,
                    'dias_validos': int(round(dv)),
                    'cobertura_pct': round(cob, 1),
                    'motivo': (
                        f"Cobertura de {int(round(dv))} dias válidos ({cob:.1f}%) "
                        f"abaixo do limiar de {limiar_cobertura_pct:.0f}%"
                    ),
                })

    if excluir_incompletos and anos_descartados:
        descartados_set = {d['ano'] for d in anos_descartados}
        df_limpo = series_df[~series_df[col_a].isin(descartados_set)].copy().reset_index(drop=True)
    else:
        df_limpo = series_df.copy().reset_index(drop=True)

    y = df_limpo[col_p].dropna().values
    n = len(y)
    mu = float(np.mean(y)) if n > 0 else 0.0
    sigma = float(np.std(y, ddof=1)) if n > 1 else 0.0
    cv = float(sigma / mu) if mu > 0 else 0.0

    cv_status = 'ok' if (0.15 <= cv <= 0.30) else 'alert'
    cv_msg = t('diag_cv_ok', lang).format(cv) if cv_status == 'ok' else t('diag_cv_alert', lang).format(cv)

    # Teste de Mann-Kendall
    anos_limpos = df_limpo[col_a].values
    if n >= 4:
        try:
            tau, p_val = kendalltau(anos_limpos, y)
            tau = 0.0 if np.isnan(tau) else float(tau)
            p_val = 1.0 if np.isnan(p_val) else float(p_val)
            mk_trend = bool(p_val < 0.05)
            mk_msg = t('diag_mk_trend', lang).format(tau, p_val) if mk_trend else t('diag_mk_no_trend', lang).format(tau, p_val)
        except Exception as e:
            tau, p_val, mk_trend, mk_msg = 0.0, 1.0, False, f"Erro Mann-Kendall: {e}"
    else:
        tau, p_val, mk_trend, mk_msg = 0.0, 1.0, False, "Série insuficiente para Mann-Kendall."

    # Teste de Outliers (Grubbs e Chauvenet)
    outliers = []
    if n >= 4 and sigma > 0:
        try:
            t_crit = student_t.ppf(1.0 - 0.05 / (2.0 * n), n - 2)
            g_crit = ((n - 1) / np.sqrt(n)) * np.sqrt(t_crit**2 / (n - 2 + t_crit**2))
            for _, row in df_limpo.iterrows():
                val = float(row[col_p])
                ano = int(row[col_a])
                z = abs(val - mu) / sigma
                flagged = False
                teste_nome = ""
                if z > g_crit:
                    flagged = True
                    teste_nome = "Grubbs"
                p_c = 2.0 * (1.0 - student_t.cdf(z, n - 1))
                if p_c * n < 0.5:
                    flagged = True
                    teste_nome = "Grubbs / Chauvenet" if teste_nome else "Chauvenet"
                if flagged:
                    outliers.append({
                        'ano': ano,
                        'valor': val,
                        'z_score': round(z, 2),
                        'teste': teste_nome,
                        'msg': t('diag_outlier_found', lang).format(ano, val, teste_nome),
                    })
        except Exception as e:
            logger.warning(f"Erro no teste de outliers: {e}")

    return {
        'series_limpa': df_limpo,
        'anos_descartados': anos_descartados,
        'tem_dias_validos': tem_dias_validos,
        'n': n,
        'mu': mu,
        'sigma': sigma,
        'cv': round(cv, 4),
        'cv_status': cv_status,
        'cv_msg': cv_msg,
        'mann_kendall': {
            'tau': round(tau, 4),
            'p_value': round(p_val, 4),
            'trend': mk_trend,
            'msg': mk_msg,
        },
        'outliers': outliers,
    }


def _interpolate_rel6min(tr: int, isozona_data: dict) -> float:
    """Interpolate rel6min coefficient for a given TR."""
    r05_50 = isozona_data['rel6min']['05/50']
    r100 = isozona_data['rel6min']['100']
    if tr <= 50:
        return r05_50
    # Linear interpolation between TR=50 and TR=100
    frac = (tr - 50) / 50.0
    return r05_50 + frac * (r100 - r05_50)


def _interpolate_rel1h(tr: int, isozona_data: dict) -> float:
    """Interpolate rel1h coefficient for a given TR."""
    rel1h_table = isozona_data['rel1h']
    trs = sorted(rel1h_table.keys())
    if tr <= trs[0]:
        return rel1h_table[trs[0]]
    if tr >= trs[-1]:
        return rel1h_table[trs[-1]]
    for i in range(len(trs) - 1):
        t1, t2 = trs[i], trs[i + 1]
        if t1 <= tr <= t2:
            r1, r2 = rel1h_table[t1], rel1h_table[t2]
            frac = (tr - t1) / (t2 - t1)
            return r1 + frac * (r2 - r1)
    return rel1h_table[trs[-1]]


def disaggregate_rainfall(gumbel_df: pd.DataFrame, isozona: str, lang: str = 'PT') -> pd.DataFrame:
    """
    Disaggregate 1-day rainfall to sub-daily durations using Taborga Isozone method.
    Returns DataFrame: rows = durations, columns = TR values (precipitation in mm).
    """
    isozona_data = ISOZONA_CONSTANTS[isozona]
    sn_prime = 1.202

    rows = []
    for _, row in gumbel_df.iterrows():
        tr = int(row[t('col_tr', lang)])
        p1dia = row[t('col_pt', lang)]

        # Multiplier
        ap = p1dia * sn_prime

        # Coefficients for this TR
        rel6min = _interpolate_rel6min(tr, isozona_data)
        rel1h = _interpolate_rel1h(tr, isozona_data)

        precip_by_duration = {}
        for dur in DURATIONS:
            if dur <= 60:
                # Logarithmic interpolation between 6 min and 60 min
                p6  = ap * rel6min / 100.0
                p60 = ap * rel1h   / 100.0
                if dur == 6:
                    pt = p6
                elif dur == 60:
                    pt = p60
                else:
                    log_frac = np.log(dur / 6.0) / np.log(60.0 / 6.0)
                    pt = p6 + log_frac * (p60 - p6)
            else:
                # Logarithmic interpolation between 60 min and 1440 min
                p60   = ap * rel1h / 100.0
                p1440 = p1dia
                log_frac = np.log(dur / 60.0) / np.log(1440.0 / 60.0)
                pt = p60 + log_frac * (p1440 - p60)

            precip_by_duration[dur] = round(pt, 3)

        precip_by_duration['TR'] = tr
        rows.append(precip_by_duration)

    df = pd.DataFrame(rows).set_index('TR').T
    df.index.name = t('col_duracao', lang)
    df.columns = [f"{t('tr_col_prefix', lang)}{c}{t('tr_col_suffix', lang)}" for c in df.columns]
    logger.info(f"✅ Desagregação concluída. Shape: {df.shape}")
    return df


def compute_idf(disagg_df: pd.DataFrame, lang: str = 'PT') -> pd.DataFrame:
    """
    Convert precipitation (mm) to intensity (mm/h).
    i(t) = P(t) / (t / 60)
    Returns DataFrame with same structure as disagg_df but values in mm/h.
    """
    idf_df = disagg_df.copy()
    dur_name = t('col_duracao', lang)
    idf_df.index.name = dur_name
    for dur in DURATIONS:
        if dur in idf_df.index:
            idf_df.loc[dur] = disagg_df.loc[dur] / (dur / 60.0)
    logger.info("✅ Curvas IDF calculadas.")
    return idf_df


def verificar_consistencia_fisica_idf(
    idf_df: pd.DataFrame,
    sherman_params: dict,
    lang: str = 'PT',
) -> dict:
    """
    Asserções de consistência física sobre a matriz de intensidades da curva IDF
    e sobre os parâmetros ajustados de Sherman.
    Verifica:
      1. Monotonicidade temporal: para cada TR, i(t_{k+1}) < i(t_k) para t crescente.
      2. Monotonicidade de frequência: para cada duração t, i(TR_{j+1}) > i(TR_j).
      3. Plausibilidade hidrológica dos parâmetros ajustados B, C e D.
    """
    violacoes_tempo = []
    violacoes_freq = []
    violacoes_param = []
    mensagens = []

    # 1. Monotonicidade temporal
    for col in idf_df.columns:
        for k in range(len(DURATIONS) - 1):
            t1 = DURATIONS[k]
            t2 = DURATIONS[k + 1]
            if t1 in idf_df.index and t2 in idf_df.index:
                i1 = float(idf_df.loc[t1, col])
                i2 = float(idf_df.loc[t2, col])
                if i2 > i1 + 1e-4:
                    msg = t('phys_cons_time_viol', lang).format(col, t1, i1, t2, i2)
                    violacoes_tempo.append({'tr': col, 't1': t1, 'i1': i1, 't2': t2, 'i2': i2, 'msg': msg})
                    mensagens.append(msg)

    # 2. Monotonicidade de frequência
    tr_cols = idf_df.columns.tolist()
    for t_dur in DURATIONS:
        if t_dur in idf_df.index:
            for j in range(len(tr_cols) - 1):
                col1 = tr_cols[j]
                col2 = tr_cols[j + 1]
                i1 = float(idf_df.loc[t_dur, col1])
                i2 = float(idf_df.loc[t_dur, col2])
                if i2 < i1 - 1e-4:
                    msg = t('phys_cons_freq_viol', lang).format(t_dur, col1, i1, col2, i2)
                    violacoes_freq.append({'t': t_dur, 'tr1': col1, 'i1': i1, 'tr2': col2, 'i2': i2, 'msg': msg})
                    mensagens.append(msg)

    # 3. Limites de parâmetros de Sherman (comparados contra faixas típicas da literatura)
    for p_name in ('A', 'B', 'C', 'D'):
        val = sherman_params.get(p_name)
        if val is not None:
            low, high = SHERMAN_TYPICAL_RANGES[p_name]
            if not (low <= val <= high):
                low_str = f"{low:g}"
                high_str = f"{high:g}"
                msg = t('param_out_range', lang).format(p_name, val, low_str, high_str)
                violacoes_param.append({
                    'param': p_name,
                    'val': val,
                    'low': low,
                    'high': high,
                    'msg': msg,
                })
                mensagens.append(msg)

    for p_name, b_val in sherman_params.get('bounds_touched', []):
        msg = t('bound_touch_alert', lang).format(p_name, sherman_params.get(p_name, 0.0), b_val)
        mensagens.append(msg)

    is_valid = len(violacoes_tempo) == 0 and len(violacoes_freq) == 0 and len(violacoes_param) == 0
    status = 'OK' if is_valid else 'VIOLATION'
    return {
        'is_valid': is_valid,
        'status': status,
        'violacoes_tempo': violacoes_tempo,
        'violacoes_freq': violacoes_freq,
        'violacoes_param': violacoes_param,
        'mensagens': mensagens,
    }


def sherman_model(x_data: tuple, A: float, B: float, C: float, D: float) -> np.ndarray:
    """Sherman (Montana) equation: i(t, TR) = (A * TR^B) / (t + C)^D"""
    t, tr = x_data
    return (A * (tr ** B)) / ((t + C) ** D)


def sherman_log_model(x_data: tuple, ln_A: float, B: float, C: float, D: float) -> np.ndarray:
    """Sherman model in logarithmic space: ln(i) = ln(A) + B*ln(TR) - D*ln(t + C)"""
    t, tr = x_data
    return ln_A + B * np.log(tr) - D * np.log(t + C)


def compute_gumbel_memory(series_df: pd.DataFrame, lang: str = 'PT') -> dict:
    """
    Compute the full Gumbel memory-of-calculation following the Ven Te Chow method.

    Returns a dict with:
      - 'rows'      : list of dicts — one per data point (ordered table)
      - 'stats'     : dict of aggregate statistics (N, Pn, sigma, Yn, sn, sums)
      - 'chow_rows' : list of dicts — Ven Te Chow results per TR
    """
    precip_col = t('col_precip', lang)
    data_col   = t('col_data',   lang)
    ano_col    = t('col_ano',    lang)

    raw_values = series_df[precip_col].dropna().values.tolist()
    dates      = series_df[data_col].astype(str).tolist() if data_col in series_df.columns else \
                 series_df[ano_col].astype(str).tolist()
    n = len(raw_values)

    # ── Basic statistics ──────────────────────────────────────────────────────
    pn     = float(np.mean(raw_values))
    sigma  = float(np.std(raw_values, ddof=1))
    sum_p  = float(np.sum(raw_values))
    sum_ppn2 = float(np.sum([(p - pn) ** 2 for p in raw_values]))

    # ── Sorted (descending) values for ordered table ──────────────────────────
    sorted_vals = sorted(raw_values, reverse=True)

    # ── Compute Y for each rank m ─────────────────────────────────────────────
    sample_ys = []
    for m_idx, p_desc in enumerate(sorted_vals):
        m  = m_idx + 1
        pr = int(np.ceil(100 * (1 - m / (n - 1)))) if n > 1 else 0
        pr = max(0, min(pr, 100))
        tr_emp = (100 / (100 - pr)) if pr < 100 else 1000.0
        y_val  = float(-np.log(np.log(tr_emp / (tr_emp - 1)))) if tr_emp > 1 else 0.0
        sample_ys.append((m, p_desc, pr, tr_emp, y_val))

    # ── Yn and sn from non-zero Y values ─────────────────────────────────────
    non_zero_ys = [y for (_, _, _, _, y) in sample_ys if y != 0.0]
    yn_sample   = float(np.mean(non_zero_ys)) if non_zero_ys else 0.0
    sum_yyn2    = float(np.sum([(y - yn_sample) ** 2 for y in non_zero_ys]))
    sn_sample   = float(np.sqrt(sum_yyn2 / (n - 1))) if n > 1 else 0.0
    sum_y       = float(np.sum(non_zero_ys))

    # ── Build ordered rows (aligned with original series order for Date/Ano) ──
    orig_pairs = list(zip(dates, raw_values))  # original order for Date column

    rows = []
    for m_idx, (m, p_desc, pr, tr_emp, y_val) in enumerate(sample_ys):
        date_str = orig_pairs[m_idx][0]  # keep original order for date column
        p_orig   = orig_pairs[m_idx][1]
        ppn      = p_orig - pn
        ppn2     = ppn ** 2
        yyn      = y_val - yn_sample
        yyn2     = yyn ** 2
        rows.append({
            'date':   date_str,
            'p_orig': round(p_orig, 1),
            'm':      m,
            'p_desc': round(p_desc, 2),
            'ppn':    round(ppn, 2),
            'ppn2':   round(ppn2, 2),
            'pr':     pr,
            'tr_emp': round(tr_emp, 2),
            'y':      round(y_val, 3),
            'yyn':    round(yyn, 3),
            'yyn2':   round(yyn2, 4),
        })

    # ── Ven Te Chow results per standard TR ──────────────────────────────────
    chow_rows = []
    for tr in RETURN_PERIODS:
        yt  = float(-np.log(np.log(tr / (tr - 1))))
        kt  = (yt - yn_sample) / sn_sample if sn_sample > 0 else 0.0
        pt  = pn + sigma * kt
        p24 = pt * 1.158
        chow_rows.append({
            'tr':    tr,
            'yt':    round(yt, 4),
            'pn':    round(pn, 2),
            'sigma': round(sigma, 2),
            'kt':    round(kt, 4),
            'pt':    round(pt, 2),
            'p24':   round(p24, 2),
        })

    stats = {
        'n':        n,
        'n1':       n - 1,
        'sum_p':    round(sum_p, 2),
        'pn':       round(pn, 2),
        'sum_ppn2': round(sum_ppn2, 2),
        'sigma':    round(sigma, 2),
        'sum_y':    round(sum_y, 4),
        'yn':       round(yn_sample, 4),
        'sum_yyn2': round(sum_yyn2, 4),
        'sn':       round(sn_sample, 4),
    }

    logger.info(f"📐 Memória Gumbel: N={n}, Pn={pn:.2f}, σ={sigma:.2f}, Yn={yn_sample:.4f}, sn={sn_sample:.4f}")
    return {'rows': rows, 'stats': stats, 'chow_rows': chow_rows}


def compute_taborga_memory(gumbel_memory: dict, isozona: str, lang: str = 'PT') -> dict:
    """
    Compute the full Taborga Isozone disaggregation memory-of-calculation (Passo 3).
    """
    isozona_data = ISOZONA_CONSTANTS[isozona]
    chow_rows    = gumbel_memory['chow_rows']   # list of dicts: tr, pt, sigma, kt, p24
    sn_prime     = gumbel_memory['stats']['sn']  # σ'n from Gumbel sample

    base_rows    = []
    rel_rows     = []
    height_rows  = []
    summary_rows = []
    k_rows       = []

    for r in chow_rows:
        tr   = r['tr']
        pt   = r['pt']
        ap   = round(pt * 1.202, 3)   # 24h equivalent height

        # ── Taborga coefficients for this TR ──────────────────────────────────
        rel1h   = round(_interpolate_rel1h(tr, isozona_data) / 100.0, 5)   # fraction
        rel6min = round(_interpolate_rel6min(tr, isozona_data) / 100.0, 5) # fraction

        # ── Absolute precipitation heights ────────────────────────────────────
        p1h   = round(ap * rel1h,   3)   # 60-min height
        p6min = round(ap * rel6min, 3)   # 6-min height
        p1440 = round(pt, 3)             # 1440-min = original Pt (1 day)

        # ── Logarithmic interpolation coefficients ────────────────────────────
        ln_60_6   = float(np.log(60.0 / 6.0))
        ln_1440_60 = float(np.log(1440.0 / 60.0))
        k1 = round((p1h - p6min) / ln_60_6,    4) if ln_60_6   > 0 else 0.0
        k2 = round((p1440 - p1h) / ln_1440_60, 4) if ln_1440_60 > 0 else 0.0

        base_rows.append({
            'tr': tr, 'pt': pt, 'sn': round(sn_prime, 4), 'ap': ap,
        })
        rel_rows.append({
            'tr': tr,
            'rel1h':   round(rel1h,   3),
            'rel6min': round(rel6min, 3),
        })
        height_rows.append({
            'tr': tr, 'p1h': p1h, 'p6min': p6min,
        })
        summary_rows.append({
            'tr': tr, 'p6min': p6min, 'p1h': p1h, 'p24': p1440,
        })
        k_rows.append({
            'tr': tr, 'p6min': p6min, 'p1h': p1h, 'p1440': p1440,
            'k1': k1, 'k2': k2,
        })

    rel1h_table  = isozona_data['rel1h']
    rel6min_data = isozona_data['rel6min']
    isozona_info = {
        'zone':       isozona,
        'rel1h_by_tr': {tr: v for tr, v in rel1h_table.items()},
        'rel6min_05_50': rel6min_data['05/50'],
        'rel6min_100':   rel6min_data['100'],
    }

    logger.info(
        f"🗺️ Taborga Passo 3: Isozona={isozona}, TRs={[r['tr'] for r in base_rows]}, "
        f"K1 range=[{min(r['k1'] for r in k_rows):.3f}–{max(r['k1'] for r in k_rows):.3f}]"
    )

    return {
        'base_rows':    base_rows,
        'rel_rows':     rel_rows,
        'height_rows':  height_rows,
        'summary_rows': summary_rows,
        'k_rows':       k_rows,
        'isozona_info': isozona_info,
        'isozona':      isozona,
        'sn_prime':     sn_prime,
    }


def _verificar_toque_bound(val: float, low: float, high: float, tol: float = 0.005) -> tuple[bool, float | None]:
    """
    Verifica se o parâmetro ajustado 'val' tocou ou se aproximou perigosamente do limite
    inferior 'low' ou superior 'high' com tolerância relativa 'tol' (padrão 0,5%).
    """
    if low != 0:
        if abs(val - low) <= tol * abs(low) or val < low:
            return True, low
    else:
        if abs(val - low) <= tol:
            return True, low

    if high != 0:
        if abs(val - high) <= tol * abs(high) or val > high:
            return True, high
    else:
        if abs(val - high) <= tol:
            return True, high

    return False, None


def fit_sherman(
    idf_df: pd.DataFrame,
    gumbel_df: pd.DataFrame = None,
    lang: str = 'PT',
    modo_ajuste: str = 'log',
) -> dict:
    """
    Ajuste paramétrico da equação de Sherman (Montana):
      i(t, TR) = (A * TR^B) / (t + C)^D

    Por padrão (modo_ajuste='log'), ajusta em espaço logarítmico:
      ln(i) = ln(A) + B*ln(TR) - D*ln(t + C)
    com bounds hidrológicos da literatura:
      A in [10, 20000], B in [0.08, 0.45], C in [3.0, 70.0], D in [0.50, 0.98].
    Calcula matriz de covariância pcov, erros-padrão (se_A pelo método delta),
    intervalos de confiança de 95%, detecção de toques de bounds (margem 0.5%),
    e métricas: R², NSE verdadeiro, RMSE, erro celular máximo (%) e médio (%).
    """
    t_list, tr_list, i_list = [], [], []

    for col in idf_df.columns:
        try:
            tr_val = int(col.split('=')[1].split(' ')[0])
        except (IndexError, ValueError):
            logger.warning(f"⚠️ Não foi possível extrair TR da coluna: {col}")
            continue
        for t in DURATIONS:
            try:
                i_val = float(idf_df.loc[t, col])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(i_val) and i_val > 0:
                t_list.append(t)
                tr_list.append(tr_val)
                i_list.append(i_val)

    logger.info(f"📐 Pontos para ajuste Sherman: {len(i_list)}")

    if len(i_list) == 0:
        logger.warning("⚠️ Nenhum ponto válido para ajuste Sherman. Usando parâmetros padrão.")
        return {
            'A': 1000.0, 'B': 0.2, 'C': 20.0, 'D': 0.8,
            'se_A': 0.0, 'se_B': 0.0, 'se_C': 0.0, 'se_D': 0.0,
            'ci_A': (0.0, 0.0), 'ci_B': (0.0, 0.0), 'ci_C': (0.0, 0.0), 'ci_D': (0.0, 0.0),
            'bounds_touched': [],
            'R²': 0.0, 'RMSE': 0.0, 'NSE': 0.0,
            'erro_max_celula': 0.0, 'erro_medio_celula': 0.0,
            'modo_ajuste': modo_ajuste,
        }

    t_arr = np.array(t_list, dtype=float)
    tr_arr = np.array(tr_list, dtype=float)
    i_arr = np.array(i_list, dtype=float)

    bounds_touched = []

    if modo_ajuste == 'linear_sem_bounds':
        p0 = [1000.0, 0.2, 20.0, 0.8]
        bounds = ([1.0, 0.01, 0.1, 0.1], [100000.0, 2.0, 100.0, 2.0])
        try:
            popt, pcov = curve_fit(
                sherman_model,
                (t_arr, tr_arr),
                i_arr,
                p0=p0,
                bounds=bounds,
                method='trf',
                maxfev=10000,
            )
            A, B, C, D = popt
            perr = np.sqrt(np.diag(pcov))
            se_A, se_B, se_C, se_D = perr
        except Exception as e:
            logger.warning(f"Ajuste linear não convergiu: {e}")
            A, B, C, D = p0
            se_A, se_B, se_C, se_D = 0.0, 0.0, 0.0, 0.0
    else:
        # Ajuste em espaço log com bounds hidrológicos da literatura
        p0_log = [float(np.log(1200.0)), 0.22, 15.0, 0.80]
        bounds_log = (
            [float(np.log(SHERMAN_OPTIMIZER_BOUNDS['A'][0])), SHERMAN_OPTIMIZER_BOUNDS['B'][0], SHERMAN_OPTIMIZER_BOUNDS['C'][0], SHERMAN_OPTIMIZER_BOUNDS['D'][0]],
            [float(np.log(SHERMAN_OPTIMIZER_BOUNDS['A'][1])), SHERMAN_OPTIMIZER_BOUNDS['B'][1], SHERMAN_OPTIMIZER_BOUNDS['C'][1], SHERMAN_OPTIMIZER_BOUNDS['D'][1]],
        )
        try:
            popt_log, pcov_log = curve_fit(
                sherman_log_model,
                (t_arr, tr_arr),
                np.log(i_arr),
                p0=p0_log,
                bounds=bounds_log,
                method='trf',
                maxfev=15000,
            )
            ln_A, B, C, D = popt_log
            A = float(np.exp(ln_A))
            perr_log = np.sqrt(np.diag(pcov_log))
            se_ln_A, se_B, se_C, se_D = perr_log
            se_A = float(A * se_ln_A)  # método delta

            # Verificação de bounds tocados (margem de 0.5%)
            for p_name, val in [('A', A), ('B', B), ('C', C), ('D', D)]:
                low, high = SHERMAN_OPTIMIZER_BOUNDS[p_name]
                touched, b_val = _verificar_toque_bound(val, low, high)
                if touched:
                    bounds_touched.append((p_name, b_val))

        except Exception as e:
            logger.warning(f"Ajuste log-space não convergiu: {e}")
            A, B, C, D = 1200.0, 0.22, 15.0, 0.80
            se_A, se_B, se_C, se_D = 0.0, 0.0, 0.0, 0.0

    # Intervalos de Confiança (95%)
    df_resid = max(1, len(i_arr) - 4)
    t_crit = float(student_t.ppf(0.975, df_resid))
    ci_A = (round(max(0.0, float(A - t_crit * se_A)), 2), round(float(A + t_crit * se_A), 2))
    ci_B = (round(max(0.0, float(B - t_crit * se_B)), 4), round(float(B + t_crit * se_B), 4))
    ci_C = (round(max(0.0, float(C - t_crit * se_C)), 2), round(float(C + t_crit * se_C), 2))
    ci_D = (round(max(0.0, float(D - t_crit * se_D)), 4), round(float(D + t_crit * se_D), 4))

    # Métricas de validação nas intensidades observadas
    i_fitted = sherman_model((t_arr, tr_arr), A, B, C, D)
    ss_res = float(np.sum((i_arr - i_fitted) ** 2))
    ss_tot = float(np.sum((i_arr - np.mean(i_arr)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0)
    nse = float(1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0)
    rmse = float(np.sqrt(np.mean((i_arr - i_fitted) ** 2)))

    cell_errs = np.abs((i_arr - i_fitted) / i_arr) * 100.0
    erro_max_celula = float(np.max(cell_errs))
    erro_medio_celula = float(np.mean(cell_errs))

    logger.info(f"✅ Sherman ({modo_ajuste}): A={A:.3f}, B={B:.4f}, C={C:.4f}, D={D:.4f} | R²={r2:.4f}, NSE={nse:.4f}, RMSE={rmse:.2f}")

    return {
        'A': round(float(A), 4),
        'B': round(float(B), 4),
        'C': round(float(C), 4),
        'D': round(float(D), 4),
        'se_A': round(float(se_A), 4),
        'se_B': round(float(se_B), 4),
        'se_C': round(float(se_C), 4),
        'se_D': round(float(se_D), 4),
        'ci_A': ci_A,
        'ci_B': ci_B,
        'ci_C': ci_C,
        'ci_D': ci_D,
        'bounds_touched': bounds_touched,
        'R²': round(r2, 4),
        'NSE': round(nse, 4),
        'RMSE': round(rmse, 4),
        'erro_max_celula': round(erro_max_celula, 2),
        'erro_medio_celula': round(erro_medio_celula, 2),
        'modo_ajuste': modo_ajuste,
    }


def run_full_analysis(
    file_bytes: bytes | None = None,
    manual_text: str | None = None,
    df_input: pd.DataFrame | None = None,
    isozona: str = 'B',
    lang: str = 'PT',
    year_start: int | None = None,
    year_end: int | None = None,
    limiar_cobertura_pct: float = 90.0,
    excluir_incompletos: bool = True,
    modo_ajuste_sherman: str = 'log',
) -> dict:
    """
    Orquestra o pipeline completo de análise IDF com diagnóstico de qualidade,
    asserções de monotonicidade e metadados de rastreabilidade.
    """
    # ── Step 1: Parse or receive data ─────────────────────────────────────────
    if df_input is not None and not df_input.empty:
        series_df = df_input.copy()
    elif file_bytes:
        series_df = parse_ana_file(file_bytes, lang=lang)
    elif manual_text and manual_text.strip():
        series_df = parse_manual_data(manual_text, lang=lang)
    else:
        raise UserError(t('err_no_data', lang))

    col_ano = t('col_ano', lang)
    if col_ano not in series_df.columns:
        col_ano = 'Ano' if 'Ano' in series_df.columns else series_df.columns[0]

    # ── Step 1b: Filter by period ─────────────────────────────────────────────
    if year_start is not None or year_end is not None:
        mask = pd.Series([True] * len(series_df))
        if year_start is not None:
            mask = mask & (series_df[col_ano] >= year_start)
        if year_end is not None:
            mask = mask & (series_df[col_ano] <= year_end)
        series_filtered = series_df[mask].reset_index(drop=True)
        if len(series_filtered) == 0:
            y0 = year_start or series_df[col_ano].min()
            y1 = year_end or series_df[col_ano].max()
            raise UserError(t('err_no_period_data', lang).format(y0, y1))
        logger.info(
            f"🗓️ Período filtrado: {year_start or '—'} → {year_end or '—'} "
            f"({len(series_filtered)} de {len(series_df)} anos)"
        )
        series_df = series_filtered

    df_raw_series = series_df.copy()

    # ── Step 1c: Hydrological Quality Diagnostics ─────────────────────────────
    quality_diag = analisar_qualidade_serie(
        series_df,
        limiar_cobertura_pct=limiar_cobertura_pct,
        excluir_incompletos=excluir_incompletos,
        lang=lang,
    )
    series_df = quality_diag['series_limpa']
    anos_descartados = quality_diag['anos_descartados']

    n = len(series_df)
    if n < 10:
        logger.warning(t('err_small_sample', lang).format(n))

    # ── Step 2: Gumbel analysis ───────────────────────────────────────────────
    gumbel_df, mu, sigma, n_samples = gumbel_analysis(series_df, lang=lang)

    # ── Step 3: Disaggregation ────────────────────────────────────────────────
    disagg_df = disaggregate_rainfall(gumbel_df, isozona, lang=lang)

    # ── Step 4: IDF curves ────────────────────────────────────────────────────
    idf_df = compute_idf(disagg_df, lang=lang)

    # ── Step 5: Sherman fitting ───────────────────────────────────────────────
    sherman_params = fit_sherman(
        idf_df, gumbel_df, lang=lang, modo_ajuste=modo_ajuste_sherman
    )

    # ── Step 6: Consistency Verification ─────────────────────────────────────
    physical_consistency = verificar_consistencia_fisica_idf(
        idf_df, sherman_params, lang=lang
    )

    # ── Step 7: Memories of calculation ──────────────────────────────────────
    gumbel_memory = compute_gumbel_memory(series_df, lang=lang)
    taborga_memory = compute_taborga_memory(gumbel_memory, isozona, lang=lang)

    return {
        'series_df': series_df,
        'df_raw_series': df_raw_series,
        'quality_diag': quality_diag,
        'anos_descartados': anos_descartados,
        'physical_consistency': physical_consistency,
        'gumbel_df': gumbel_df,
        'mu': mu,
        'sigma': sigma,
        'n_samples': n_samples,
        'disagg_df': disagg_df,
        'idf_df': idf_df,
        'sherman_params': sherman_params,
        'gumbel_memory': gumbel_memory,
        'taborga_memory': taborga_memory,
        'isozona': isozona,
        'lang': lang,
        'year_start': year_start,
        'year_end': year_end,
        'limiar_cobertura_pct': limiar_cobertura_pct,
        'excluir_incompletos': excluir_incompletos,
        'modo_ajuste_sherman': modo_ajuste_sherman,
    }