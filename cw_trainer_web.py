#!/usr/bin/env python3
"""
+===========================================================+
|     CW ADAPTIVE TRAINER  v10  (Streamlit)                  |
|     Treino de CW por PY2TAE (Lucas)                        |
|                                                            |
|  Página abre zerada. Progresso salvo como "save game" JSON |
|  Cada aba do navegador é independente                      |
|                                                            |
|  Uso: streamlit run cw_trainer_web.py                      |
|  Dependência: pip install streamlit                         |
+===========================================================+
"""

import json, math, wave, array, random, io, datetime
import streamlit as st

# ===========================================================
#  CONSTANTES
# ===========================================================

CHAR_SEQUENCE = list("ETIANMSURWDKGOHVFLPJBXCYZQ0123456789.,?/=")

MORSE_CODE = {
    'A': '.-',    'B': '-...',  'C': '-.-.',  'D': '-..',   'E': '.',
    'F': '..-.',  'G': '--.',   'H': '....',  'I': '..',    'J': '.---',
    'K': '-.-',   'L': '.-..',  'M': '--',    'N': '-.',    'O': '---',
    'P': '.--.',  'Q': '--.-',  'R': '.-.',   'S': '...',   'T': '-',
    'U': '..-',   'V': '...-',  'W': '.--',   'X': '-..-',  'Y': '-.--',
    'Z': '--..',
    '0': '-----', '1': '.----', '2': '..---', '3': '...--', '4': '....-',
    '5': '.....', '6': '-....', '7': '--...', '8': '---..', '9': '----.',
    '.': '.-.-.-', ',': '--..--', '?': '..--..', '/': '-..-.', '=': '-...-',
}

SAMPLE_RATE = 22050
RAMP_MS = 3
TWO_PI = 2.0 * math.pi

DEFAULT_CONFIG = {
    "frequencia": 700, "variacao_freq": 0, "wpm": 10, "farnsworth": 6,
    "licao": 2, "num_grupos": 6, "tam_grupo": 4, "meta_acerto": 90,
    "janela": 10, "peso_minimo": 0.1, "peso_maximo": 1.0,
    "historico_chars": {},
    "registro": [],
}


# ===========================================================
#  MOTOR DE ÁUDIO
# ===========================================================

def _tom(duracao, frequencia):
    n = int(SAMPLE_RATE * duracao)
    if n == 0:
        return array.array('h')
    rampa = int(SAMPLE_RATE * RAMP_MS / 1000)
    buf = array.array('h', [0] * n)
    for i in range(n):
        v = math.sin(TWO_PI * frequencia * i / SAMPLE_RATE)
        if i < rampa:
            v *= i / rampa
        elif i >= n - rampa:
            v *= (n - 1 - i) / rampa
        buf[i] = int(v * 24000)
    return buf


def _silencio(duracao):
    return array.array('h', [0] * int(SAMPLE_RATE * duracao))


def _tempos(wpm, farn):
    dit = 1.2 / wpm
    dah = 3 * dit
    intra = dit
    if farn < wpm:
        delta = (60.0 / farn - 50 * dit) / 19.0
        return dit, dah, intra, 3 * delta, 7 * delta
    return dit, dah, intra, 3 * dit, 7 * dit


