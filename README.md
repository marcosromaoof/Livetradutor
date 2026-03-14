# LiveTradutor

Aplicativo desktop para traducao de audio em tempo real:

`Audio do sistema (browser/live) -> Deepgram STT -> IA traduz -> Piper TTS -> Playback`

---

## 1) O que o app faz

- Captura o audio do sistema (WASAPI loopback no Windows).
- Transcreve em streaming com Deepgram.
- Traduz para portugues do Brasil com IA.
- Gera voz local com Piper.
- Reproduz o audio traduzido em fluxo continuo.

Interface:
- `PLAY`: inicia todo o pipeline.
- `STOP`: para tudo e limpa as filas.
- `CONFIG`: configura chaves e modelos.

---

## 2) Requisitos

- Windows 10 ou 11.
- Internet ativa (Deepgram + provedor de traducao usam API online).
- Pasta `piper` presente na raiz do projeto (com `piper.exe` e modelo `.onnx`).
- Python 3.12 (somente para rodar em dev e compilar).

---

## 3) Instalacao e execucao (modo desenvolvimento)

No PowerShell, dentro da pasta do projeto:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
py .\main.py
```

---

## 4) Configuracao inicial no app (passo a passo)

1. Abra o app e clique em `CONFIG`.
2. Preencha `Deepgram API Key` (obrigatorio para transcricao).
3. Escolha o `Provedor principal` da traducao.
4. Preencha a chave do provedor escolhido:
   - Gemini **ou**
   - Groq **ou**
   - DeepSeek
5. Clique em `Buscar modelos` do provedor que voce vai usar.
6. (Opcional) Ative fallback automatico e configure outra chave de backup.
7. Clique em `Salvar`.
8. Clique em `PLAY` para iniciar.

Regra importante:
- Voce **nao precisa configurar os 3 provedores de traducao**.
- Basta `Deepgram` + **1** provedor de traducao.

---

## 5) Como obter as chaves de API (links diretos)

### 5.1 Deepgram (obrigatorio para STT)

- Console: [https://console.deepgram.com/](https://console.deepgram.com/)
- Guia oficial de criacao de chave: [https://developers.deepgram.com/docs/create-additional-api-keys](https://developers.deepgram.com/docs/create-additional-api-keys)

### 5.2 Gemini (tem camada gratuita)

- Obter chave: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- Documentacao oficial: [https://ai.google.dev/gemini-api/docs/api-key](https://ai.google.dev/gemini-api/docs/api-key)

### 5.3 Groq (tem camada gratuita)

- Console: [https://console.groq.com/](https://console.groq.com/)
- Chaves/API docs: [https://console.groq.com/docs/overview](https://console.groq.com/docs/overview)

### 5.4 DeepSeek (pago)

- Plataforma: [https://platform.deepseek.com/](https://platform.deepseek.com/)
- API Keys: [https://platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys)
- Documentacao: [https://api-docs.deepseek.com/](https://api-docs.deepseek.com/)

Resumo de custo:
- Gemini: possui opcao gratuita.
- Groq: possui opcao gratuita.
- DeepSeek: normalmente pago.

---

## 6) Build do EXE (rodar em PC sem Python)

### 6.1 Compilar localmente

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-build.txt
py .\build_exe.py
```

Saida:
- `dist\LiveTradutor\LiveTradutor.exe`

### 6.2 Como distribuir corretamente

Para outro PC, envie a pasta inteira:
- `dist\LiveTradutor\`

Nao envie apenas o `.exe` isolado, porque os binarios internos e assets do Piper sao necessarios.

---

## 7) GitHub Releases (zip automatico com o EXE)

O workflow ja existe em:
- `.github/workflows/release-windows.yml`

Para gerar release:

```powershell
git add .
git commit -m "release: v1.0.0"
git tag v1.0.0
git push origin main
git push origin v1.0.0
```

O GitHub Actions gera e publica:
- `LiveTradutor-vX.Y.Z-win64.zip`
- `LiveTradutor-vX.Y.Z-win64.sha256.txt`

---

## 8) Logs e arquivos locais

Pasta padrao do app:
- `%APPDATA%\LiveTradutor\`

Arquivos importantes:
- `runtime_settings.json` (config geral sem segredo em texto puro)
- `secure_secrets.db` (cofre de chaves)
- `live_translator.log` (fluxo geral)
- `stt_transcript.log` (texto do STT)
- `ai_translation.log` (entrada/saida da IA)

---

## 9) Seguranca das chaves

- As chaves sao salvas em cofre local (`secure_secrets.db`) com criptografia DPAPI do Windows.
- O botao `Limpar Chaves` apaga todas as chaves salvas localmente.
- Arquivos sensiveis estao no `.gitignore` e nao devem ser versionados.

---

## 10) Solucao de problemas

### Problema: nao traduz nada

Verifique:
- `Deepgram API Key` preenchida.
- Pelo menos 1 chave valida de traducao (Gemini, Groq ou DeepSeek).
- Clique em `Buscar modelos` e depois `Salvar`.

### Problema: erro 429 (rate limit)

- Troque o provedor principal.
- Ative fallback automatico com outro provedor configurado.

### Problema: captura de audio falha

- Garanta que ha audio sendo reproduzido no sistema.
- Use dispositivo de saida padrao no Windows com suporte a loopback.
- Reinicie o app apos mudar dispositivo de audio.

### Problema: modelos nao carregam

- Confira se a chave corresponde ao provedor correto.
- O app tenta identificar automaticamente pelo prefixo da chave.

### Problema: build falha

- Confirme Python 3.12.
- Confirme pasta `piper` na raiz do projeto.
- Rode novamente `pip install -r requirements.txt` e `pip install -r requirements-build.txt`.
