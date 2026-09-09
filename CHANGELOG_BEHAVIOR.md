# Histórico de Mudanças de Comportamento Técnico (CHANGELOG_BEHAVIOR)

Este documento registra alterações metodológicas, correções de algoritmos e mudanças de formulação hidrológica entre as versões do ecossistema **SII-HiDRO**.

Ao abrir um projeto gerado por uma versão anterior, o sistema consulta este registro para informar o responsável técnico sobre discrepâncias potenciais nos resultados recalculados a quente.

---

## [3.0.0] - 2026-08-15
### Mudanças Estruturais e Metodológicas
- **Arquitetura Modular SII-HiDRO:** Transição para estado de dois eixos (`active_module` e `step`), eliminando a barra lateral e integrando os módulos de Projeto, IDF, Bacia e Vazão.
- **Formato de Projeto .siih (Esquema `siih/1`):** Adoção de formato de persistência aberto em JSON UTF-8 com auditoria criptográfica SHA-256 e recálculo dinâmico na abertura ("Guarde entrada, recalcule saída").
- **Delineação Hidrográfica Integrada:** Mapeamento de bacia com MDE FABDEM e reprojeção SIRGAS 2000 UTM.
- **Determinação de Vazão de Projeto:** Critério de transição de método por limiar normativo IPR-724 (Método Racional até 100 ha; Hidrograma Unitário SCS acima de 100 ha).

---

## [2.1.0] - 2026-08-10
### Correções Algorítmicas e Auditoria
- **Consistência Física Obrigatória:** Implementação de verificação de monotonicidade em tempo ($i_{t_1} > i_{t_2}$) e em frequência ($i_{TR_1} < i_{TR_2}$) na matriz IDF calculada e na equação de Sherman ajustada.
- **Ajuste de Sherman Montana com Bounds da Literatura:** Correção da regressão não-linear em espaço logarítmico para evitar degeneração paramétrica, aplicando limites físicos clássicos ($A > 0$, $0 < B \le 0,60$, $C > 0$, $0,50 \le D \le 1,20$).
- **Desagregação de Chuvas (Taborga, 1974):** Padronização das 22 durações sub-diárias completas (6 min a 1440 min) com preservação da coluna de duração no índice dos DataFrames exportados.
- **Interpolação Multi-estação (IDW):** Implementação de salvaguarda de co-localização quando a distância até a estação for inferior a 0,1 km, evitando pesos infinitos ou singularidades numéricas.
- **Identificação Espacial de Isozonas:** Detecção geográfica por mapa raster oficial com fallback automático resiliente.

---

## [2.0.0] - 2026-07-01
### Versão Inicial Integrada
- Implementação inicial das rotas da API HidroWeb da ANA.
- Ajuste probabilístico de Gumbel (Valor Extremo Tipo I) via formulação de Ven Te Chow.
- Exportação de memoriais de cálculo em formatos PDF e Word (.docx).