def _para_wav(arr):
    buf = io.BytesIO()
    with wave.open(buf, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(arr.tobytes())
    buf.seek(0)
    return buf


def texto_para_audio(texto, frequencia, wpm, farn):
    """Gera áudio WAV a partir de texto morse. Retorna (BytesIO, duração_s)."""
    dit_t, dah_t, intra_t, ic_t, iw_t = _tempos(wpm, farn)
    td, ta = _tom(dit_t, frequencia), _tom(dah_t, frequencia)
    si, sc, sw = _silencio(intra_t), _silencio(ic_t), _silencio(iw_t)
    audio = array.array('h')
    for i, ch in enumerate(texto):
        if ch == ' ':
            audio.extend(sw)
            continue
        morse = MORSE_CODE.get(ch.upper(), '')
        if not morse:
            continue
        for j, sym in enumerate(morse):
            audio.extend(td if sym == '.' else ta)
            if j < len(morse) - 1:
                audio.extend(si)
        if i < len(texto) - 1 and texto[i + 1] != ' ':
            audio.extend(sc)
    return _para_wav(audio), len(audio) / SAMPLE_RATE


def audio_amostra(caracteres, frequencia, wpm):
    """Gera áudio com cada caractere separado por pausa."""
    dit_t, dah_t, intra_t, _, _ = _tempos(wpm, wpm)
    td, ta = _tom(dit_t, frequencia), _tom(dah_t, frequencia)
    si, pausa = _silencio(intra_t), _silencio(0.6)
    audio = array.array('h')
    for ch in caracteres:
        morse = MORSE_CODE.get(ch.upper(), '')
        if not morse:
            continue
        for j, sym in enumerate(morse):
            audio.extend(td if sym == '.' else ta)
            if j < len(morse) - 1:
                audio.extend(si)
        audio.extend(pausa)
    return _para_wav(audio)


# ===========================================================
#  CONFIGURAÇÃO (somente session_state)
# ===========================================================

def cfg():
    return st.session_state.cfg


def acuracia_char(ch):
    h = cfg()["historico_chars"].get(ch, [])
    return sum(h) / len(h) if h else 0.5


def atualizar_historico(ch, acertou):
    conf = cfg()
    janela = conf["janela"]
    if ch not in conf["historico_chars"]:
        conf["historico_chars"][ch] = []
    conf["historico_chars"][ch].append(1 if acertou else 0)
    if len(conf["historico_chars"][ch]) > janela:
        conf["historico_chars"][ch] = conf["historico_chars"][ch][-janela:]


def adicionar_registro(licao, freq, total, corretos, acuracia, aprovado):
    entrada = {
        "data": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "licao": licao, "freq": freq,
        "total": total, "corretos": corretos,
        "acuracia": round(acuracia, 1), "aprovado": aprovado,
    }
    cfg()["registro"].append(entrada)
    if len(cfg()["registro"]) > 500:
        cfg()["registro"] = cfg()["registro"][-500:]


# ===========================================================
#  GERAÇÃO DE GRUPOS PONDERADOS
# ===========================================================

def calcular_pesos():
    conf = cfg()
    piso, teto = conf["peso_minimo"], conf["peso_maximo"]
    chars = CHAR_SEQUENCE[:conf["licao"]]
    return chars, [piso + (teto - piso) * (1.0 - acuracia_char(ch)) for ch in chars]


def gerar_grupos():
    conf = cfg()
    chars, pesos = calcular_pesos()
    return [''.join(random.choices(chars, weights=pesos, k=conf["tam_grupo"]))
            for _ in range(conf["num_grupos"])]


def frequencia_aleatoria():
    conf = cfg()
    v = conf["variacao_freq"]
    return conf["frequencia"] + (random.randint(-v, v) if v else 0)


# ===========================================================
#  COMPARAÇÃO
# ===========================================================

def comparar(enviados, texto_recebido):
    recebidos = texto_recebido.upper().split()
    total = corretos = 0
    detalhes, resultados = [], []
    for i, sg in enumerate(enviados):
        rg = recebidos[i] if i < len(recebidos) else ''
        acertos = 0
        for ci in range(len(sg)):
            total += 1
            ok = ci < len(rg) and sg[ci] == rg[ci]
            if ok:
                acertos += 1
            resultados.append((sg[ci], ok))
        corretos += acertos
        detalhes.append((sg, rg, acertos))
    return total, corretos, (corretos / total * 100 if total else 0), detalhes, resultados


# ===========================================================
#  STREAMLIT
# ===========================================================

def inicializar():
    padrao = {"cfg": None, "grupos": [], "freq": 0,
              "wav": None, "dur": 0, "corrigido": False, "resultado": None}
    for k, v in padrao.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if st.session_state.cfg is None:
        st.session_state.cfg = dict(DEFAULT_CONFIG)


# ── Barra lateral ─────────────────────────────────────────

def barra_lateral():
    conf = cfg()
    chars_licao = CHAR_SEQUENCE[:conf["licao"]]

    st.sidebar.markdown("## ⚡ CW Trainer")
    st.sidebar.caption("Treino de CW por PY2TAE (Lucas)")
    st.sidebar.divider()

    # Save game: SEMPRE visível e destacado
    st.sidebar.markdown("### 💾 Seu progresso")
    dados_json = json.dumps(conf, indent=2, ensure_ascii=False)
    st.sidebar.download_button(
        "📥 Baixar save game",
        data=dados_json,
        file_name=f"cw_save_{datetime.date.today()}.json",
        mime="application/json",
        use_container_width=True,
    )
    arquivo = st.sidebar.file_uploader("📤 Carregar save game:", type=["json"], key="importar")
    if arquivo is not None:
        try:
            dados = json.load(arquivo)
            mesclado = dict(DEFAULT_CONFIG)
            mesclado.update(dados)
            if not isinstance(mesclado.get("historico_chars"), dict):
                mesclado["historico_chars"] = {}
            if not isinstance(mesclado.get("registro"), list):
                mesclado["registro"] = []
            st.session_state.cfg = mesclado
            st.sidebar.success("Progresso carregado!")
            st.rerun()
        except json.JSONDecodeError:
            st.sidebar.error("Arquivo JSON inválido.")

    st.sidebar.caption("⚠️ Baixe seu save game antes de fechar o navegador!")

    st.sidebar.divider()

    # Info da lição
    st.sidebar.markdown(f"**Lição {conf['licao']}/{len(CHAR_SEQUENCE)}**")
    st.sidebar.code(' '.join(chars_licao), language=None)
    if conf["licao"] < len(CHAR_SEQUENCE):
        prox = CHAR_SEQUENCE[conf["licao"]]
        st.sidebar.markdown(f"Próximo: **{prox}** (`{MORSE_CODE.get(prox, '')}`)")

    st.sidebar.divider()

    # Configurações
    with st.sidebar.expander("⚙️ Configurações"):
        conf["licao"] = st.number_input("Lição", 2, len(CHAR_SEQUENCE), conf["licao"], key="sl")
        conf["frequencia"] = st.number_input("Frequência base (Hz)", 200, 1500, conf["frequencia"], key="sf")
        conf["variacao_freq"] = st.number_input("Variação ± (Hz)", 0, 200, conf["variacao_freq"], key="sv")
        conf["wpm"] = st.number_input("WPM (velocidade do caractere)", 5, 60, conf["wpm"], key="sw")
        conf["farnsworth"] = st.number_input("Farnsworth WPM (espaçamento)", 2, conf["wpm"],
                                              min(conf["farnsworth"], conf["wpm"]), key="sn")
        conf["num_grupos"] = st.number_input("Grupos por exercício", 1, 50, conf["num_grupos"], key="sg_")
        conf["tam_grupo"] = st.number_input("Caracteres por grupo", 2, 10, conf["tam_grupo"], key="sc_")
        conf["meta_acerto"] = st.number_input("Meta de acerto (%)", 50, 100, conf["meta_acerto"], key="st_")
        conf["janela"] = st.number_input("Janela da média móvel", 3, 100, conf["janela"], key="sj")
        conf["peso_minimo"] = st.number_input("Peso mínimo (char bom)", 0.01, 0.5,
                                               conf["peso_minimo"], format="%.2f", key="spf")
        conf["peso_maximo"] = st.number_input("Peso máximo (char ruim)", 0.1, 10.0,
                                               conf["peso_maximo"], format="%.1f", key="spc")
        conf["peso_maximo"] = max(conf["peso_maximo"], conf["peso_minimo"] + 0.1)

    # Ações
    with st.sidebar.expander("🔧 Ações"):
        if st.button("🗑️ Zerar estatísticas"):
            conf["historico_chars"] = {}
            conf["registro"] = []
            st.rerun()
        if st.button("↩️ Restaurar tudo para o padrão"):
            st.session_state.cfg = dict(DEFAULT_CONFIG)
            st.session_state.grupos = []
            st.session_state.wav = None
            st.session_state.corrigido = False
            st.session_state.resultado = None
            st.rerun()

    st.sidebar.divider()
    razao = conf["peso_maximo"] / conf["peso_minimo"] if conf["peso_minimo"] > 0 else 999
    st.sidebar.caption(
        f"{conf['wpm']} WPM · Farns: {conf['farnsworth']} · "
        f"{conf['frequencia']}Hz ±{conf['variacao_freq']}\n\n"
        f"{conf['num_grupos']}×{conf['tam_grupo']} chars · "
        f"Meta: {conf['meta_acerto']}% · Razão: {razao:.0f}×"
    )


# ── Aba Exercício ─────────────────────────────────────────

def aba_exercicio():
    conf = cfg()

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        tocar = st.button("▶  Gerar e tocar", type="primary", use_container_width=True)
    with c2:
        amostra_btn = st.button("♪  Ouvir amostra", use_container_width=True)
    with c3:
        corrigir = st.button("✓  Corrigir", type="primary", use_container_width=True)

    # GERAR E TOCAR
    if tocar:
        st.session_state.grupos = gerar_grupos()
        st.session_state.freq = frequencia_aleatoria()
        st.session_state.corrigido = False
        st.session_state.resultado = None
        texto = ' '.join(st.session_state.grupos)
        with st.spinner("Gerando áudio..."):
            buf, dur = texto_para_audio(texto, st.session_state.freq, conf["wpm"], conf["farnsworth"])
            st.session_state.wav = buf.getvalue()
            st.session_state.dur = dur

    # AMOSTRA
    if amostra_btn:
        chars = CHAR_SEQUENCE[:conf["licao"]]
        freq = frequencia_aleatoria()
        with st.spinner("Gerando amostra..."):
            buf = audio_amostra(chars, freq, conf["wpm"])
        st.audio(buf, format="audio/wav", autoplay=True)
        st.markdown(f"**Amostra a {freq} Hz:**")
        colunas = st.columns(min(len(chars), 8))
        for i, ch in enumerate(chars):
            colunas[i % len(colunas)].code(f"{ch}  {MORSE_CODE.get(ch, '')}")
        return

    # PLAYER
    if st.session_state.wav and not st.session_state.corrigido:
        st.divider()
        grupos = st.session_state.grupos
        total_chars = sum(len(g) for g in grupos)

        with st.expander(
            f"ℹ️ {len(grupos)} grupos × {conf['tam_grupo']} = "
            f"{total_chars} caracteres · {st.session_state.freq} Hz"
        ):
            chars, pesos = calcular_pesos()
            total_p = sum(pesos)
            itens = sorted(zip(chars, pesos), key=lambda x: x[1], reverse=True)[:5]
            st.markdown("**Caracteres em foco (maior probabilidade):**")
            for ch, p in itens:
                acc = acuracia_char(ch)
                hist = conf["historico_chars"].get(ch, [])
                media_str = f"{acc * 100:.0f}%" if hist else "sem dados"
                foco = " 🎯" if p > conf["peso_maximo"] * 0.7 else ""
                st.text(f"  {ch}   média: {media_str:>10s}   prob: {p / total_p * 100:4.1f}%{foco}")

        st.audio(st.session_state.wav, format="audio/wav", autoplay=True)
        st.caption(f"⏱️ Duração: {st.session_state.dur:.1f}s — Aperte play e anote o que ouvir")

    # CAMPO DE RESPOSTA
    if st.session_state.grupos and not st.session_state.corrigido:
        st.markdown("### ✏️ Digite o que você ouviu")
        st.caption("Separe os grupos com espaço")
        resposta = st.text_input("Sua resposta:", key="resposta",
                                  placeholder="ETIA MSNR ...",
                                  label_visibility="collapsed")
        if corrigir:
            if resposta and resposta.strip():
                executar_correcao(resposta.strip().upper())
            else:
                st.warning("Digite o que você ouviu antes de corrigir.")

    # RESULTADO
    if st.session_state.resultado:
        exibir_resultado()


def executar_correcao(resposta):
    conf = cfg()
    grupos = st.session_state.grupos
    chars_licao = CHAR_SEQUENCE[:conf["licao"]]

    total, corretos, acuracia, detalhes, res_chars = comparar(grupos, resposta)

    for ch, acertou in res_chars:
        atualizar_historico(ch, acertou)

    limiar = conf["meta_acerto"] / 100.0
    janela = conf["janela"]
    abaixo, sem_dados = [], []
    for ch in chars_licao:
        h = conf["historico_chars"].get(ch, [])
        if len(h) < janela:
            sem_dados.append((ch, len(h)))
        elif acuracia_char(ch) < limiar:
            abaixo.append((ch, acuracia_char(ch)))

    aprovado = not abaixo and not sem_dados

    adicionar_registro(conf["licao"], st.session_state.freq, total, corretos, acuracia, aprovado)

    if aprovado and conf["licao"] < len(CHAR_SEQUENCE):
        conf["licao"] += 1

    st.session_state.resultado = {
        "total": total, "corretos": corretos, "acuracia": acuracia,
        "detalhes": detalhes, "res_chars": res_chars,
        "aprovado": aprovado, "abaixo": abaixo, "sem_dados": sem_dados,
        "freq": st.session_state.freq,
    }
    st.session_state.corrigido = True


def exibir_resultado():
    conf = cfg()
    r = st.session_state.resultado

    st.divider()

    c1, c2, c3 = st.columns(3)
    c1.metric("Acerto", f"{r['acuracia']:.1f}%")
    c2.metric("Corretos", f"{r['corretos']}/{r['total']}")
    c3.metric("Frequência", f"{r['freq']} Hz")
    st.progress(min(r['acuracia'] / 100, 1.0))

    # Comparação grupo a grupo
    st.markdown("#### Comparação grupo a grupo")
    for sg, rg, gc in r["detalhes"]:
        if not rg:
            marcado = " ".join(["🔴"] * len(sg))
        else:
            partes = []
            for ci in range(len(sg)):
                if ci < len(rg):
                    if sg[ci] == rg[ci]:
                        partes.append(f"**{rg[ci]}**")
                    else:
                        partes.append(f"~~{rg[ci].lower()}~~")
                else:
                    partes.append("⬜")
            marcado = " ".join(partes)
        icone = "✅" if sg == (rg.upper() if rg else '') else "❌"
        st.markdown(f"`{sg}` → {marcado}  {icone} ({gc}/{len(sg)})")

    # Erros
    erros = {}
    for ch, ok in r["res_chars"]:
        if not ok:
            erros[ch] = erros.get(ch, 0) + 1
    if erros:
        st.markdown("#### Caracteres com erro")
        for ch in sorted(erros, key=erros.get, reverse=True):
            m = MORSE_CODE.get(ch, '')
            acc = acuracia_char(ch)
            st.markdown(f"- **{ch}** (`{m}`) — {erros[ch]}× erro — média atual: {acc * 100:.0f}%")

    # Aprovação
    st.divider()
    if r["aprovado"]:
        st.success(f"✅ Aprovado! Todos os caracteres atingiram a meta de {conf['meta_acerto']}%!")
        if conf["licao"] <= len(CHAR_SEQUENCE):
            nc = CHAR_SEQUENCE[conf["licao"] - 1]
            st.info(f"Avançando para a lição {conf['licao']} — novo caractere: **{nc}** (`{MORSE_CODE.get(nc, '')}`)")
    else:
        st.error(
            f"Repetindo a lição {conf['licao']}. "
            f"Critério: todos os caracteres ≥ {conf['meta_acerto']}% "
            f"(janela de {conf['janela']} tentativas)"
        )
        if r["abaixo"]:
            st.markdown("**Caracteres abaixo da meta:**")
            for ch, acc in sorted(r["abaixo"], key=lambda x: x[1]):
                h = conf["historico_chars"].get(ch, [])
                visual = ''.join(['🟢' if x else '🔴' for x in h[-conf["janela"]:]])
                falta = conf["meta_acerto"] - acc * 100
                st.markdown(
                    f"- **{ch}** (`{MORSE_CODE.get(ch, '')}`) — "
                    f"{acc * 100:.1f}% (faltam {falta:.1f}%) — {visual}"
                )
        if r["sem_dados"]:
            st.markdown("**Caracteres com poucas amostras:**")
            for ch, n in r["sem_dados"]:
                st.markdown(
                    f"- **{ch}** (`{MORSE_CODE.get(ch, '')}`) — "
                    f"{n}/{conf['janela']} tentativas"
                )

    st.markdown("")
    if st.button("🔄 Novo exercício", type="primary"):
        st.session_state.grupos = []
        st.session_state.wav = None
        st.session_state.corrigido = False
        st.session_state.resultado = None
        st.rerun()


# ── Aba Estatísticas ──────────────────────────────────────

def aba_estatisticas():
    conf = cfg()
    chars_licao = CHAR_SEQUENCE[:conf["licao"]]
    janela = conf["janela"]
    limiar = conf["meta_acerto"] / 100.0
    _, pesos = calcular_pesos()
    mapa_pesos = dict(zip(chars_licao, pesos))

    prontos = sum(1 for ch in chars_licao
                  if len(conf["historico_chars"].get(ch, [])) >= janela
                  and acuracia_char(ch) >= limiar)
    st.progress(prontos / len(chars_licao) if chars_licao else 0)
    st.caption(f"Progresso: {prontos}/{len(chars_licao)} caracteres aprovados (≥ {conf['meta_acerto']}%)")

    dados = []
    for ch in chars_licao:
        h = conf["historico_chars"].get(ch, [])
        n = len(h)
        acc = sum(h) / n if n > 0 else -1
        visual = ''.join(['🟢' if x else '🔴' for x in h[-janela:]])
        status = "✅" if n >= janela and acc >= limiar else ("⏳" if n < janela else "❌")
        dados.append({
            "": status,
            "Caractere": ch,
            "Morse": MORSE_CODE.get(ch, '?'),
            "Amostras": f"{n}/{janela}",
            "Média": f"{acc * 100:.1f}%" if n else "—",
            "Peso": f"{mapa_pesos.get(ch, 0.5):.2f}",
            "Histórico": visual or "—",
        })
    dados.sort(key=lambda x: float(x["Média"].replace('%', '').replace('—', '-1')))
    st.dataframe(dados, use_container_width=True, hide_index=True,
                 height=min(35 * len(dados) + 38, 600))

    com_dados = [ch for ch in chars_licao if conf["historico_chars"].get(ch)]
    if com_dados:
        acuracias = [acuracia_char(ch) for ch in com_dados]
        media = sum(acuracias) / len(acuracias) * 100
        pior = min(com_dados, key=lambda ch: acuracia_char(ch))
        melhor = max(com_dados, key=lambda ch: acuracia_char(ch))
        c1, c2, c3 = st.columns(3)
        c1.metric("Média geral", f"{media:.1f}%")
        c2.metric(f"Melhor: {melhor}", f"{acuracia_char(melhor) * 100:.1f}%")
        c3.metric(f"Pior: {pior}", f"{acuracia_char(pior) * 100:.1f}%")


# ── Aba Histórico ─────────────────────────────────────────

def aba_historico():
    conf = cfg()
    registro = conf.get("registro", [])

    if not registro:
        st.info("Nenhum exercício registrado ainda. Faça seu primeiro treino!")
        return

    st.markdown(f"### Histórico de treinos ({len(registro)} exercícios)")

    total_ex = len(registro)
    aprovados = sum(1 for r in registro if r.get("aprovado"))
    taxa = aprovados / total_ex * 100 if total_ex else 0
    media_acc = sum(r.get("acuracia", 0) for r in registro) / total_ex if total_ex else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total de exercícios", total_ex)
    c2.metric("Aprovações", f"{aprovados} ({taxa:.0f}%)")
    c3.metric("Acurácia média", f"{media_acc:.1f}%")

    ultimos = list(reversed(registro[-50:]))
    tabela = []
    for r in ultimos:
        tabela.append({
            "Data": r.get("data", "—"),
            "Lição": r.get("licao", "—"),
            "Acerto": f"{r.get('acuracia', 0):.1f}%",
            "Corretos": f"{r.get('corretos', 0)}/{r.get('total', 0)}",
            "Freq": f"{r.get('freq', 0)} Hz",
            "Resultado": "✅ Aprovado" if r.get("aprovado") else "❌ Repetir",
        })
    st.dataframe(tabela, use_container_width=True, hide_index=True)


# ── Aba Referência Morse ──────────────────────────────────

def aba_referencia():
    conf = cfg()
    chars = CHAR_SEQUENCE[:conf["licao"]]

    st.markdown("### Caracteres da lição atual")
    colunas = st.columns(min(len(chars), 6))
    for i, ch in enumerate(chars):
        m = MORSE_CODE.get(ch, '')
        acc = acuracia_char(ch)
        h = conf["historico_chars"].get(ch, [])
        media_str = f"{acc * 100:.0f}%" if h else "—"
        colunas[i % len(colunas)].code(f"{ch}  {m:<8s}  {media_str}")

    if conf["licao"] < len(CHAR_SEQUENCE):
        st.divider()
        st.markdown("### Caracteres ainda não desbloqueados")
        restantes = CHAR_SEQUENCE[conf["licao"]:]
        colunas2 = st.columns(min(len(restantes), 6))
        for i, ch in enumerate(restantes):
            m = MORSE_CODE.get(ch, '')
            colunas2[i % len(colunas2)].code(f"{ch}  {m}")


# ===========================================================
#  MAIN
# ===========================================================

def main():
    st.set_page_config(
        page_title="CW Trainer — PY2TAE",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown("""<style>
    .stApp { background-color: #1a1a2e; }
    div[data-testid="stMetric"] { background: #16213e; padding: 10px; border-radius: 8px; }
    .stTextInput input {
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 1.2rem;
    }
    </style>""", unsafe_allow_html=True)

    inicializar()
    barra_lateral()

    t1, t2, t3, t4 = st.tabs([
        "⚡ Exercício",
        "📊 Estatísticas",
        "📋 Histórico",
        "📖 Referência Morse",
    ])

    with t1:
        aba_exercicio()
    with t2:
        aba_estatisticas()
    with t3:
        aba_historico()
    with t4:
        aba_referencia()


if __name__ == '__main__':
    main()
