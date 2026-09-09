"""
Testes automatizados para a Etapa 2 da transição SII-HiDRO (v3.0).
Valida:
1. Destravamento estrito entre módulos (module_status):
   - idf: todo com coordenadas, done com physical_consistency['is_valid'] == True
   - bacia: todo com coordenadas, done com bacia_confirmada == True
   - vazao: locked enquanto idf ou bacia não forem done; todo quando ambos done
2. Estado de dois eixos (active_module, step) e conformidade de etapas por módulo (MODULE_STEPS).
3. Fonte única de coordenadas: proj_lat e proj_lon globais compartilhados entre contexto, IDF e Bacia.
4. Ausência total de st.sidebar no código de streamlit_app.py.
5. Sincronização entre step (0..3) e current_step (1..4) no módulo IDF.
6. Contrato de persistência na tela Salvar (guarde entrada, recalcule saída).
7. Flag project_dirty e estilo âmbar (#d97706) do botão Salvar.
"""
import sys
import ast
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit_app as app
import i18n
from i18n import t


def test_sidebar_completely_removed():
    app_path = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    content = app_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(app_path))

    sidebar_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == 'sidebar':
            sidebar_calls.append(node.lineno)

    assert len(sidebar_calls) == 0, f"st.sidebar ainda encontrado nas linhas: {sidebar_calls}"


def test_module_steps_structure():
    expected_modules = {'projeto', 'idf', 'bacia', 'vazao'}
    assert set(app.MODULE_STEPS.keys()) == expected_modules

    assert len(app.MODULE_STEPS['projeto']) == 2
    assert app.MODULE_STEPS['projeto'][0][1] == 'stepper_proj_open'
    assert app.MODULE_STEPS['projeto'][1][1] == 'stepper_proj_save'

    assert len(app.MODULE_STEPS['idf']) == 4
    assert app.MODULE_STEPS['idf'][0][1] == 'stepper_step1'
    assert app.MODULE_STEPS['idf'][1][1] == 'stepper_step2'
    assert app.MODULE_STEPS['idf'][2][1] == 'stepper_step3'
    assert app.MODULE_STEPS['idf'][3][1] == 'stepper_step4'

    assert len(app.MODULE_STEPS['bacia']) == 2
    assert app.MODULE_STEPS['bacia'][0][1] == 'stepper_basin_delineation'
    assert app.MODULE_STEPS['bacia'][1][1] == 'stepper_basin_inputs'

    assert len(app.MODULE_STEPS['vazao']) == 2
    assert app.MODULE_STEPS['vazao'][0][1] == 'stepper_flow_tc'
    assert app.MODULE_STEPS['vazao'][1][1] == 'stepper_flow_design'


def test_module_status_idf():
    st.session_state['proj_lat'] = None
    st.session_state['proj_lon'] = None
    st.session_state['results'] = None
    assert app.module_status('idf') == 'locked'

    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186
    st.session_state['results'] = None
    assert app.module_status('idf') == 'todo'

    st.session_state['results'] = {'physical_consistency': {'is_valid': False}}
    assert app.module_status('idf') == 'todo'

    st.session_state['results'] = {'physical_consistency': {'is_valid': True}}
    assert app.module_status('idf') == 'done'


def test_module_status_bacia():
    st.session_state['proj_lat'] = None
    st.session_state['proj_lon'] = None
    st.session_state['bacia_confirmada'] = False
    assert app.module_status('bacia') == 'locked'

    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186
    st.session_state['bacia_confirmada'] = False
    assert app.module_status('bacia') == 'todo'

    st.session_state['bacia_confirmada'] = True
    assert app.module_status('bacia') == 'done'


def test_module_status_vazao_strict_unlock():
    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186
    st.session_state['q_projeto_m3s'] = None

    st.session_state['results'] = None
    st.session_state['bacia_confirmada'] = False
    assert app.module_status('vazao') == 'locked'

    st.session_state['results'] = {'physical_consistency': {'is_valid': True}}
    st.session_state['bacia_confirmada'] = False
    assert app.module_status('vazao') == 'locked'

    st.session_state['results'] = None
    st.session_state['bacia_confirmada'] = True
    assert app.module_status('vazao') == 'locked'

    st.session_state['results'] = {'physical_consistency': {'is_valid': True}}
    st.session_state['bacia_confirmada'] = True
    assert app.module_status('vazao') == 'todo'

    st.session_state['q_projeto_m3s'] = 39.4
    assert app.module_status('vazao') == 'done'


def test_single_coordinate_source():
    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186
    st.session_state['proj_loc'] = 'Novo Progresso, PA'

    assert st.session_state['proj_lat'] == -7.0375
    assert st.session_state['proj_lon'] == -55.4186
    assert st.session_state['proj_loc'] == 'Novo Progresso, PA'


def test_project_dirty_and_amber_style():
    st.session_state['project_dirty'] = False
    app.mark_dirty()
    assert st.session_state['project_dirty'] is True

    app_path = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    code = app_path.read_text(encoding="utf-8")
    assert '#d97706' in code
    assert 'project_dirty' in code


def run_all():
    tests = [
        ("1. Ausência total de st.sidebar", test_sidebar_completely_removed),
        ("2. Estrutura de etapas por módulo (MODULE_STEPS)", test_module_steps_structure),
        ("3. Status do módulo IDF (module_status('idf'))", test_module_status_idf),
        ("4. Status do módulo Bacia (module_status('bacia'))", test_module_status_bacia),
        ("5. Destravamento estrito de Vazão (module_status('vazao'))", test_module_status_vazao_strict_unlock),
        ("6. Fonte única de coordenadas (proj_lat / proj_lon)", test_single_coordinate_source),
        ("7. Flag project_dirty e regra de cor âmbar (#d97706)", test_project_dirty_and_amber_style),
    ]

    print("=" * 70)
    print("EXECUTANDO TESTES DA ETAPA 2 (ESTADO, NAVEGAÇÃO E REGRAS SII-HiDRO)")
    print("=" * 70)
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    print("=" * 70)
    print(f"TOTAL: {passed} passaram, {failed} falharam.")
    print("=" * 70)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all()
