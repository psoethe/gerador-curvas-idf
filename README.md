# Gerador de Curvas IDF — versão Streamlit

Aplicativo web para geração de curvas IDF (Intensidade–Duração–Frequência) a partir
de séries de chuvas máximas anuais, pelo método de Gumbel + desagregação de Taborga +
ajuste da equação de Sherman. Inclui integração com a API HidroWebService da ANA e
exportação do memorial de cálculo em PDF e Word.

Esta é a versão migrada do app VIKTOR para **Streamlit**. Todo o núcleo de cálculo foi
reaproveitado; apenas a interface foi reescrita.

## Arquivos

| Arquivo | Papel |
|---|---|
| `streamlit_app.py` | Interface (o que o Streamlit executa) |
| `calculations.py` | Gumbel, Sherman, Taborga e cliente da API da ANA |
| `plotting.py` | Gráficos Plotly |
| `report.py` / `report_word.py` | Memorial em PDF / Word |
| `i18n.py` | Textos PT/EN |
| `requirements.txt` | Dependências |
| `.streamlit/config.toml` | Tema |
| `.streamlit/secrets.toml.example` | Modelo de credenciais |

## Rodar localmente

```bash
cd streamlit_app
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Abre em `http://localhost:8501`. As credenciais da ANA são lidas, nesta ordem, de:
`st.secrets` → variáveis de ambiente `ANA_USER`/`ANA_PASS` → arquivo `ana.env` na pasta.

## Publicar no Streamlit Community Cloud (grátis)

1. Suba **o conteúdo desta pasta** para um repositório no GitHub.
   O `.gitignore` já impede o envio de `ana.env` e `secrets.toml` (credenciais).
2. Acesse <https://share.streamlit.io>, faça login com o GitHub e clique em **New app**.
3. Aponte para o repositório e defina o arquivo principal como `streamlit_app.py`.
4. Em **Advanced settings → Secrets**, cole:
   ```toml
   ANA_USER = "28125322892"
   ANA_PASS = "sua-senha"
   ```
5. **Deploy**. O app fica em uma URL pública `https://<seu-app>.streamlit.app`.

Se você já tem uma página na Vercel, basta colocar lá um link (ou um `<iframe>`) para
essa URL do Streamlit.

## Fontes de dados da ANA

No modo **API HidroWeb** há duas fontes selecionáveis:

- **⚡ Histórica (convencional, recomendada)** — usa o webservice legado
  `ServiceANA.asmx/HidroSerieHistorica`, a mesma fonte dos downloads do site HidroWeb.
  Traz **toda a série numa única requisição**, é praticamente instantânea e **não exige
  credenciais**. É a fonte adequada para curvas IDF (estações convencionais, com séries
  históricas longas). Basta informar o **código da estação**.
- **📡 Telemétrica (automática)** — usa a API autenticada `EstacoesTelemetricas`. Só
  cobre estações automáticas (dados a partir de ~2001), exige token (ANA_USER/ANA_PASS)
  e vai **ano a ano** (limite de 366 dias por requisição), podendo levar vários minutos.
  Permite listar estações por UF.

## Observações

- Alternativa também instantânea: baixe o CSV no HidroWeb e use o modo **Arquivo CSV/TXT**.
- Se uma estação retornar "sem dados", experimente outro código — nem toda estação do
  inventário telemétrico possui série histórica de chuva.
- Nunca faça commit de `ana.env` nem de `.streamlit/secrets.toml`.
